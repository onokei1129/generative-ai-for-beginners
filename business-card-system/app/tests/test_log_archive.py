"""監査ログのアーカイブと破棄（要件§9、open-issues 論点H）。"""

from __future__ import annotations

import gzip
import json
from datetime import timedelta

from conftest import csrf_of, login

from bcards.db import SessionLocal
from bcards.models import AuditLog, LogArchive, utcnow
from bcards.services import log_archive, storage
from bcards.settings_store import set_setting


def _make_logs(db, count: int, *, days_ago: int) -> None:
    when = utcnow() - timedelta(days=days_ago)
    for index in range(count):
        db.add(
            AuditLog(
                user_id="u1",
                user_display_name="テスト 太郎",
                action="card_view",
                target_type="card",
                target_id=f"card-{index}",
                ip_address="10.0.0.1",
                detail={"index": index},
                occurred_at=when + timedelta(seconds=index),
            )
        )
    db.commit()


def test_old_logs_move_to_archive_and_leave_db():
    with SessionLocal() as db:
        _make_logs(db, 5, days_ago=400)
        _make_logs(db, 3, days_ago=10)

        archive = log_archive.archive_audit_logs(db)
        db.commit()

        assert archive is not None
        assert archive.row_count == 5
        # 期限内のログはDBに残る
        assert db.query(AuditLog).count() == 3
        assert storage.exists(archive.storage_key)


def test_archive_contents_are_readable_and_complete():
    with SessionLocal() as db:
        _make_logs(db, 4, days_ago=400)
        archive = log_archive.archive_audit_logs(db)
        db.commit()

        payload = gzip.decompress(log_archive.read_archive(archive))
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]

    assert len(rows) == 4
    assert {row["target_id"] for row in rows} == {f"card-{i}" for i in range(4)}
    # 監査に必要な項目が欠けていないこと（要件§9）
    for key in ("user_display_name", "action", "ip_address", "occurred_at", "detail"):
        assert rows[0][key] is not None


def test_archiving_is_disabled_when_setting_is_zero():
    with SessionLocal() as db:
        set_setting(db, "audit_log_archive_after_days", 0, None)
        _make_logs(db, 3, days_ago=400)
        assert log_archive.archive_audit_logs(db) is None
        assert db.query(AuditLog).count() == 3


def test_expired_archives_are_purged_with_their_objects():
    with SessionLocal() as db:
        _make_logs(db, 2, days_ago=2000)  # 保持期間(1095日)より古い
        archive = log_archive.archive_audit_logs(db)
        db.commit()
        key = archive.storage_key

        purged = log_archive.purge_expired_archives(db)
        db.commit()

        assert len(purged) == 1
        assert db.query(LogArchive).count() == 0
        assert not storage.exists(key)


def test_retention_zero_keeps_archives_forever():
    with SessionLocal() as db:
        set_setting(db, "audit_log_retention_days", 0, None)
        _make_logs(db, 2, days_ago=5000)
        log_archive.archive_audit_logs(db)
        db.commit()

        assert log_archive.purge_expired_archives(db) == []
        assert db.query(LogArchive).count() == 1


def test_admin_can_run_archive_and_download(client):
    login(client, "admin", "AdminPass123!")
    token = csrf_of(client)
    with SessionLocal() as db:
        _make_logs(db, 3, days_ago=400)

    response = client.post(
        "/admin/audit/archives/run", data={"csrf_token": token}, follow_redirects=False
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        archive = db.query(LogArchive).one()
        assert archive.row_count == 3

    page = client.get("/admin/audit/archives")
    assert page.status_code == 200
    assert "3" in page.text

    download = client.get(f"/admin/audit/archives/{archive.log_archive_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/gzip"
    assert len(gzip.decompress(download.content).decode().splitlines()) == 3

    with SessionLocal() as db:
        # アーカイブ操作とダウンロードの両方が監査ログに残る（要件§9）
        actions = {row.action for row in db.query(AuditLog).all()}
        assert "log_archive" in actions
        assert "log_archive_download" in actions


def test_change_history_is_never_archived():
    """変更履歴は名刺と同じく無期限に保持する（要件§10）。"""
    from bcards.models import ChangeHistory

    with SessionLocal() as db:
        db.add(
            ChangeHistory(
                target_type="card",
                target_id="c1",
                operation="update",
                changed_at=utcnow() - timedelta(days=5000),
            )
        )
        db.commit()

        log_archive.archive_audit_logs(db)
        log_archive.purge_expired_archives(db)
        db.commit()

        assert db.query(ChangeHistory).count() == 1

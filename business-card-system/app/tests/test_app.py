"""要件の主要項目に対する動作確認テスト。"""

from __future__ import annotations

from conftest import csrf_of, drain_queue, login, sample_card_image

from bcards.db import SessionLocal
from bcards.models import (
    AuditLog,
    BusinessCard,
    CardImage,
    ChangeHistory,
    CsvExportLog,
    ImportFile,
    ImportItem,
    ImportJob,
    LoginAttempt,
    Person,
)


# --------------------------------------------------------------------------
# 認証・アクセス制御（要件§6）
# --------------------------------------------------------------------------


def test_login_required(client):
    response = client.get("/cards", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_success_and_failure_are_recorded(client):
    client.post("/login", data={"login_id": "member", "password": "wrong"})
    login(client)
    with SessionLocal() as db:
        results = [a.result for a in db.query(LoginAttempt).order_by(LoginAttempt.attempted_at).all()]
        assert results == ["failure_password", "success"]
        assert db.query(AuditLog).filter(AuditLog.action == "login").count() == 2


def test_member_cannot_access_admin(client):
    login(client)
    assert client.get("/admin").status_code == 403


def test_admin_can_access_admin(client):
    login(client, "admin", "AdminPass123!")
    assert client.get("/admin").status_code == 200


def test_retired_user_cannot_login(client):
    from bcards.models import STATUS_RETIRED, User

    with SessionLocal() as db:
        user = db.query(User).filter(User.login_id == "member").first()
        user.status = STATUS_RETIRED
        db.commit()
    response = client.post("/login", data={"login_id": "member", "password": "MemberPass123!"})
    assert response.status_code == 403
    assert "退職" in response.text


def test_csrf_token_is_required(client):
    login(client)
    response = client.post("/cards/new", data={"last_name": "山田", "csrf_token": "invalid"})
    assert response.status_code == 400


# --------------------------------------------------------------------------
# 取込・OCR（要件§3, §4, §8）
# --------------------------------------------------------------------------


def test_upload_creates_item_pending_review(client):
    login(client)
    token = csrf_of(client)
    response = client.post(
        "/imports/upload",
        data={"csrf_token": token, "source": "mobile_photo"},
        files={"files": ("card.jpg", sample_card_image(), "image/jpeg")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert drain_queue() == 1

    with SessionLocal() as db:
        item = db.query(ImportItem).first()
        assert item is not None
        # OCR結果は自動確定しない（要件§8）
        assert item.status == "pending_review"
        assert item.card_id is None
        # 原本・表示用・サムネイルを保存する（要件§2）
        variants = {
            image.variant
            for image in db.query(CardImage).filter(CardImage.import_item_id == item.import_item_id).all()
        }
        assert variants == {"original", "display", "thumbnail"}


def test_unsupported_format_becomes_error_item(client):
    login(client)
    token = csrf_of(client)
    client.post(
        "/imports/upload",
        data={"csrf_token": token},
        files={"files": ("memo.txt", b"hello", "text/plain")},
    )
    drain_queue()
    with SessionLocal() as db:
        item = db.query(ImportItem).first()
        assert item.status == "error"
        assert item.error_code == "unsupported_format"


def test_review_and_register_flow(client):
    login(client)
    token = csrf_of(client)
    client.post(
        "/imports/upload",
        data={"csrf_token": token},
        files={"files": ("card.jpg", sample_card_image(), "image/jpeg")},
    )
    drain_queue()
    with SessionLocal() as db:
        item_id = db.query(ImportItem).first().import_item_id

    page = client.get(f"/imports/items/{item_id}")
    assert page.status_code == 200
    for label in ("新しい人物として登録する", "旧名刺を履歴として残し", "登録を中止する"):
        assert label in page.text  # 要件§10の6択が提示される

    response = client.post(
        f"/imports/items/{item_id}/register",
        data={
            "csrf_token": token,
            "action": "new_person",
            "last_name": "山田",
            "first_name": "太郎",
            "company_name": "株式会社サンプル商事",
            "title": "部長",
            "tel": "03-1234-5678",
            "email": "taro@example.co.jp",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        item = db.query(ImportItem).first()
        assert item.status == "registered"
        card = db.get(BusinessCard, item.card_id)
        assert card.person.full_name == "山田 太郎"
        assert card.is_latest is True
        assert card.contact_values("email") == ["taro@example.co.jp"]
        # 画像が名刺に紐づく
        assert db.query(CardImage).filter(CardImage.card_id == card.card_id).count() == 3


# --------------------------------------------------------------------------
# 人物と名刺（要件§10）
# --------------------------------------------------------------------------


def _register_card(client, token, **overrides) -> str:
    data = {
        "csrf_token": token,
        "last_name": "山田",
        "first_name": "太郎",
        "company_name": "株式会社サンプル商事",
        "title": "部長",
        "email": "taro@example.co.jp",
    }
    data.update(overrides)
    response = client.post("/cards/new", data=data, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"].split("?")[0].rsplit("/", 1)[1]


def test_duplicate_candidate_is_offered(client):
    login(client)
    token = csrf_of(client)
    _register_card(client, token)

    client.post(
        "/imports/upload",
        data={"csrf_token": token},
        files={"files": ("card.jpg", sample_card_image(), "image/jpeg")},
    )
    drain_queue()
    with SessionLocal() as db:
        item_id = db.query(ImportItem).first().import_item_id

    from bcards.services.dedupe import find_candidates

    with SessionLocal() as db:
        candidates = find_candidates(db, {"last_name": "山田", "first_name": "太郎", "email": "taro@example.co.jp"})
    assert candidates and candidates[0].score == 100  # メール一致は最優先
    assert "メールアドレスが一致" in candidates[0].reasons
    assert client.get(f"/imports/items/{item_id}").status_code == 200


def test_keep_history_keeps_old_card(client):
    """標準動作：旧名刺を残し、新しい名刺を最新とする（要件§10）。"""
    login(client)
    token = csrf_of(client)
    first_id = _register_card(client, token)

    with SessionLocal() as db:
        person_id = db.get(BusinessCard, first_id).person_id

    from types import SimpleNamespace

    from bcards.models import User
    from bcards.services.cards import register_card

    request = SimpleNamespace(
        headers={"user-agent": "test"}, cookies={}, client=SimpleNamespace(host="127.0.0.1"),
        state=SimpleNamespace(),
    )
    with SessionLocal() as db:
        user = db.query(User).filter(User.login_id == "member").first()
        register_card(
            db, request, user,
            fields={"last_name": "山田", "first_name": "太郎", "company_name": "株式会社サンプル商事", "title": "取締役"},
            action="keep_history", person_id=person_id, reason="昇進",
        )
        db.commit()

    with SessionLocal() as db:
        cards = db.query(BusinessCard).filter(BusinessCard.person_id == person_id).all()
        assert len(cards) == 2
        assert all(card.deleted_at is None for card in cards)  # 旧名刺は削除されない
        assert sum(1 for card in cards if card.is_latest) == 1
        old = db.get(BusinessCard, first_id)
        assert old.is_latest is False
        assert old.superseded_by_card_id is not None
        assert db.query(Person).filter(Person.deleted_at.is_(None)).count() == 1


def test_edit_records_change_history(client):
    login(client)
    token = csrf_of(client)
    card_id = _register_card(client, token)

    client.post(
        f"/cards/{card_id}/edit",
        data={
            "csrf_token": token,
            "last_name": "山田",
            "first_name": "太郎",
            "company_name": "株式会社サンプル商事",
            "title": "本部長",
            "reason": "役職変更のため",
        },
        follow_redirects=False,
    )
    with SessionLocal() as db:
        entry = (
            db.query(ChangeHistory)
            .filter(ChangeHistory.target_id == card_id, ChangeHistory.operation == "update")
            .first()
        )
        assert entry is not None
        assert entry.before_value["役職"] == "部長"
        assert entry.after_value["役職"] == "本部長"
        assert entry.change_reason == "役職変更のため"
        assert entry.ip_address  # 変更端末・IPを記録（要件§7）


def test_delete_restore_and_purge(client):
    """論理削除 → 管理者による復元 → 完全削除（要件§10）。"""
    login(client)
    token = csrf_of(client)
    card_id = _register_card(client, token)

    client.post(f"/cards/{card_id}/delete", data={"csrf_token": token, "reason": "重複のため"})
    with SessionLocal() as db:
        card = db.get(BusinessCard, card_id)
        assert card.deleted_at is not None
        assert card.delete_reason == "重複のため"

    # 一般利用者には表示されない
    assert client.get(f"/cards/{card_id}").status_code == 404

    client.post("/logout", data={"csrf_token": token})
    login(client, "admin", "AdminPass123!")
    admin_token = csrf_of(client)
    assert "重複のため" in client.get("/admin/deleted").text

    client.post(f"/admin/deleted/{card_id}/restore", data={"csrf_token": admin_token})
    with SessionLocal() as db:
        assert db.get(BusinessCard, card_id).deleted_at is None

    client.post(f"/cards/{card_id}/delete", data={"csrf_token": admin_token, "reason": "再削除"})
    # 完全削除には理由が必須
    client.post(f"/admin/deleted/{card_id}/purge", data={"csrf_token": admin_token, "reason": ""})
    with SessionLocal() as db:
        assert db.get(BusinessCard, card_id) is not None

    client.post(f"/admin/deleted/{card_id}/purge", data={"csrf_token": admin_token, "reason": "誤登録のため"})
    with SessionLocal() as db:
        assert db.get(BusinessCard, card_id) is None
        # 監査ログと変更履歴は残る（要件§10）
        assert db.query(AuditLog).filter(AuditLog.action == "physical_delete").count() == 1
        assert (
            db.query(ChangeHistory)
            .filter(ChangeHistory.target_id == card_id, ChangeHistory.operation == "physical_delete")
            .count()
            == 1
        )


def test_member_cannot_purge(client):
    login(client)
    token = csrf_of(client)
    card_id = _register_card(client, token)
    client.post(f"/cards/{card_id}/delete", data={"csrf_token": token, "reason": "テスト"})
    assert client.post(f"/admin/deleted/{card_id}/purge", data={"csrf_token": token, "reason": "x"}).status_code == 403


# --------------------------------------------------------------------------
# 共有範囲（要件§7）
# --------------------------------------------------------------------------


def test_all_users_can_see_cards_registered_by_others(client):
    login(client)
    token = csrf_of(client)
    _register_card(client, token, last_name="佐藤", first_name="花子", email="hanako@example.jp")
    client.post("/logout", data={"csrf_token": token})

    login(client, "admin", "AdminPass123!")
    listing = client.get("/cards?q=佐藤")
    assert listing.status_code == 200
    assert "佐藤 花子" in listing.text


# --------------------------------------------------------------------------
# CSV出力（要件§9）
# --------------------------------------------------------------------------


def test_csv_export_records_audit_log(client):
    login(client)
    token = csrf_of(client)
    _register_card(client, token)

    response = client.post(
        "/export",
        data={
            "csrf_token": token,
            "scope": "all",
            "columns": ["person_name", "company_name", "title"],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    body = response.content.decode("utf-8-sig")
    assert "無断" in body  # 注意表示
    assert "氏名,会社名,役職" in body
    assert "山田 太郎" in body

    with SessionLocal() as db:
        log = db.query(CsvExportLog).one()
        assert log.record_count == 1
        assert log.exported_columns == ["person_name", "company_name", "title"]
        assert log.control_number.startswith("BC-")
        audit = db.get(AuditLog, log.audit_log_id)
        assert audit.action == "csv_export"
        assert audit.user_display_name == "一般 次郎"
        assert audit.ip_address


def test_large_export_shows_confirmation(client):
    login(client)
    token = csrf_of(client)
    _register_card(client, token)

    from bcards.settings_store import set_setting

    with SessionLocal() as db:
        set_setting(db, "csv_large_export_threshold", 1, None)
        db.commit()

    response = client.post("/export", data={"csrf_token": token, "scope": "all", "columns": "person_name"})
    assert response.status_code == 200
    assert "大量出力の確認" in response.text
    with SessionLocal() as db:
        assert db.query(CsvExportLog).count() == 0  # 確認前は出力されない

    response = client.post(
        "/export",
        data={"csrf_token": token, "scope": "all", "columns": "person_name", "confirmed": "1"},
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.query(CsvExportLog).one().confirmed_large_export is True


# --------------------------------------------------------------------------
# 設定（要件§7 編集権限の切替）
# --------------------------------------------------------------------------


def test_edit_policy_owner_and_admin(client):
    login(client, "admin", "AdminPass123!")
    admin_token = csrf_of(client)
    card_id = _register_card(client, admin_token)
    client.post("/logout", data={"csrf_token": admin_token})

    from bcards.settings_store import set_setting

    with SessionLocal() as db:
        set_setting(db, "card_edit_policy", "owner_and_admin", None)
        db.commit()

    login(client)
    assert client.get(f"/cards/{card_id}/edit").status_code == 403

    with SessionLocal() as db:
        set_setting(db, "card_edit_policy", "all_users", None)
        db.commit()
    assert client.get(f"/cards/{card_id}/edit").status_code == 200


# --------------------------------------------------------------------------
# 取込キュー（要件§3 一時的な大量取込）
# --------------------------------------------------------------------------


def test_upload_returns_immediately_and_queues_files(client):
    """アップロードはキューに積むだけで、その場ではOCRしない。"""
    login(client)
    token = csrf_of(client)
    files = [("files", (f"card{i}.jpg", sample_card_image(), "image/jpeg")) for i in range(3)]
    response = client.post(
        "/imports/upload", data={"csrf_token": token}, files=files, follow_redirects=False
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        queued = db.query(ImportFile).filter(ImportFile.status == "queued").all()
        assert len(queued) == 3
        assert db.query(ImportItem).count() == 0  # まだ処理されていない
        assert db.get(ImportJob, queued[0].import_job_id).status == "queued"

    assert drain_queue() == 3
    with SessionLocal() as db:
        assert db.query(ImportItem).filter(ImportItem.status == "pending_review").count() == 3
        assert db.query(ImportFile).filter(ImportFile.status == "done").count() == 3
        job = db.query(ImportJob).first()
        assert job.status == "done"
        assert job.finished_at is not None


def test_queue_claim_is_exclusive(client):
    """2つのワーカーが同じファイルを取得しない。"""
    login(client)
    token = csrf_of(client)
    client.post(
        "/imports/upload",
        data={"csrf_token": token},
        files={"files": ("card.jpg", sample_card_image(), "image/jpeg")},
    )

    from bcards.services.queue import claim_next

    with SessionLocal() as db_a, SessionLocal() as db_b:
        first = claim_next(db_a, "worker-a")
        second = claim_next(db_b, "worker-b")
    assert first is not None
    assert second is None
    assert first.status == "processing"
    assert first.attempts == 1


def test_stale_processing_file_is_requeued(client):
    """ワーカーが落ちて処理中のまま残ったファイルはキューへ戻る。"""
    login(client)
    token = csrf_of(client)
    client.post(
        "/imports/upload",
        data={"csrf_token": token},
        files={"files": ("card.jpg", sample_card_image(), "image/jpeg")},
    )

    from datetime import timedelta

    from bcards.models import utcnow
    from bcards.services.queue import claim_next, requeue_stale

    with SessionLocal() as db:
        claimed = claim_next(db, "dead-worker")
        assert claimed is not None
        claimed.locked_at = utcnow() - timedelta(hours=1)
        db.commit()

        assert requeue_stale(db, lease_seconds=60) == 1
        db.refresh(claimed)
        assert claimed.status == "queued"

    assert drain_queue() == 1
    with SessionLocal() as db:
        assert db.query(ImportItem).filter(ImportItem.status == "pending_review").count() == 1


def test_broken_file_marks_queue_entry_as_error(client):
    login(client)
    token = csrf_of(client)
    client.post(
        "/imports/upload",
        data={"csrf_token": token},
        files={"files": ("broken.jpg", b"not really a jpeg", "image/jpeg")},
    )
    assert drain_queue() == 1

    with SessionLocal() as db:
        import_file = db.query(ImportFile).one()
        assert import_file.status == "error"
        assert import_file.error_message
        assert db.query(ImportJob).one().status == "failed"
        # 明細側にもエラーが残り、取込状況の画面から確認できる
        assert db.query(ImportItem).filter(ImportItem.status == "error").count() == 1


def test_import_status_page_shows_queue(client):
    login(client)
    token = csrf_of(client)
    client.post(
        "/imports/upload",
        data={"csrf_token": token},
        files={"files": ("card.jpg", sample_card_image(), "image/jpeg")},
    )
    page = client.get("/imports")
    assert page.status_code == 200
    assert "キュー待ち" in page.text

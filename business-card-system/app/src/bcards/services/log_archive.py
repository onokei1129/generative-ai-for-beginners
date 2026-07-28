"""監査ログのアーカイブと破棄（要件§9、open-issues 論点H）。

方針:

- 監査ログは追記専用。アプリの通常操作では更新・削除しない
- `audit_log_archive_after_days` を過ぎたログは、オブジェクトストレージへ
  JSONL(gzip) として書き出したうえでDBから削除する（DBの肥大化を防ぐ）
- `audit_log_retention_days` を過ぎたアーカイブは実体ごと破棄する
- **変更履歴（change_history）はアーカイブしない**。要件§10 のとおり
  名刺データに保存期限がなく、変更履歴は名刺の一部として無期限に保持する

アーカイブの作成・破棄そのものも監査ログに残るため、
「いつ・誰が・どの期間のログを・何件退避したか」を後から追える。
"""

from __future__ import annotations

import gzip
import io
import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import AuditLog, LogArchive, User, utcnow
from ..settings_store import get_setting
from . import storage

BATCH_SIZE = 5000


def _serialize(entry: AuditLog) -> dict:
    return {
        "audit_log_id": entry.audit_log_id,
        "user_id": entry.user_id,
        "user_display_name": entry.user_display_name,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "result": entry.result,
        "error_message": entry.error_message,
        "ip_address": entry.ip_address,
        "device_id": entry.device_id,
        "user_agent": entry.user_agent,
        "os_info": entry.os_info,
        "detail": entry.detail,
        "occurred_at": entry.occurred_at.isoformat() if entry.occurred_at else None,
    }


def archive_candidates(db: Session, cutoff: datetime) -> int:
    return db.query(AuditLog).filter(AuditLog.occurred_at < cutoff).count()


def archive_audit_logs(
    db: Session, *, user: User | None = None, cutoff: datetime | None = None
) -> LogArchive | None:
    """期限を過ぎた監査ログをアーカイブへ移す。対象が無ければ None。

    書き出しが成功してからDBの行を削除する。逆順にすると、
    書き出しに失敗した場合にログが失われる。
    """
    if cutoff is None:
        days = int(get_setting(db, "audit_log_archive_after_days") or 0)
        if days <= 0:
            return None
        cutoff = utcnow() - timedelta(days=days)

    entries = (
        db.query(AuditLog)
        .filter(AuditLog.occurred_at < cutoff)
        .order_by(AuditLog.occurred_at)
        .limit(BATCH_SIZE)
        .all()
    )
    if not entries:
        return None

    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as gz:
        for entry in entries:
            gz.write((json.dumps(_serialize(entry), ensure_ascii=False) + "\n").encode("utf-8"))
    payload = buffer.getvalue()

    period_from = entries[0].occurred_at
    period_to = entries[-1].occurred_at
    key = storage.put_bytes(payload, suffix=".jsonl.gz", prefix="log-archives/audit")

    archive = LogArchive(
        log_type="audit_log",
        period_from=period_from,
        period_to=period_to,
        row_count=len(entries),
        storage_key=key,
        byte_size=len(payload),
        checksum=storage.checksum(payload),
        created_by=user.user_id if user else None,
    )
    db.add(archive)
    db.flush()

    for entry in entries:
        db.delete(entry)
    db.flush()
    return archive


def purge_expired_archives(db: Session, *, now: datetime | None = None) -> list[LogArchive]:
    """保持期間を過ぎたアーカイブを実体ごと破棄する。戻り値は破棄したもの。"""
    days = int(get_setting(db, "audit_log_retention_days") or 0)
    if days <= 0:
        return []  # 無期限。破棄しない
    cutoff = (now or utcnow()) - timedelta(days=days)

    expired = db.query(LogArchive).filter(LogArchive.period_to < cutoff).all()
    for archive in expired:
        try:
            storage.delete(archive.storage_key)
        except Exception:  # 実体が既にない場合も記録は消す
            pass
        db.delete(archive)
    if expired:
        db.flush()
    return expired


def read_archive(archive: LogArchive) -> bytes:
    return storage.get_bytes(archive.storage_key)


def list_archives(db: Session, log_type: str = "audit_log") -> list[LogArchive]:
    return (
        db.query(LogArchive)
        .filter(LogArchive.log_type == log_type)
        .order_by(LogArchive.period_to.desc())
        .all()
    )


def archive_stats(db: Session) -> dict:
    """管理画面に出す要約。"""
    archive_days = int(get_setting(db, "audit_log_archive_after_days") or 0)
    retention_days = int(get_setting(db, "audit_log_retention_days") or 0)
    now = utcnow()

    archives = list_archives(db)
    pending = (
        archive_candidates(db, now - timedelta(days=archive_days)) if archive_days > 0 else 0
    )
    return {
        "archive_after_days": archive_days,
        "retention_days": retention_days,
        "db_rows": db.query(AuditLog).count(),
        "pending_rows": pending,
        "archives": archives,
        "archived_rows": sum(a.row_count for a in archives),
        "archived_bytes": sum(a.byte_size for a in archives),
        "oldest_in_db": (
            db.query(AuditLog).order_by(AuditLog.occurred_at).first().occurred_at
            if db.query(AuditLog).count()
            else None
        ),
    }

"""監査ログ・変更履歴の記録（要件§7, §9, 確定仕様21）。

監査ログは追記専用。アプリからは更新・削除を行わない。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, ChangeHistory, User


def client_ip(request: Request) -> str:
    """接続元IPを求める（要件§6のアクセス制限とログの根拠になる値）。

    X-Forwarded-For は利用者が自由に付けられるため、そのまま信用するとIP制限を
    回避されてしまう。信頼できるプロキシ（BCARDS_TRUSTED_PROXIES）経由の接続に
    限り、ヘッダの中で最も外側にある「信頼できないアドレス」を採用する。
    """
    from .config import settings
    from .security import ip_in_cidrs

    peer = request.client.host if request.client else "unknown"
    trusted = settings.trusted_proxy_cidrs
    if not trusted or not ip_in_cidrs(peer, trusted):
        return peer

    forwarded = request.headers.get("x-forwarded-for") or ""
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    for candidate in reversed(chain):
        if not ip_in_cidrs(candidate, trusted):
            return candidate
    return peer


def os_from_user_agent(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    ua = user_agent.lower()
    for needle, label in (
        ("windows nt 10", "Windows 10/11"),
        ("windows", "Windows"),
        ("iphone", "iOS"),
        ("ipad", "iPadOS"),
        ("android", "Android"),
        ("mac os x", "macOS"),
        ("linux", "Linux"),
    ):
        if needle in ua:
            return label
    return None


def log_audit(
    db: Session,
    request: Request,
    user: User | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    result: str = "success",
    error_message: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    user_agent = request.headers.get("user-agent")
    entry = AuditLog(
        user_id=user.user_id if user else None,
        user_display_name=user.display_name if user else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        error_message=error_message,
        ip_address=client_ip(request),
        device_id=request.cookies.get("bcards_device"),
        user_agent=user_agent,
        os_info=os_from_user_agent(user_agent),
        detail=detail,
    )
    db.add(entry)
    db.flush()
    return entry


def record_change(
    db: Session,
    request: Request,
    user: User | None,
    *,
    target_type: str,
    target_id: str,
    operation: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> ChangeHistory:
    entry = ChangeHistory(
        target_type=target_type,
        target_id=target_id,
        operation=operation,
        changed_by=user.user_id if user else None,
        changed_by_name=user.display_name if user else None,
        device_id=request.cookies.get("bcards_device"),
        ip_address=client_ip(request),
        before_value=before,
        after_value=after,
        change_reason=reason,
    )
    db.add(entry)
    db.flush()
    return entry


def diff_dicts(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """変更のあった項目だけを抽出する（変更履歴の容量を抑えるため）。"""
    changed_before: dict[str, Any] = {}
    changed_after: dict[str, Any] = {}
    for key in set(before) | set(after):
        b, a = before.get(key), after.get(key)
        if b != a:
            changed_before[key] = b
            changed_after[key] = a
    return changed_before, changed_after

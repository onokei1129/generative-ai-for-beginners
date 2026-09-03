"""リクエスト共通処理（セッション・権限・IP制限）。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .audit import client_ip
from .db import get_db
from .models import ROLE_ADMIN, AllowedIp, User
from .security import ip_in_cidrs
from .settings_store import get_setting


class AuthRequired(Exception):
    def __init__(self, reason: str = "login") -> None:
        self.reason = reason


class AccessDenied(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


def session_data(request: Request) -> dict[str, Any]:
    return getattr(request.state, "session", {}) or {}


def _load_user(request: Request, db: Session) -> User | None:
    data = session_data(request)
    user_id = data.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or not user.can_login:
        return None
    return user


def allowed_cidrs(db: Session, *, for_member: bool) -> list[str]:
    rows = db.query(AllowedIp).filter(AllowedIp.enabled.is_(True)).all()
    result = []
    for row in rows:
        if row.applies_to == "member_only" and not for_member:
            continue
        result.append(row.cidr)
    return result


def check_network_access(request: Request, db: Session, user: User) -> None:
    """要件§6：一般利用者は社内ネットワークのみ。管理者は条件付きで社外可。"""
    from .config import settings as app_settings

    if not app_settings.enforce_ip_restriction:
        return

    ip = client_ip(request)
    cidrs = allowed_cidrs(db, for_member=user.role != ROLE_ADMIN)
    if not cidrs:
        # 許可IPが未登録の状態では制限をかけない（初期セットアップ用）。
        # 管理画面のバナーで登録を促す。
        return
    if ip_in_cidrs(ip, cidrs):
        return

    # 社内IP以外からのアクセス
    if user.role != ROLE_ADMIN:
        raise AccessDenied("社内ネットワーク以外からはアクセスできません。（要件§6）")

    mode = get_setting(db, "admin_external_access_mode")
    if mode == "denied":
        raise AccessDenied("管理者の社外アクセスは現在禁止に設定されています。")
    if mode == "on_demand" and not user.external_access_allowed:
        raise AccessDenied("この管理者アカウントは社外アクセスが許可されていません。")
    if not session_data(request).get("mfa_verified"):
        raise AuthRequired("mfa")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _load_user(request, db)
    if user is None:
        raise AuthRequired()
    if user.mfa_enabled and not session_data(request).get("mfa_verified"):
        raise AuthRequired("mfa")
    check_network_access(request, db, user)
    request.state.user = user
    return user


def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者のみ実行できます。")
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    try:
        return _load_user(request, db)
    except Exception:
        return None


def verify_csrf(request: Request, token: str | None) -> None:
    expected = session_data(request).get("csrf")
    if not expected or not token or token != expected:
        raise HTTPException(status_code=400, detail="不正なリクエストです（CSRFトークン不一致）。")


def idle_timeout_seconds(db: Session, user: User | None, request: Request) -> int:
    minutes = int(get_setting(db, "session_idle_timeout_minutes") or 60)
    if user and user.is_admin and session_data(request).get("external_access"):
        minutes = int(get_setting(db, "admin_external_idle_timeout_minutes") or 15)
    return max(1, minutes) * 60


def now_epoch() -> int:
    return int(time.time())


def start_session(request: Request, user: User, *, mfa_verified: bool, external: bool) -> None:
    """ログイン成功時に新しいセッションを発行する。"""
    from .security import new_csrf_token

    request.state.new_session = {
        "user_id": user.user_id,
        "login_at": now_epoch(),
        "last_seen": now_epoch(),
        "csrf": new_csrf_token(),
        "mfa_verified": mfa_verified,
        "external_access": external,
    }


def update_session(request: Request, **values: Any) -> None:
    data = dict(session_data(request))
    data.update(values)
    data["last_seen"] = now_epoch()
    request.state.new_session = data
    request.state.session = data


def clear_session(request: Request) -> None:
    request.state.new_session = None
    request.state.clear_session = True

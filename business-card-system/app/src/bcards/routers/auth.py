"""ログイン・多要素認証・ログアウト（要件§6）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..audit import client_ip, log_audit, os_from_user_agent
from ..config import settings
from ..db import get_db
from ..deps import (
    ROLE_ADMIN,
    allowed_cidrs,
    clear_session,
    session_data,
    start_session,
    update_session,
)
from ..models import Device, LoginAttempt, User, new_id, utcnow
from ..security import ip_in_cidrs, verify_password, verify_totp
from ..settings_store import get_setting
from ..web import render

router = APIRouter()


def _record_attempt(db: Session, request: Request, login_id: str, user: User | None, result: str) -> None:
    db.add(
        LoginAttempt(
            login_id=login_id,
            user_id=user.user_id if user else None,
            result=result,
            ip_address=client_ip(request),
            device_id=request.cookies.get(settings.device_cookie),
            user_agent=request.headers.get("user-agent"),
        )
    )


def _is_external(db: Session, request: Request, user: User) -> bool:
    if not settings.enforce_ip_restriction:
        return False
    cidrs = allowed_cidrs(db, for_member=user.role != ROLE_ADMIN)
    if not cidrs:
        return False
    return not ip_in_cidrs(client_ip(request), cidrs)


def _ensure_device(db: Session, request: Request, user: User) -> str:
    device_id = request.cookies.get(settings.device_cookie)
    user_agent = request.headers.get("user-agent")
    device = db.get(Device, device_id) if device_id else None
    if device is None:
        device_id = device_id or new_id()
        device = Device(
            device_id=device_id,
            user_id=user.user_id,
            user_agent=user_agent,
            os_info=os_from_user_agent(user_agent),
        )
        db.add(device)
        request.state.new_device_id = device_id
    else:
        device.user_id = user.user_id
        device.user_agent = user_agent
        device.os_info = os_from_user_agent(user_agent)
        device.last_seen_at = utcnow()
    return device_id


@router.get("/login")
def login_form(request: Request):
    if session_data(request).get("user_id"):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", {"title": "ログイン"})


@router.post("/login")
def login(
    request: Request,
    login_id: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.login_id == login_id.strip()).first()

    if user is None or not verify_password(password, user.password_hash):
        _record_attempt(db, request, login_id, user, "failure_password")
        log_audit(db, request, None, "login", result="failure", error_message="IDまたはパスワードが違います")
        db.commit()
        return render(
            request,
            "login.html",
            {"title": "ログイン", "error": "IDまたはパスワードが違います。"},
            status_code=401,
        )

    if not user.can_login:
        _record_attempt(db, request, login_id, user, "blocked_status")
        log_audit(db, request, user, "login", result="failure", error_message=f"status={user.status}")
        db.commit()
        message = "このアカウントは退職済みです。" if user.status == "retired" else "このアカウントは利用停止中です。"
        return render(request, "login.html", {"title": "ログイン", "error": message}, status_code=403)

    external = _is_external(db, request, user)
    if external:
        if user.role != ROLE_ADMIN:
            _record_attempt(db, request, login_id, user, "blocked_ip")
            log_audit(db, request, user, "login", result="failure", error_message="社外IPからのアクセス")
            db.commit()
            return render(
                request,
                "login.html",
                {"title": "ログイン", "error": "社内ネットワーク以外からはログインできません。（要件§6）"},
                status_code=403,
            )
        mode = get_setting(db, "admin_external_access_mode")
        if mode == "denied" or (mode == "on_demand" and not user.external_access_allowed):
            _record_attempt(db, request, login_id, user, "blocked_ip")
            log_audit(db, request, user, "login", result="failure", error_message="管理者の社外アクセス不許可")
            db.commit()
            return render(
                request,
                "login.html",
                {"title": "ログイン", "error": "この環境からの管理者アクセスは許可されていません。"},
                status_code=403,
            )
        if not user.mfa_enabled:
            _record_attempt(db, request, login_id, user, "blocked_mfa")
            log_audit(db, request, user, "login", result="failure", error_message="社外アクセスにMFA未設定")
            db.commit()
            return render(
                request,
                "login.html",
                {
                    "title": "ログイン",
                    "error": "社外からのアクセスには多要素認証の設定が必要です。社内から設定してください。",
                },
                status_code=403,
            )

    _ensure_device(db, request, user)
    needs_mfa = user.mfa_enabled
    start_session(request, user, mfa_verified=not needs_mfa, external=external)

    if needs_mfa:
        db.commit()
        return RedirectResponse("/mfa", status_code=303)

    user.last_login_at = utcnow()
    _record_attempt(db, request, login_id, user, "success")
    log_audit(db, request, user, "login", detail={"external": external})
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.get("/mfa")
def mfa_form(request: Request, db: Session = Depends(get_db)):
    data = session_data(request)
    if not data.get("user_id"):
        return RedirectResponse("/login", status_code=303)
    if data.get("mfa_verified"):
        return RedirectResponse("/", status_code=303)
    return render(request, "mfa.html", {"title": "多要素認証"})


@router.post("/mfa")
def mfa_verify(request: Request, code: str = Form(...), db: Session = Depends(get_db)):
    data = session_data(request)
    user = db.get(User, data.get("user_id", ""))
    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not user.mfa_secret or not verify_totp(user.mfa_secret, code):
        _record_attempt(db, request, user.login_id, user, "failure_mfa")
        log_audit(db, request, user, "login", result="failure", error_message="MFAコード不一致")
        db.commit()
        return render(
            request,
            "mfa.html",
            {"title": "多要素認証", "error": "認証コードが正しくありません。"},
            status_code=401,
        )

    update_session(request, mfa_verified=True)
    user.last_login_at = utcnow()
    _record_attempt(db, request, user.login_id, user, "success")
    log_audit(db, request, user, "login", detail={"mfa": True, "external": data.get("external_access", False)})
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = db.get(User, session_data(request).get("user_id", "")) if session_data(request) else None
    if user:
        log_audit(db, request, user, "logout")
        db.commit()
    clear_session(request)
    return RedirectResponse("/login?msg=ログアウトしました。", status_code=303)

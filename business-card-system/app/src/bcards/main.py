"""名刺一元管理システム アプリケーション本体。"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .db import SessionLocal, init_db
from .deps import AccessDenied, AuthRequired
from .models import Device, User, utcnow
from .routers import admin, auth, cards, exports, home, imports
from .security import dump_session, load_session
from .settings_store import get_setting
from .web import render

MAX_SESSION_AGE = 12 * 60 * 60  # 署名の絶対上限。無操作タイムアウトは別途判定する


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="名刺一元管理システム", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    """セッションの読み込み・無操作タイムアウト・端末識別IDの発行。"""
    token = request.cookies.get(settings.session_cookie)
    session = load_session(token, MAX_SESSION_AGE) if token else None

    idle_limit = 60 * 60
    if session:
        with SessionLocal() as db:
            minutes = int(get_setting(db, "session_idle_timeout_minutes") or 60)
            if session.get("external_access"):
                minutes = int(get_setting(db, "admin_external_idle_timeout_minutes") or 15)
            idle_limit = max(1, minutes) * 60
        last_seen = int(session.get("last_seen", 0))
        if last_seen and time.time() - last_seen > idle_limit:
            session = None
            request.state.session_expired = True

    request.state.session = session or {}
    device_id = request.cookies.get(settings.device_cookie)

    response = await call_next(request)

    if hasattr(request.state, "new_session"):
        session = request.state.new_session  # ログイン時は新セッション、ログアウト時は None
    elif session is not None:
        session = dict(session)
        session["last_seen"] = int(time.time())

    if session:
        response.set_cookie(
            settings.session_cookie,
            dump_session(session),
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookie,
            max_age=MAX_SESSION_AGE,
        )
    elif token or getattr(request.state, "clear_session", False):
        response.delete_cookie(settings.session_cookie)

    new_device_id = getattr(request.state, "new_device_id", None) or device_id
    if new_device_id and new_device_id != device_id:
        response.set_cookie(
            settings.device_cookie,
            new_device_id,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookie,
            max_age=400 * 24 * 3600,
        )
    return response


@app.middleware("http")
async def device_registration_middleware(request: Request, call_next):
    """端末識別ID（要件§9）を発行し、最終利用日時を更新する。"""
    device_id = request.cookies.get(settings.device_cookie)
    if device_id:
        with SessionLocal() as db:
            device = db.get(Device, device_id)
            if device is not None:
                device.last_seen_at = utcnow()
                db.commit()
    return await call_next(request)


@app.exception_handler(AuthRequired)
async def auth_required_handler(request: Request, exc: AuthRequired) -> RedirectResponse:
    if exc.reason == "mfa":
        return RedirectResponse("/mfa", status_code=303)
    expired = getattr(request.state, "session_expired", False)
    suffix = "?err=一定時間操作がなかったため自動ログアウトしました。" if expired else ""
    return RedirectResponse(f"/login{suffix}", status_code=303)


@app.exception_handler(AccessDenied)
async def access_denied_handler(request: Request, exc: AccessDenied) -> HTMLResponse:
    return render(request, "error.html", {"title": "アクセスできません", "message": exc.message}, status_code=403)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc) -> HTMLResponse:
    detail = getattr(exc, "detail", "権限がありません。")
    return render(request, "error.html", {"title": "権限がありません", "message": detail}, status_code=403)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc) -> HTMLResponse:
    return render(
        request,
        "error.html",
        {"title": "ページが見つかりません", "message": "URLをご確認ください。"},
        status_code=404,
    )


app.include_router(auth.router)
app.include_router(home.router)
app.include_router(cards.router)
app.include_router(imports.router)
app.include_router(exports.router)
app.include_router(admin.router)


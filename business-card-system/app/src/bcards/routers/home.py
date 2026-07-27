"""ホーム・マイページ。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..db import get_db
from ..deps import current_user, verify_csrf
from ..models import (
    ITEM_ERROR,
    ITEM_REVIEW,
    BusinessCard,
    ImportItem,
    ImportJob,
    Notification,
    Person,
    User,
)
from ..security import generate_totp_secret, hash_password, totp_provisioning_uri, verify_password, verify_totp
from ..services.importer import storage_usage_percent
from ..settings_store import get_setting
from ..web import render

router = APIRouter()


@router.get("/")
def home(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    recent_cards = (
        db.query(BusinessCard)
        .filter(BusinessCard.deleted_at.is_(None))
        .order_by(BusinessCard.created_at.desc())
        .limit(8)
        .all()
    )
    my_pending = (
        db.query(ImportItem)
        .join(ImportJob, ImportJob.import_job_id == ImportItem.import_job_id)
        .filter(ImportJob.created_by == user.user_id, ImportItem.status.in_([ITEM_REVIEW, ITEM_ERROR]))
        .order_by(ImportItem.created_at.desc())
        .limit(10)
        .all()
    )
    stats = {
        "cards": db.query(BusinessCard).filter(BusinessCard.deleted_at.is_(None)).count(),
        "persons": db.query(Person).filter(Person.deleted_at.is_(None)).count(),
        "pending": db.query(ImportItem).filter(ImportItem.status == ITEM_REVIEW).count(),
        "errors": db.query(ImportItem).filter(ImportItem.status == ITEM_ERROR).count(),
    }

    notifications = []
    storage_percent = storage_usage_percent()
    if user.is_admin:
        threshold = float(get_setting(db, "storage_alert_threshold_percent") or 80)
        if storage_percent >= threshold:
            notifications.append(
                f"保存容量が {storage_percent}% に達しました（閾値 {threshold}%）。容量の拡張を検討してください。"
            )
        notifications += [
            n.message
            for n in db.query(Notification)
            .filter(Notification.read_at.is_(None))
            .order_by(Notification.created_at.desc())
            .limit(5)
            .all()
        ]

    return render(
        request,
        "home.html",
        {
            "title": "ホーム",
            "recent_cards": recent_cards,
            "my_pending": my_pending,
            "stats": stats,
            "notifications": notifications,
            "storage_percent": storage_percent,
        },
    )


@router.get("/mypage")
def mypage(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    my_cards = (
        db.query(BusinessCard)
        .filter(BusinessCard.created_by == user.user_id, BusinessCard.deleted_at.is_(None))
        .order_by(BusinessCard.created_at.desc())
        .limit(20)
        .all()
    )
    pending_secret = request.query_params.get("secret")
    return render(
        request,
        "mypage.html",
        {
            "title": "マイページ",
            "my_cards": my_cards,
            "pending_secret": pending_secret,
            "otpauth": totp_provisioning_uri(pending_secret, user.login_id) if pending_secret else None,
        },
    )


@router.post("/mypage/password")
def change_password(
    request: Request,
    csrf_token: str = Form(...),
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    verify_csrf(request, csrf_token)
    if not verify_password(current_password, user.password_hash):
        return RedirectResponse("/mypage?err=現在のパスワードが違います。", status_code=303)
    if len(new_password) < 10:
        return RedirectResponse("/mypage?err=パスワードは10文字以上にしてください。", status_code=303)
    user.password_hash = hash_password(new_password)
    log_audit(db, request, user, "password_change")
    db.commit()
    return RedirectResponse("/mypage?msg=パスワードを変更しました。", status_code=303)


@router.post("/mypage/mfa/start")
def start_mfa(
    request: Request,
    csrf_token: str = Form(...),
    user: User = Depends(current_user),
):
    verify_csrf(request, csrf_token)
    secret = generate_totp_secret()
    return RedirectResponse(f"/mypage?secret={secret}", status_code=303)


@router.post("/mypage/mfa/enable")
def enable_mfa(
    request: Request,
    csrf_token: str = Form(...),
    secret: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    verify_csrf(request, csrf_token)
    if not verify_totp(secret, code):
        return RedirectResponse(f"/mypage?secret={secret}&err=認証コードが一致しません。", status_code=303)
    user.mfa_secret = secret
    user.mfa_enabled = True
    log_audit(db, request, user, "mfa_enable")
    db.commit()
    return RedirectResponse("/mypage?msg=多要素認証を有効にしました。", status_code=303)


@router.post("/mypage/mfa/disable")
def disable_mfa(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    verify_csrf(request, csrf_token)
    user.mfa_enabled = False
    user.mfa_secret = None
    log_audit(db, request, user, "mfa_disable")
    db.commit()
    return RedirectResponse("/mypage?msg=多要素認証を無効にしました。", status_code=303)

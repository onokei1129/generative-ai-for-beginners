"""管理機能（要件§1, §2, §6, §9, §10）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..audit import log_audit, record_change
from ..config import settings as app_settings
from ..db import get_db
from ..deps import current_admin, verify_csrf
from ..models import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    STATUS_ACTIVE,
    STATUS_RETIRED,
    STATUS_SUSPENDED,
    AllowedIp,
    AuditLog,
    BusinessCard,
    CardImage,
    ChangeHistory,
    CsvExportLog,
    Device,
    LoginAttempt,
    Person,
    User,
    utcnow,
)
from ..security import hash_password
from ..services import storage
from ..services.cards import merge_persons, purge_card, restore_card
from ..settings_store import DEFAULTS, DESCRIPTIONS, all_settings, set_setting
from ..web import render

router = APIRouter(prefix="/admin")


@router.get("")
def admin_home(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    used = storage.total_bytes()
    stats = {
        "users": db.query(User).count(),
        "active_users": db.query(User).filter(User.status == STATUS_ACTIVE).count(),
        "cards": db.query(BusinessCard).filter(BusinessCard.deleted_at.is_(None)).count(),
        "deleted_cards": db.query(BusinessCard).filter(BusinessCard.deleted_at.isnot(None)).count(),
        "storage_used_mb": round(used / 1024 / 1024, 1),
        "storage_quota_mb": round(app_settings.storage_quota_bytes / 1024 / 1024, 1),
        "storage_percent": round(used / max(1, app_settings.storage_quota_bytes) * 100, 2),
        "allowed_ips": db.query(AllowedIp).filter(AllowedIp.enabled.is_(True)).count(),
    }
    return render(request, "admin/index.html", {"title": "管理", "stats": stats})


# --------------------------------------------------------------------------
# 利用者管理（要件§1）
# --------------------------------------------------------------------------


@router.get("/users")
def user_list(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    users = db.query(User).order_by(User.status, User.display_name).all()
    return render(request, "admin/users.html", {"title": "利用者管理", "users": users})


@router.post("/users")
async def create_user(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    login_id = (form.get("login_id") or "").strip()
    if not login_id or db.query(User).filter(User.login_id == login_id).first():
        return RedirectResponse("/admin/users?err=ログインIDが未入力か既に使われています。", status_code=303)
    password = (form.get("password") or "").strip()
    if len(password) < 10:
        return RedirectResponse("/admin/users?err=初期パスワードは10文字以上にしてください。", status_code=303)

    user = User(
        login_id=login_id,
        email=(form.get("email") or "").strip(),
        display_name=(form.get("display_name") or login_id).strip(),
        password_hash=hash_password(password),
        role=ROLE_ADMIN if form.get("role") == ROLE_ADMIN else ROLE_MEMBER,
        status=STATUS_ACTIVE,
        created_by=admin.user_id,
        updated_by=admin.user_id,
    )
    db.add(user)
    db.flush()
    log_audit(db, request, admin, "user_admin", target_type="user", target_id=user.user_id,
              detail={"operation": "create", "login_id": login_id})
    db.commit()
    return RedirectResponse("/admin/users?msg=利用者を登録しました。", status_code=303)


@router.post("/users/{user_id}")
async def update_user(user_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))

    before = {"role": user.role, "status": user.status, "external": user.external_access_allowed}
    operation = form.get("operation")

    if operation == "status":
        status = form.get("status")
        if status in (STATUS_ACTIVE, STATUS_SUSPENDED, STATUS_RETIRED):
            if status == STATUS_RETIRED and user.user_id == admin.user_id:
                return RedirectResponse("/admin/users?err=自分自身を退職にはできません。", status_code=303)
            user.status = status
            # 要件§10：退職者はアカウントのみ停止し、登録した名刺は保持する
            user.retired_at = utcnow() if status == STATUS_RETIRED else None
    elif operation == "role":
        if user.user_id == admin.user_id and form.get("role") != ROLE_ADMIN:
            return RedirectResponse("/admin/users?err=自分自身の管理者権限は外せません。", status_code=303)
        user.role = ROLE_ADMIN if form.get("role") == ROLE_ADMIN else ROLE_MEMBER
        if user.role != ROLE_ADMIN:
            user.external_access_allowed = False
    elif operation == "external":
        if user.role != ROLE_ADMIN:
            return RedirectResponse("/admin/users?err=社外アクセスは管理者のみ許可できます。", status_code=303)
        user.external_access_allowed = form.get("external") == "1"
    elif operation == "password":
        password = (form.get("password") or "").strip()
        if len(password) < 10:
            return RedirectResponse("/admin/users?err=パスワードは10文字以上にしてください。", status_code=303)
        user.password_hash = hash_password(password)
    elif operation == "reset_mfa":
        user.mfa_enabled = False
        user.mfa_secret = None

    user.updated_by = admin.user_id
    after = {"role": user.role, "status": user.status, "external": user.external_access_allowed}
    record_change(db, request, admin, target_type="user", target_id=user.user_id,
                  operation="update", before=before, after=after, reason=form.get("reason"))
    log_audit(db, request, admin, "user_admin", target_type="user", target_id=user.user_id,
              detail={"operation": operation})
    db.commit()
    return RedirectResponse("/admin/users?msg=利用者情報を更新しました。", status_code=303)


# --------------------------------------------------------------------------
# アクセス制御（要件§6, §9）
# --------------------------------------------------------------------------


@router.get("/access")
def access_control(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    ips = db.query(AllowedIp).order_by(AllowedIp.label).all()
    devices = db.query(Device).order_by(Device.last_seen_at.desc()).limit(100).all()
    return render(
        request,
        "admin/access.html",
        {
            "title": "アクセス制御",
            "ips": ips,
            "devices": devices,
            "users": {u.user_id: u for u in db.query(User).all()},
            "enforce": app_settings.enforce_ip_restriction,
        },
    )


@router.post("/access/ips")
async def add_ip(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    cidr = (form.get("cidr") or "").strip()
    label = (form.get("label") or "").strip() or cidr
    if not cidr:
        return RedirectResponse("/admin/access?err=IPアドレス／CIDRを入力してください。", status_code=303)
    import ipaddress

    try:
        ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return RedirectResponse("/admin/access?err=IPアドレスの形式が正しくありません。", status_code=303)

    entry = AllowedIp(
        cidr=cidr,
        label=label,
        applies_to=form.get("applies_to") or "all",
        created_by=admin.user_id,
        updated_by=admin.user_id,
    )
    db.add(entry)
    log_audit(db, request, admin, "setting_change", target_type="allowed_ip",
              detail={"operation": "add", "cidr": cidr})
    db.commit()
    return RedirectResponse("/admin/access?msg=許可IPを追加しました。", status_code=303)


@router.post("/access/ips/{allowed_ip_id}/toggle")
async def toggle_ip(allowed_ip_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    entry = db.get(AllowedIp, allowed_ip_id)
    if entry is None:
        raise HTTPException(status_code=404)
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    entry.enabled = not entry.enabled
    log_audit(db, request, admin, "setting_change", target_type="allowed_ip", target_id=allowed_ip_id,
              detail={"enabled": entry.enabled})
    db.commit()
    return RedirectResponse("/admin/access?msg=許可IPの状態を変更しました。", status_code=303)


@router.post("/access/devices/{device_id}")
async def update_device(device_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404)
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    device.device_name = (form.get("device_name") or "").strip() or None
    device.is_trusted = form.get("is_trusted") == "1"
    log_audit(db, request, admin, "setting_change", target_type="device", target_id=device_id)
    db.commit()
    return RedirectResponse("/admin/access?msg=端末情報を更新しました。", status_code=303)


# --------------------------------------------------------------------------
# 削除済み名刺（要件§10）
# --------------------------------------------------------------------------


@router.get("/deleted")
def deleted_cards(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    cards = (
        db.query(BusinessCard)
        .filter(BusinessCard.deleted_at.isnot(None))
        .order_by(BusinessCard.deleted_at.desc())
        .limit(200)
        .all()
    )
    return render(
        request,
        "admin/deleted.html",
        {"title": "削除済み名刺", "cards": cards, "users": {u.user_id: u for u in db.query(User).all()}},
    )


@router.post("/deleted/{card_id}/restore")
async def restore(card_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    card = db.get(BusinessCard, card_id)
    if card is None or card.deleted_at is None:
        raise HTTPException(status_code=404)
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    restore_card(db, request, admin, card, (form.get("reason") or "").strip() or None)
    db.commit()
    return RedirectResponse("/admin/deleted?msg=名刺を復元しました。", status_code=303)


@router.post("/deleted/{card_id}/purge")
async def purge(card_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    card = db.get(BusinessCard, card_id)
    if card is None or card.deleted_at is None:
        raise HTTPException(status_code=404)
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    reason = (form.get("reason") or "").strip()
    if not reason:
        return RedirectResponse("/admin/deleted?err=完全削除には理由の入力が必要です。", status_code=303)
    purge_card(db, request, admin, card, reason)
    db.commit()
    return RedirectResponse("/admin/deleted?msg=名刺を完全削除しました。", status_code=303)


# --------------------------------------------------------------------------
# 人物統合（要件§10）
# --------------------------------------------------------------------------


@router.get("/merge")
def merge_form(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    keyword = (request.query_params.get("q") or "").strip()
    persons = []
    if keyword:
        like = f"%{keyword}%"
        persons = (
            db.query(Person)
            .filter(Person.deleted_at.is_(None))
            .filter((Person.last_name.like(like)) | (Person.first_name.like(like)))
            .limit(50)
            .all()
        )
    return render(request, "admin/merge.html", {"title": "人物の統合", "persons": persons, "q": keyword})


@router.post("/merge")
async def do_merge(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    source = db.get(Person, (form.get("source_id") or "").strip())
    target = db.get(Person, (form.get("target_id") or "").strip())
    if source is None or target is None or source.person_id == target.person_id:
        return RedirectResponse("/admin/merge?err=統合元と統合先を正しく選択してください。", status_code=303)
    merge_persons(db, request, admin, source, target, (form.get("reason") or "").strip() or None)
    db.commit()
    return RedirectResponse(f"/persons/{target.person_id}?msg=人物を統合しました。", status_code=303)


# --------------------------------------------------------------------------
# ログ照会（要件§6, §9）
# --------------------------------------------------------------------------


@router.get("/audit")
def audit_logs(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    params = dict(request.query_params)
    query = db.query(AuditLog)
    if params.get("action"):
        query = query.filter(AuditLog.action == params["action"])
    if params.get("user_id"):
        query = query.filter(AuditLog.user_id == params["user_id"])
    if params.get("result"):
        query = query.filter(AuditLog.result == params["result"])
    logs = query.order_by(AuditLog.occurred_at.desc()).limit(300).all()
    actions = [row[0] for row in db.query(AuditLog.action).distinct().all()]
    return render(
        request,
        "admin/audit.html",
        {
            "title": "監査ログ",
            "logs": logs,
            "actions": sorted(actions),
            "users": db.query(User).order_by(User.display_name).all(),
            "params": params,
        },
    )


@router.get("/exports")
def export_logs(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    logs = (
        db.query(CsvExportLog, AuditLog)
        .join(AuditLog, AuditLog.audit_log_id == CsvExportLog.audit_log_id)
        .order_by(AuditLog.occurred_at.desc())
        .limit(300)
        .all()
    )
    return render(request, "admin/exports.html", {"title": "CSV出力ログ", "logs": logs})


@router.get("/logins")
def login_history(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    attempts = db.query(LoginAttempt).order_by(LoginAttempt.attempted_at.desc()).limit(300).all()
    return render(request, "admin/logins.html", {"title": "ログイン履歴", "attempts": attempts})


@router.get("/changes")
def change_logs(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    history = db.query(ChangeHistory).order_by(ChangeHistory.changed_at.desc()).limit(300).all()
    return render(request, "admin/changes.html", {"title": "変更履歴（全体）", "history": history})


# --------------------------------------------------------------------------
# システム設定（要件§2, §6, §7, §9）
# --------------------------------------------------------------------------


@router.get("/settings")
def settings_form(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    return render(
        request,
        "admin/settings.html",
        {
            "title": "システム設定",
            "values": all_settings(db),
            "defaults": DEFAULTS,
            "descriptions": DESCRIPTIONS,
        },
    )


@router.post("/settings")
async def update_settings(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    before = all_settings(db)

    for key, default in DEFAULTS.items():
        if isinstance(default, bool):
            value: object = form.get(key) == "1"
        elif isinstance(default, int):
            raw = (form.get(key) or "").strip()
            if not raw.lstrip("-").isdigit():
                continue
            value = int(raw)
        else:
            raw = (form.get(key) or "").strip()
            if not raw:
                continue
            value = raw
        set_setting(db, key, value, admin.user_id)

    db.flush()
    after = all_settings(db)
    changed_before = {k: v for k, v in before.items() if after.get(k) != v}
    changed_after = {k: v for k, v in after.items() if before.get(k) != v}
    if changed_before or changed_after:
        record_change(db, request, admin, target_type="app_setting", target_id="system",
                      operation="update", before=changed_before, after=changed_after,
                      reason=form.get("reason"))
    log_audit(db, request, admin, "setting_change", detail={"changed": list(changed_after)})
    db.commit()
    return RedirectResponse("/admin/settings?msg=設定を保存しました。", status_code=303)


@router.get("/storage")
def storage_status(request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    used = storage.total_bytes()
    images = db.query(CardImage).count()
    by_variant = {}
    for variant in ("original", "display", "thumbnail"):
        rows = db.query(CardImage).filter(CardImage.variant == variant).all()
        by_variant[variant] = {
            "count": len(rows),
            "mb": round(sum(r.byte_size for r in rows) / 1024 / 1024, 2),
        }
    return render(
        request,
        "admin/storage.html",
        {
            "title": "ストレージ・利用状況",
            "used_mb": round(used / 1024 / 1024, 2),
            "quota_mb": round(app_settings.storage_quota_bytes / 1024 / 1024, 2),
            "percent": round(used / max(1, app_settings.storage_quota_bytes) * 100, 2),
            "images": images,
            "by_variant": by_variant,
            "free_mb": round(storage.free_space_bytes() / 1024 / 1024, 2),
        },
    )

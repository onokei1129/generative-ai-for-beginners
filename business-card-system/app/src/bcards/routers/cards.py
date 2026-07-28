"""名刺・人物・会社の閲覧と編集（要件§7, §10）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..db import get_db
from ..deps import current_user, verify_csrf
from ..models import (
    BusinessCard,
    CardImage,
    ChangeHistory,
    Company,
    Person,
    User,
)
from ..services import storage
from ..services.cards import can_edit, register_card, soft_delete_card, update_card
from ..services.search import build_query, describe_conditions
from ..settings_store import get_setting
from ..web import render

router = APIRouter()

PAGE_SIZE = 20


def _form_fields(form: dict[str, str]) -> dict[str, str]:
    keys = (
        "last_name", "first_name", "last_name_kana", "first_name_kana",
        "company_name", "department_name", "title", "card_type",
        "postal_code", "address", "tel", "mobile", "fax", "email", "url",
        "exchanged_on", "note",
    )
    return {key: (form.get(key) or "").strip() for key in keys}


@router.get("/cards")
def card_list(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    params = dict(request.query_params)
    page = max(1, int(params.get("page") or 1))
    query = build_query(db, params)
    total = query.count()
    cards = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()

    log_audit(db, request, user, "search", detail={"conditions": describe_conditions(params), "hits": total})
    db.commit()

    companies = db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.name).all()
    users = db.query(User).order_by(User.display_name).all()
    return render(
        request,
        "cards_list.html",
        {
            "title": "名刺検索",
            "cards": cards,
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "params": params,
            "companies": companies,
            "users": users,
            "thumbnails": _thumbnail_map(db, cards),
        },
    )


def _thumbnail_map(db: Session, cards: list[BusinessCard]) -> dict[str, str]:
    ids = [card.card_id for card in cards]
    if not ids:
        return {}
    rows = (
        db.query(CardImage)
        .filter(CardImage.card_id.in_(ids), CardImage.variant == "thumbnail", CardImage.side == "front")
        .all()
    )
    return {row.card_id: row.card_image_id for row in rows if row.card_id}


@router.get("/cards/new")
def new_card_form(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return render(request, "card_edit.html", {"title": "名刺の手入力登録", "card": None, "fields": {}})


@router.post("/cards/new")
async def create_card(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    fields = _form_fields(form)
    card = register_card(
        db, request, user,
        fields=fields, action="new_person", source="manual", reason=form.get("reason") or "手入力登録",
    )
    db.commit()
    return RedirectResponse(f"/cards/{card.card_id}?msg=名刺を登録しました。", status_code=303)


@router.get("/cards/{card_id}")
def card_detail(card_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    card = db.get(BusinessCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    if card.deleted_at is not None and not user.is_admin:
        raise HTTPException(status_code=404)

    images = (
        db.query(CardImage)
        .filter(CardImage.card_id == card_id, CardImage.variant.in_(("display", "original")))
        .all()
    )
    history = (
        db.query(ChangeHistory)
        .filter(ChangeHistory.target_type == "business_card", ChangeHistory.target_id == card_id)
        .order_by(ChangeHistory.changed_at.desc())
        .limit(5)
        .all()
    )
    other_cards = (
        db.query(BusinessCard)
        .filter(BusinessCard.person_id == card.person_id, BusinessCard.card_id != card_id)
        .order_by(BusinessCard.created_at.desc())
        .all()
    )

    log_audit(db, request, user, "view_card", target_type="business_card", target_id=card_id)
    db.commit()
    return render(
        request,
        "card_detail.html",
        {
            "title": "名刺詳細",
            "card": card,
            "images": images,
            "history": history,
            "other_cards": other_cards,
            "editable": can_edit(db, card, user),
            "registered_by": db.get(User, card.created_by) if card.created_by else None,
        },
    )


@router.get("/cards/{card_id}/edit")
def edit_card_form(card_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    card = db.get(BusinessCard, card_id)
    if card is None or card.deleted_at is not None:
        raise HTTPException(status_code=404)
    if not can_edit(db, card, user):
        raise HTTPException(status_code=403, detail="この名刺を編集する権限がありません。")

    fields = {
        "last_name": card.person.last_name or "",
        "first_name": card.person.first_name or "",
        "last_name_kana": card.person.last_name_kana or "",
        "first_name_kana": card.person.first_name_kana or "",
        "company_name": card.company_display,
        "department_name": card.department_name or "",
        "title": card.title or "",
        "card_type": card.card_type or "",
        "postal_code": card.postal_code or "",
        "address": card.address or "",
        "tel": ", ".join(card.contact_values("tel")),
        "mobile": ", ".join(card.contact_values("mobile")),
        "fax": ", ".join(card.contact_values("fax")),
        "email": ", ".join(card.contact_values("email")),
        "url": ", ".join(card.contact_values("url")),
        "exchanged_on": card.exchanged_on.strftime("%Y-%m-%d") if card.exchanged_on else "",
        "note": card.note or "",
    }
    return render(
        request,
        "card_edit.html",
        {
            "title": "名刺の編集",
            "card": card,
            "fields": fields,
            "require_reason": bool(get_setting(db, "require_reason_on_edit")),
        },
    )


@router.post("/cards/{card_id}/edit")
async def edit_card(card_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    card = db.get(BusinessCard, card_id)
    if card is None or card.deleted_at is not None:
        raise HTTPException(status_code=404)
    if not can_edit(db, card, user):
        raise HTTPException(status_code=403, detail="この名刺を編集する権限がありません。")

    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    reason = (form.get("reason") or "").strip()
    if get_setting(db, "require_reason_on_edit") and not reason:
        return RedirectResponse(f"/cards/{card_id}/edit?err=変更理由を入力してください。", status_code=303)

    update_card(db, request, user, card, _form_fields(form), reason or None)
    db.commit()
    return RedirectResponse(f"/cards/{card_id}?msg=名刺を更新しました。", status_code=303)


@router.post("/cards/{card_id}/delete")
async def delete_card(card_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    card = db.get(BusinessCard, card_id)
    if card is None or card.deleted_at is not None:
        raise HTTPException(status_code=404)
    if not can_edit(db, card, user):
        raise HTTPException(status_code=403, detail="この名刺を削除する権限がありません。")

    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    reason = (form.get("reason") or "").strip()
    if get_setting(db, "require_reason_on_overwrite_delete") and not reason:
        return RedirectResponse(f"/cards/{card_id}?err=削除理由を入力してください。", status_code=303)

    soft_delete_card(db, request, user, card, reason or None)
    db.commit()
    return RedirectResponse("/cards?msg=名刺を削除しました（管理者が復元できます）。", status_code=303)


@router.get("/cards/{card_id}/history")
def card_history(card_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    card = db.get(BusinessCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    history = (
        db.query(ChangeHistory)
        .filter(ChangeHistory.target_type == "business_card", ChangeHistory.target_id == card_id)
        .order_by(ChangeHistory.changed_at.desc())
        .all()
    )
    return render(request, "history.html", {"title": "変更履歴", "card": card, "history": history})


@router.get("/images/{card_image_id}")
def serve_image(card_image_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    image = db.get(CardImage, card_image_id)
    if image is None or not storage.exists(image.storage_key):
        raise HTTPException(status_code=404)
    if image.variant == "original":
        log_audit(db, request, user, "view_image", target_type="card_image", target_id=card_image_id)
        db.commit()
    return Response(content=storage.get_bytes(image.storage_key), media_type=image.mime_type)


@router.get("/persons/{person_id}")
def person_detail(person_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404)
    cards = (
        db.query(BusinessCard)
        .filter(BusinessCard.person_id == person_id)
        .order_by(BusinessCard.is_latest.desc(), BusinessCard.created_at.desc())
        .all()
    )
    visible = [c for c in cards if c.deleted_at is None or user.is_admin]
    log_audit(db, request, user, "view_person", target_type="person", target_id=person_id)
    db.commit()
    return render(
        request,
        "person_detail.html",
        {
            "title": "人物詳細",
            "person": person,
            "cards": visible,
            "thumbnails": _thumbnail_map(db, visible),
        },
    )


@router.get("/companies")
def company_list(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    keyword = (request.query_params.get("q") or "").strip()
    query = db.query(Company).filter(Company.deleted_at.is_(None))
    if keyword:
        query = query.filter(Company.name.like(f"%{keyword}%"))
    companies = query.order_by(Company.name).limit(200).all()
    counts = {
        company.company_id: db.query(BusinessCard)
        .filter(BusinessCard.company_id == company.company_id, BusinessCard.deleted_at.is_(None))
        .count()
        for company in companies
    }
    return render(
        request,
        "companies.html",
        {"title": "会社一覧", "companies": companies, "counts": counts, "q": keyword},
    )


@router.get("/companies/{company_id}")
def company_detail(company_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404)
    cards = (
        db.query(BusinessCard)
        .filter(BusinessCard.company_id == company_id, BusinessCard.deleted_at.is_(None))
        .order_by(BusinessCard.is_latest.desc(), BusinessCard.created_at.desc())
        .all()
    )
    return render(
        request,
        "company_detail.html",
        {"title": "会社詳細", "company": company, "cards": cards, "thumbnails": _thumbnail_map(db, cards)},
    )

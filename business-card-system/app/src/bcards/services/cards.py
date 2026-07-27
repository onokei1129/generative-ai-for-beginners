"""名刺・人物・会社の登録更新（要件§7, §10）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from ..audit import diff_dicts, log_audit, record_change
from ..models import (
    BusinessCard,
    CardContact,
    CardImage,
    Company,
    Person,
    User,
    utcnow,
)
from .ocr.parser import normalize_company, normalize_name, normalize_phone

CONTACT_FIELDS = (("tel", "tel"), ("mobile", "mobile"), ("fax", "fax"), ("email", "email"), ("url", "url"))

CARD_TEXT_FIELDS = (
    "company_name_raw",
    "department_name",
    "title",
    "card_type",
    "postal_code",
    "address",
    "note",
)


def card_snapshot(card: BusinessCard) -> dict[str, Any]:
    """変更履歴の before/after に使うスナップショット。"""
    return {
        "氏名": card.person.full_name if card.person else "",
        "会社名": card.company_display,
        "部署": card.department_name or "",
        "役職": card.title or "",
        "郵便番号": card.postal_code or "",
        "住所": card.address or "",
        "電話": ", ".join(card.contact_values("tel")),
        "携帯": ", ".join(card.contact_values("mobile")),
        "FAX": ", ".join(card.contact_values("fax")),
        "メール": ", ".join(card.contact_values("email")),
        "URL": ", ".join(card.contact_values("url")),
        "名刺種別": card.card_type or "",
        "名刺交換日": card.exchanged_on.strftime("%Y-%m-%d") if card.exchanged_on else "",
        "備考": card.note or "",
        "最新": card.is_latest,
    }


def get_or_create_company(db: Session, name: str, user: User | None) -> Company | None:
    name = (name or "").strip()
    if not name:
        return None
    normalized = normalize_company(name)
    company = (
        db.query(Company)
        .filter(Company.name_normalized == normalized, Company.deleted_at.is_(None))
        .first()
    )
    if company:
        return company
    company = Company(
        name=name,
        name_normalized=normalized,
        created_by=user.user_id if user else None,
        updated_by=user.user_id if user else None,
    )
    db.add(company)
    db.flush()
    return company


def get_or_create_person(db: Session, fields: dict[str, Any], user: User | None) -> Person:
    person = Person(
        last_name=(fields.get("last_name") or "").strip() or None,
        first_name=(fields.get("first_name") or "").strip() or None,
        last_name_kana=(fields.get("last_name_kana") or "").strip() or None,
        first_name_kana=(fields.get("first_name_kana") or "").strip() or None,
        created_by=user.user_id if user else None,
        updated_by=user.user_id if user else None,
    )
    person.full_name_normalized = normalize_name(f"{person.last_name or ''}{person.first_name or ''}")
    db.add(person)
    db.flush()
    return person


def update_person_names(db: Session, person: Person, fields: dict[str, Any], user: User | None) -> None:
    changed = False
    for attr, key in (
        ("last_name", "last_name"),
        ("first_name", "first_name"),
        ("last_name_kana", "last_name_kana"),
        ("first_name_kana", "first_name_kana"),
    ):
        value = (fields.get(key) or "").strip() or None
        if value and getattr(person, attr) != value:
            setattr(person, attr, value)
            changed = True
    if changed:
        person.full_name_normalized = normalize_name(f"{person.last_name or ''}{person.first_name or ''}")
        person.updated_by = user.user_id if user else None


def _set_contacts(db: Session, card: BusinessCard, fields: dict[str, Any]) -> None:
    for contact in list(card.contacts):
        db.delete(contact)
    card.contacts.clear()
    db.flush()
    for key, contact_type in CONTACT_FIELDS:
        raw = (fields.get(key) or "").strip()
        if not raw:
            continue
        normalized = (
            normalize_phone(raw)
            if contact_type in ("tel", "mobile", "fax")
            else raw.lower()
        )
        card.contacts.append(
            CardContact(
                card_id=card.card_id,
                contact_type=contact_type,
                value_raw=raw,
                value_normalized=normalized,
            )
        )


def apply_fields(db: Session, card: BusinessCard, fields: dict[str, Any], user: User | None) -> None:
    company_name = (fields.get("company_name") or "").strip()
    company = get_or_create_company(db, company_name, user)
    card.company_id = company.company_id if company else None
    card.company_name_raw = company_name or None
    card.department_name = (fields.get("department_name") or "").strip() or None
    card.title = (fields.get("title") or "").strip() or None
    card.card_type = (fields.get("card_type") or "").strip() or None
    card.postal_code = (fields.get("postal_code") or "").strip() or None
    card.address = (fields.get("address") or "").strip() or None
    card.note = (fields.get("note") or "").strip() or None

    exchanged = (fields.get("exchanged_on") or "").strip()
    if exchanged:
        try:
            card.exchanged_on = datetime.strptime(exchanged, "%Y-%m-%d")
        except ValueError:
            card.exchanged_on = None
    else:
        card.exchanged_on = None

    card.updated_by = user.user_id if user else None
    _set_contacts(db, card, fields)


def _demote_previous_latest(db: Session, person_id: str, keep_card_id: str | None = None) -> None:
    query = db.query(BusinessCard).filter(
        BusinessCard.person_id == person_id,
        BusinessCard.is_latest.is_(True),
        BusinessCard.deleted_at.is_(None),
    )
    if keep_card_id:
        query = query.filter(BusinessCard.card_id != keep_card_id)
    for card in query.all():
        card.is_latest = False


def attach_images(db: Session, card: BusinessCard, image_ids: list[str]) -> None:
    if not image_ids:
        return
    for image in db.query(CardImage).filter(CardImage.card_image_id.in_(image_ids)).all():
        image.card_id = card.card_id


def register_card(
    db: Session,
    request: Request,
    user: User,
    *,
    fields: dict[str, Any],
    action: str,
    person_id: str | None = None,
    target_card_id: str | None = None,
    image_ids: list[str] | None = None,
    source: str = "file_upload",
    reason: str | None = None,
    ocr_confidence: float | None = None,
) -> BusinessCard:
    """要件§10の6択に対応した登録処理。

    action: new_person / add_to_person / overwrite / replace / keep_history
    """
    image_ids = image_ids or []

    if action == "overwrite":
        card = db.get(BusinessCard, target_card_id)
        if card is None:
            raise ValueError("上書き対象の名刺が見つかりません。")
        before = card_snapshot(card)
        update_person_names(db, card.person, fields, user)
        apply_fields(db, card, fields, user)
        card.verified_by_user_id = user.user_id
        card.verified_at = utcnow()
        attach_images(db, card, image_ids)
        db.flush()
        after = card_snapshot(card)
        b, a = diff_dicts(before, after)
        record_change(
            db, request, user,
            target_type="business_card", target_id=card.card_id,
            operation="update", before=b, after=a, reason=reason,
        )
        log_audit(db, request, user, "overwrite_card", target_type="business_card", target_id=card.card_id)
        return card

    if action == "new_person" or not person_id:
        person = get_or_create_person(db, fields, user)
        record_change(
            db, request, user,
            target_type="person", target_id=person.person_id,
            operation="create", after={"氏名": person.full_name}, reason=reason,
        )
    else:
        person = db.get(Person, person_id)
        if person is None:
            raise ValueError("対象の人物が見つかりません。")
        update_person_names(db, person, fields, user)

    card = BusinessCard(
        person_id=person.person_id,
        source=source,
        is_latest=True,
        status="active",
        ocr_confidence=ocr_confidence,
        verified_by_user_id=user.user_id,
        verified_at=utcnow(),
        exchanged_by_user_id=user.user_id,
        created_by=user.user_id,
        updated_by=user.user_id,
    )
    db.add(card)
    db.flush()
    apply_fields(db, card, fields, user)
    attach_images(db, card, image_ids)

    if action == "replace" and target_card_id:
        old = db.get(BusinessCard, target_card_id)
        if old is not None:
            before = card_snapshot(old)
            old.deleted_at = utcnow()
            old.deleted_by = user.user_id
            old.delete_reason = reason or "新しい名刺への置換"
            old.is_latest = False
            old.superseded_by_card_id = card.card_id
            record_change(
                db, request, user,
                target_type="business_card", target_id=old.card_id,
                operation="logical_delete", before=before, after=None, reason=old.delete_reason,
            )
    elif action in ("keep_history", "add_to_person"):
        for old in (
            db.query(BusinessCard)
            .filter(
                BusinessCard.person_id == person.person_id,
                BusinessCard.card_id != card.card_id,
                BusinessCard.is_latest.is_(True),
                BusinessCard.deleted_at.is_(None),
            )
            .all()
        ):
            old.superseded_by_card_id = card.card_id

    _demote_previous_latest(db, person.person_id, keep_card_id=card.card_id)
    person.latest_card_id = card.card_id
    db.flush()

    record_change(
        db, request, user,
        target_type="business_card", target_id=card.card_id,
        operation="create", after=card_snapshot(card), reason=reason,
    )
    audit_action = {"replace": "replace_card"}.get(action, "create_card")
    log_audit(
        db, request, user, audit_action,
        target_type="business_card", target_id=card.card_id,
        detail={"action": action, "person_id": person.person_id},
    )
    return card


def update_card(
    db: Session,
    request: Request,
    user: User,
    card: BusinessCard,
    fields: dict[str, Any],
    reason: str | None,
) -> BusinessCard:
    before = card_snapshot(card)
    update_person_names(db, card.person, fields, user)
    apply_fields(db, card, fields, user)
    db.flush()
    after = card_snapshot(card)
    b, a = diff_dicts(before, after)
    if b or a:
        record_change(
            db, request, user,
            target_type="business_card", target_id=card.card_id,
            operation="update", before=b, after=a, reason=reason,
        )
    log_audit(db, request, user, "update_card", target_type="business_card", target_id=card.card_id)
    return card


def soft_delete_card(
    db: Session, request: Request, user: User, card: BusinessCard, reason: str | None
) -> None:
    before = card_snapshot(card)
    card.deleted_at = utcnow()
    card.deleted_by = user.user_id
    card.delete_reason = reason
    was_latest = card.is_latest
    card.is_latest = False
    db.flush()

    if was_latest:
        replacement = (
            db.query(BusinessCard)
            .filter(
                BusinessCard.person_id == card.person_id,
                BusinessCard.deleted_at.is_(None),
            )
            .order_by(BusinessCard.created_at.desc())
            .first()
        )
        if replacement:
            replacement.is_latest = True
            card.person.latest_card_id = replacement.card_id
        else:
            card.person.latest_card_id = None

    record_change(
        db, request, user,
        target_type="business_card", target_id=card.card_id,
        operation="logical_delete", before=before, after=None, reason=reason,
    )
    log_audit(db, request, user, "delete_card", target_type="business_card", target_id=card.card_id)


def restore_card(db: Session, request: Request, user: User, card: BusinessCard, reason: str | None) -> None:
    card.deleted_at = None
    card.deleted_by = None
    card.delete_reason = None
    db.flush()
    _demote_previous_latest(db, card.person_id, keep_card_id=card.card_id)
    card.is_latest = True
    card.person.latest_card_id = card.card_id
    record_change(
        db, request, user,
        target_type="business_card", target_id=card.card_id,
        operation="restore", after=card_snapshot(card), reason=reason,
    )
    log_audit(db, request, user, "restore_card", target_type="business_card", target_id=card.card_id)


def purge_card(db: Session, request: Request, user: User, card: BusinessCard, reason: str | None) -> None:
    """完全削除（管理者のみ）。監査ログと変更履歴は残す（要件§10）。"""
    snapshot = card_snapshot(card)
    card_id = card.card_id
    person = card.person

    for image in db.query(CardImage).filter(CardImage.card_id == card_id).all():
        image.card_id = None
    for contact in list(card.contacts):
        db.delete(contact)
    db.delete(card)
    db.flush()

    if person and person.latest_card_id == card_id:
        replacement = (
            db.query(BusinessCard)
            .filter(BusinessCard.person_id == person.person_id, BusinessCard.deleted_at.is_(None))
            .order_by(BusinessCard.created_at.desc())
            .first()
        )
        person.latest_card_id = replacement.card_id if replacement else None
        if replacement:
            replacement.is_latest = True

    record_change(
        db, request, user,
        target_type="business_card", target_id=card_id,
        operation="physical_delete", before=snapshot, after=None, reason=reason,
    )
    log_audit(db, request, user, "physical_delete", target_type="business_card", target_id=card_id)


def merge_persons(
    db: Session, request: Request, user: User, source: Person, target: Person, reason: str | None
) -> None:
    """人物の統合（管理者のみ）。名刺を統合先へ付け替える。"""
    moved = []
    for card in db.query(BusinessCard).filter(BusinessCard.person_id == source.person_id).all():
        card.person_id = target.person_id
        card.is_latest = False
        moved.append(card.card_id)
    db.flush()

    latest = (
        db.query(BusinessCard)
        .filter(BusinessCard.person_id == target.person_id, BusinessCard.deleted_at.is_(None))
        .order_by(BusinessCard.created_at.desc())
        .first()
    )
    if latest:
        latest.is_latest = True
        target.latest_card_id = latest.card_id

    source.merged_into_person_id = target.person_id
    source.deleted_at = utcnow()
    source.deleted_by = user.user_id
    source.delete_reason = reason or "人物統合"

    record_change(
        db, request, user,
        target_type="person", target_id=source.person_id,
        operation="merge",
        before={"人物": source.full_name},
        after={"統合先": target.full_name, "移動した名刺数": len(moved)},
        reason=reason,
    )
    log_audit(
        db, request, user, "merge_person",
        target_type="person", target_id=target.person_id,
        detail={"source": source.person_id, "moved_cards": len(moved)},
    )

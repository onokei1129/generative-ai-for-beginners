"""名刺の検索（要件§7）。登録利用者は全名刺を検索・閲覧できる。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session, joinedload

from ..models import BusinessCard, CardContact, Company, Person


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def build_query(db: Session, params: dict[str, Any], *, include_deleted: bool = False) -> Query:
    query = (
        db.query(BusinessCard)
        .options(joinedload(BusinessCard.person), joinedload(BusinessCard.company))
        .join(Person, Person.person_id == BusinessCard.person_id)
        .outerjoin(Company, Company.company_id == BusinessCard.company_id)
    )
    if not include_deleted:
        query = query.filter(BusinessCard.deleted_at.is_(None))
    else:
        query = query.filter(BusinessCard.deleted_at.isnot(None))

    keyword = (params.get("q") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        contact_subquery = (
            db.query(CardContact.card_id)
            .filter(CardContact.value_raw.like(like))
            .subquery()
        )
        query = query.filter(
            or_(
                Person.last_name.like(like),
                Person.first_name.like(like),
                Person.last_name_kana.like(like),
                Person.first_name_kana.like(like),
                Company.name.like(like),
                BusinessCard.company_name_raw.like(like),
                BusinessCard.department_name.like(like),
                BusinessCard.title.like(like),
                BusinessCard.address.like(like),
                BusinessCard.note.like(like),
                BusinessCard.card_id.in_(contact_subquery),
            )
        )

    company_id = (params.get("company_id") or "").strip()
    if company_id:
        query = query.filter(BusinessCard.company_id == company_id)

    person_id = (params.get("person_id") or "").strip()
    if person_id:
        query = query.filter(BusinessCard.person_id == person_id)

    created_by = (params.get("created_by") or "").strip()
    if created_by:
        query = query.filter(BusinessCard.created_by == created_by)

    date_from = parse_date(params.get("from"))
    if date_from:
        query = query.filter(BusinessCard.created_at >= date_from)
    date_to = parse_date(params.get("to"))
    if date_to:
        query = query.filter(BusinessCard.created_at < date_to.replace(hour=23, minute=59, second=59))

    if (params.get("latest_only") or "") in ("1", "on", "true"):
        query = query.filter(BusinessCard.is_latest.is_(True))

    card_ids = params.get("card_ids")
    if card_ids:
        query = query.filter(BusinessCard.card_id.in_(card_ids))

    sort = params.get("sort") or "created_desc"
    if sort == "created_asc":
        query = query.order_by(BusinessCard.created_at.asc())
    elif sort == "exchanged_desc":
        query = query.order_by(BusinessCard.exchanged_on.desc().nullslast(), BusinessCard.created_at.desc())
    elif sort == "name":
        query = query.order_by(Person.full_name_normalized.asc())
    else:
        query = query.order_by(BusinessCard.created_at.desc())
    return query


def describe_conditions(params: dict[str, Any]) -> dict[str, Any]:
    """CSV出力ログに残す検索条件（要件§9）。"""
    keys = ("q", "company_id", "person_id", "created_by", "from", "to", "latest_only", "sort")
    return {key: params.get(key) for key in keys if params.get(key)}

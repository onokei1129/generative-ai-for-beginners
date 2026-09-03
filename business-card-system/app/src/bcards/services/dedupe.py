"""重複人物の候補提示（要件§10、open-issues-v0.3.md 論点D）。

自動統合は行わず、スコアと一致理由を提示して利用者に判断させる。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..models import BusinessCard, CardContact, Person
from .ocr.parser import normalize_company, normalize_name, normalize_phone

WEIGHTS = {
    "email": 100,
    "mobile": 85,
    "name_company": 80,
    "kana_company": 65,
    "name": 55,
    "tel_company": 60,
}

REASON_LABELS = {
    "email": "メールアドレスが一致",
    "mobile": "携帯電話番号が一致",
    "name_company": "氏名と会社名が一致",
    "kana_company": "ふりがなと会社名が一致",
    "name": "氏名が一致",
    "tel_company": "電話番号と会社名が一致",
}


@dataclass
class Candidate:
    person_id: str
    person_name: str
    company_name: str
    score: int
    reasons: list[str]
    latest_card_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "person_id": self.person_id,
            "person_name": self.person_name,
            "company_name": self.company_name,
            "score": self.score,
            "reasons": self.reasons,
            "latest_card_id": self.latest_card_id,
        }


def _person_company(db: Session, person: Person) -> str:
    card = (
        db.query(BusinessCard)
        .filter(BusinessCard.person_id == person.person_id, BusinessCard.deleted_at.is_(None))
        .order_by(BusinessCard.is_latest.desc(), BusinessCard.created_at.desc())
        .first()
    )
    return card.company_display if card else ""


def find_candidates(db: Session, fields: dict[str, Any], threshold: int = 60, limit: int = 5) -> list[Candidate]:
    scores: dict[str, dict[str, Any]] = {}

    def add(person_id: str, reason: str) -> None:
        entry = scores.setdefault(person_id, {"score": 0, "reasons": []})
        if reason in entry["reasons"]:
            return
        entry["reasons"].append(reason)
        entry["score"] = max(entry["score"], WEIGHTS[reason])

    email = (fields.get("email") or "").strip().lower()
    mobile = normalize_phone(fields.get("mobile") or "")
    tel = normalize_phone(fields.get("tel") or "")
    name_norm = normalize_name(f"{fields.get('last_name', '')}{fields.get('first_name', '')}")
    kana_norm = normalize_name(f"{fields.get('last_name_kana', '')}{fields.get('first_name_kana', '')}")
    company_norm = normalize_company(fields.get("company_name") or "")

    def persons_by_contact(value: str, contact_types: tuple[str, ...]) -> list[str]:
        if not value:
            return []
        rows = (
            db.query(BusinessCard.person_id)
            .join(CardContact, CardContact.card_id == BusinessCard.card_id)
            .filter(
                CardContact.value_normalized == value,
                CardContact.contact_type.in_(contact_types),
                BusinessCard.deleted_at.is_(None),
            )
            .distinct()
            .all()
        )
        return [row[0] for row in rows]

    for person_id in persons_by_contact(email, ("email",)):
        add(person_id, "email")
    for person_id in persons_by_contact(mobile, ("mobile",)):
        add(person_id, "mobile")

    if name_norm:
        for person in (
            db.query(Person)
            .filter(Person.full_name_normalized == name_norm, Person.deleted_at.is_(None))
            .limit(50)
            .all()
        ):
            if company_norm and _company_matches(db, person.person_id, company_norm):
                add(person.person_id, "name_company")
            else:
                add(person.person_id, "name")

    if kana_norm and company_norm:
        for person in (
            db.query(Person)
            .filter(Person.deleted_at.is_(None))
            .filter(
                (Person.last_name_kana.isnot(None)) | (Person.first_name_kana.isnot(None))
            )
            .limit(200)
            .all()
        ):
            person_kana = normalize_name(f"{person.last_name_kana or ''}{person.first_name_kana or ''}")
            if person_kana and person_kana == kana_norm and _company_matches(db, person.person_id, company_norm):
                add(person.person_id, "kana_company")

    if tel and company_norm:
        for person_id in persons_by_contact(tel, ("tel", "mobile")):
            if _company_matches(db, person_id, company_norm):
                add(person_id, "tel_company")

    candidates: list[Candidate] = []
    for person_id, entry in scores.items():
        if entry["score"] < threshold:
            continue
        person = db.get(Person, person_id)
        if person is None or person.deleted_at is not None:
            continue
        candidates.append(
            Candidate(
                person_id=person_id,
                person_name=person.full_name,
                company_name=_person_company(db, person),
                score=entry["score"],
                reasons=[REASON_LABELS[r] for r in entry["reasons"]],
                latest_card_id=person.latest_card_id,
            )
        )
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit]


def _company_matches(db: Session, person_id: str, company_norm: str) -> bool:
    cards = (
        db.query(BusinessCard)
        .filter(BusinessCard.person_id == person_id, BusinessCard.deleted_at.is_(None))
        .all()
    )
    for card in cards:
        if normalize_company(card.company_display) == company_norm:
            return True
    return False

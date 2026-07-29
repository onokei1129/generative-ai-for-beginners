"""電話番号の正規形を国内表記に揃える

`card_contact.value_normalized` は照合と重複人物の判定に使う。以前は
`+81 90-1234-5678` を `+819012345678`、`090-1234-5678` を `09012345678` と
別の値にしていたため、同じ番号でも重複人物として気づけなかった。

正規形を国内表記（`09012345678`）に変えたので、既存の行を詰め替える。
表示用の `value_raw` は名刺の記載どおりのまま触らない。

Revision ID: a4f18b2c7e05
Revises: d72f96ac9ae1
Create Date: 2026-07-29

"""

from __future__ import annotations

import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4f18b2c7e05"
down_revision: Union[str, Sequence[str], None] = "d72f96ac9ae1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PHONE_TYPES = ("tel", "mobile", "fax")


def _to_domestic(raw: str) -> str:
    """services/ocr/parser.domestic_digits と同じ規則。

    マイグレーションはアプリのコードに依存させない（将来コードが変わっても、
    この版で行った変換が再現できるようにするため）。
    """
    text = (raw or "").strip()
    if text.startswith("+"):
        text = re.sub(r"\(\s*0\s*\)", "", text)
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") and digits.startswith("81"):
        return "0" + digits[2:]
    return digits


def _to_previous(raw: str) -> str:
    """変更前の正規形（数字と + だけを残したもの）。"""
    return re.sub(r"[^\d+]", "", (raw or "").strip())


def _rewrite(convert) -> None:
    connection = op.get_bind()
    contact = sa.table(
        "card_contact",
        sa.column("card_contact_id", sa.String),
        sa.column("contact_type", sa.String),
        sa.column("value_raw", sa.String),
        sa.column("value_normalized", sa.String),
    )
    rows = connection.execute(
        sa.select(contact.c.card_contact_id, contact.c.value_raw, contact.c.value_normalized).where(
            contact.c.contact_type.in_(PHONE_TYPES)
        )
    ).fetchall()

    for contact_id, value_raw, value_normalized in rows:
        wanted = convert(value_raw)
        if wanted == (value_normalized or ""):
            continue
        connection.execute(
            sa.update(contact)
            .where(contact.c.card_contact_id == contact_id)
            .values(value_normalized=wanted)
        )


def upgrade() -> None:
    _rewrite(_to_domestic)


def downgrade() -> None:
    _rewrite(_to_previous)

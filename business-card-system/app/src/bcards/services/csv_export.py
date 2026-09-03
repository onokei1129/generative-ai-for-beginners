"""CSV出力と監査記録（要件§9）。"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..models import BusinessCard, CsvExportLog, User
from ..settings_store import get_setting

# 出力可能な項目（要件§9「指定した項目のみ」）
COLUMNS: dict[str, str] = {
    "card_id": "名刺ID",
    "person_name": "氏名",
    "person_kana": "ふりがな",
    "company_name": "会社名",
    "department_name": "部署",
    "title": "役職",
    "postal_code": "郵便番号",
    "address": "住所",
    "tel": "電話",
    "mobile": "携帯",
    "fax": "FAX",
    "email": "メール",
    "url": "URL",
    "card_type": "名刺種別",
    "exchanged_on": "名刺交換日",
    "is_latest": "最新",
    "registered_by": "登録者",
    "created_at": "登録日時",
    "note": "備考",
}

DEFAULT_COLUMNS = [
    "person_name",
    "person_kana",
    "company_name",
    "department_name",
    "title",
    "postal_code",
    "address",
    "tel",
    "mobile",
    "fax",
    "email",
    "url",
    "exchanged_on",
    "created_at",
]

SCOPE_LABELS = {
    "search_result": "検索結果",
    "selected": "選択した名刺",
    "by_company": "指定した会社",
    "by_period": "指定した期間",
    "all": "全名刺",
}


def _value(card: BusinessCard, column: str, user_names: dict[str, str]) -> str:
    if column == "card_id":
        return card.card_id
    if column == "person_name":
        return card.person.full_name if card.person else ""
    if column == "person_kana":
        return card.person.full_name_kana if card.person else ""
    if column == "company_name":
        return card.company_display
    if column == "department_name":
        return card.department_name or ""
    if column == "title":
        return card.title or ""
    if column == "postal_code":
        return card.postal_code or ""
    if column == "address":
        return card.address or ""
    if column in ("tel", "mobile", "fax", "email", "url"):
        return ", ".join(card.contact_values(column))
    if column == "card_type":
        from ..models import CARD_TYPES

        return CARD_TYPES.get(card.card_type or "", card.card_type or "")
    if column == "exchanged_on":
        return card.exchanged_on.strftime("%Y-%m-%d") if card.exchanged_on else ""
    if column == "is_latest":
        return "最新" if card.is_latest else "過去"
    if column == "registered_by":
        return user_names.get(card.created_by or "", "")
    if column == "created_at":
        return card.created_at.strftime("%Y-%m-%d %H:%M")
    if column == "note":
        return card.note or ""
    return ""


def build_control_number(user: User) -> str:
    return f"BC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{user.user_id[:6].upper()}"


def build_csv(
    db: Session,
    cards: list[BusinessCard],
    columns: list[str],
    *,
    user: User,
    control_number: str,
    add_control_row: bool,
) -> str:
    from ..models import User as UserModel

    user_names = {u.user_id: u.display_name for u in db.query(UserModel).all()}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")

    # 見出しは必ず1行目に置く。
    # 管理情報を先頭に付けるとExcelの「テーブルとして書式設定」「オートフィルタ」
    # ピボットテーブルがいずれも1行目を見出しとみなすため、列がずれて使えなくなる。
    writer.writerow([COLUMNS[c] for c in columns])
    for card in cards:
        writer.writerow([_value(card, column, user_names) for column in columns])

    if add_control_row:
        # 要件§9「CSVファイル自体に付与することも検討する」
        # 空行を1行はさむ。Excelは連続した範囲（現在の領域）を表とみなすため、
        # 空行があれば管理情報が表に取り込まれず、並べ替えでも混ざらない。
        writer.writerow([])
        writer.writerow([f"# 出力者: {user.display_name}({user.login_id})"])
        writer.writerow([f"# 出力日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
        writer.writerow([f"# システム管理番号: {control_number}"])
        writer.writerow(["# 本ファイルは社内利用限定です。無断での再配布・社外持出しを禁止します。"])

    return buffer.getvalue()


def export(
    db: Session,
    request: Request,
    user: User,
    cards: list[BusinessCard],
    columns: list[str],
    *,
    scope: str,
    conditions: dict[str, Any],
    confirmed_large: bool,
) -> tuple[str, str, CsvExportLog]:
    """CSVを生成し、監査ログとCSV出力ログを記録する（要件§9）。"""
    columns = [c for c in columns if c in COLUMNS] or DEFAULT_COLUMNS
    control_number = build_control_number(user)
    # 管理番号をファイル名にも入れる。出回ったファイルから出力ログを引けるようにするため
    # （論点J）。管理番号自体に出力日時が入っている。
    file_name = f"business_cards_{control_number}.csv"
    add_control_row = bool(get_setting(db, "csv_add_control_row"))

    content = build_csv(
        db, cards, columns, user=user, control_number=control_number, add_control_row=add_control_row
    )

    audit = log_audit(
        db,
        request,
        user,
        "csv_export",
        target_type="business_card",
        result="success",
        detail={"scope": scope, "record_count": len(cards), "control_number": control_number},
    )
    export_log = CsvExportLog(
        audit_log_id=audit.audit_log_id,
        export_scope=scope,
        search_condition=conditions,
        exported_columns=columns,
        record_count=len(cards),
        file_name=file_name,
        control_number=control_number,
        confirmed_large_export=confirmed_large,
    )
    db.add(export_log)
    db.flush()
    return content, file_name, export_log

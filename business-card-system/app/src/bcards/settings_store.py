"""管理画面から変更できるシステム設定（AppSetting テーブル）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AppSetting

DEFAULTS: dict[str, Any] = {
    # 要件§6
    "admin_external_access_mode": "on_demand",  # always / on_demand / denied
    "session_idle_timeout_minutes": 60,
    "admin_external_idle_timeout_minutes": 15,
    # 要件§2
    "storage_alert_threshold_percent": 80,
    # 要件§9
    "csv_large_export_threshold": 500,
    "csv_add_control_row": True,
    # 要件§7（open-issues 論点A）
    "card_edit_policy": "all_users",  # all_users / owner_and_admin / request_approval
    "require_reason_on_edit": False,
    "require_reason_on_overwrite_delete": True,
    # 要件§10（open-issues 論点D）
    "duplicate_match_threshold": 60,
    # 要件§4（open-issues 論点G）
    "image_correction_enabled": True,
    # 要件§9（open-issues 論点H）ログ・履歴の保存期間
    "audit_log_retention_days": 1095,  # 監査ログの保持期間（3年）。0で無期限
    "audit_log_archive_after_days": 365,  # この日数を過ぎた監査ログをアーカイブへ移す。0で移さない
}

DESCRIPTIONS: dict[str, str] = {
    "admin_external_access_mode": "管理者の社外アクセス（always=常時許可 / on_demand=許可された利用者のみ / denied=禁止）",
    "session_idle_timeout_minutes": "無操作自動ログアウトまでの分数（一般）",
    "admin_external_idle_timeout_minutes": "管理者が社外からアクセスした場合の無操作ログアウト分数",
    "storage_alert_threshold_percent": "保存容量アラートの閾値（%）",
    "csv_large_export_threshold": "CSV大量出力の確認画面を表示する件数",
    "csv_add_control_row": "CSVに出力者・日時・管理番号・注意表示の行を付与する",
    "card_edit_policy": "名刺の編集権限（all_users / owner_and_admin / request_approval）",
    "require_reason_on_edit": "通常の項目修正でも変更理由の入力を必須にする",
    "require_reason_on_overwrite_delete": "上書き・削除時に変更理由の入力を必須にする",
    "duplicate_match_threshold": "重複人物候補として提示するスコアの閾値（0-100）",
    "image_correction_enabled": "アップロード画像の自動補正を行う",
    "audit_log_retention_days": "監査ログの保持期間（日）。この期間を過ぎたアーカイブを破棄する。0で無期限",
    "audit_log_archive_after_days": "監査ログをアーカイブへ移すまでの日数。0でDBに置いたままにする",
}


def get_setting(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    if row is None:
        return DEFAULTS.get(key)
    return row.setting_value.get("value", DEFAULTS.get(key))


def all_settings(db: Session) -> dict[str, Any]:
    values = dict(DEFAULTS)
    for row in db.query(AppSetting).all():
        values[row.setting_key] = row.setting_value.get("value")
    return values


def set_setting(db: Session, key: str, value: Any, user_id: str | None) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(setting_key=key, setting_value={"value": value}, updated_by=user_id)
        db.add(row)
    else:
        row.setting_value = {"value": value}
        row.updated_by = user_id

"""データモデル。

docs/data-model-v0.3.md のER設計に対応する。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(32))


# --------------------------------------------------------------------------
# 利用者・組織
# --------------------------------------------------------------------------

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_RETIRED = "retired"


class Department(Base, TimestampMixin):
    """部署・グループ。要件§1により初期リリースでは任意（未使用でよい）。"""

    __tablename__ = "department"

    department_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_department_id: Mapped[str | None] = mapped_column(ForeignKey("department.department_id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class User(Base, TimestampMixin):
    __tablename__ = "user"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    login_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_MEMBER, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE, nullable=False)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.department_id"))

    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    external_access_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime)

    department: Mapped[Department | None] = relationship()

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def can_login(self) -> bool:
        return self.status == STATUS_ACTIVE


class Device(Base):
    """アプリ側で発行する端末識別ID（要件§9）。"""

    __tablename__ = "device"

    device_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"))
    device_name: Mapped[str | None] = mapped_column(String(128))
    user_agent: Mapped[str | None] = mapped_column(Text)
    os_info: Mapped[str | None] = mapped_column(String(128))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User | None] = relationship()


class AllowedIp(Base, TimestampMixin):
    __tablename__ = "allowed_ip"

    allowed_ip_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    applies_to: Mapped[str] = mapped_column(String(16), default="all")  # all / member_only
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempt"

    login_attempt_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    login_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"))
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(32))
    user_agent: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# --------------------------------------------------------------------------
# 会社・人物・名刺
# --------------------------------------------------------------------------


class Company(Base, TimestampMixin):
    __tablename__ = "company"

    company_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    name_kana: Mapped[str | None] = mapped_column(String(256))
    name_normalized: Mapped[str] = mapped_column(String(256), index=True, nullable=False, default="")
    postal_code: Mapped[str | None] = mapped_column(String(16))
    address: Mapped[str | None] = mapped_column(String(512))
    tel: Mapped[str | None] = mapped_column(String(64))
    fax: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(String(256))
    merged_into_company_id: Mapped[str | None] = mapped_column(ForeignKey("company.company_id"))

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_by: Mapped[str | None] = mapped_column(String(32))
    delete_reason: Mapped[str | None] = mapped_column(Text)


class Person(Base, TimestampMixin):
    __tablename__ = "person"

    person_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    last_name: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(64))
    last_name_kana: Mapped[str | None] = mapped_column(String(64))
    first_name_kana: Mapped[str | None] = mapped_column(String(64))
    full_name_normalized: Mapped[str] = mapped_column(String(128), index=True, default="")
    latest_card_id: Mapped[str | None] = mapped_column(String(32))
    merged_into_person_id: Mapped[str | None] = mapped_column(ForeignKey("person.person_id"))
    note: Mapped[str | None] = mapped_column(Text)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_by: Mapped[str | None] = mapped_column(String(32))
    delete_reason: Mapped[str | None] = mapped_column(Text)

    cards: Mapped[list["BusinessCard"]] = relationship(
        back_populates="person", order_by="BusinessCard.created_at.desc()"
    )

    @property
    def full_name(self) -> str:
        return " ".join(x for x in (self.last_name, self.first_name) if x) or "（氏名不明）"

    @property
    def full_name_kana(self) -> str:
        return " ".join(x for x in (self.last_name_kana, self.first_name_kana) if x)


CARD_TYPES = {
    "head_office": "本社用",
    "branch": "支店用",
    "business_unit": "事業別",
    "other": "その他",
}

SOURCES = {
    "scan": "複合機スキャン",
    "mobile_photo": "スマートフォン撮影",
    "file_upload": "ファイルアップロード",
    "manual": "手入力",
}


class BusinessCard(Base, TimestampMixin):
    __tablename__ = "business_card"

    card_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    person_id: Mapped[str] = mapped_column(ForeignKey("person.person_id"), nullable=False, index=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("company.company_id"), index=True)
    company_name_raw: Mapped[str | None] = mapped_column(String(256))
    department_name: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(128))
    card_type: Mapped[str | None] = mapped_column(String(32))
    postal_code: Mapped[str | None] = mapped_column(String(16))
    address: Mapped[str | None] = mapped_column(String(512))
    note: Mapped[str | None] = mapped_column(Text)

    exchanged_on: Mapped[datetime | None] = mapped_column(DateTime)
    exchanged_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"))

    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    superseded_by_card_id: Mapped[str | None] = mapped_column(String(32))

    source: Mapped[str] = mapped_column(String(32), default="file_upload")
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    verified_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)

    status: Mapped[str] = mapped_column(String(16), default="active")  # draft/active/archived
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    deleted_by: Mapped[str | None] = mapped_column(String(32))
    delete_reason: Mapped[str | None] = mapped_column(Text)

    person: Mapped[Person] = relationship(back_populates="cards")
    company: Mapped[Company | None] = relationship()
    contacts: Mapped[list["CardContact"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    images: Mapped[list["CardImage"]] = relationship(back_populates="card")

    __table_args__ = (
        Index("ix_card_person_latest", "person_id", "is_latest"),
        Index("ix_card_exchanged_on", "exchanged_on"),
    )

    def contact_values(self, contact_type: str) -> list[str]:
        return [c.value_raw for c in self.contacts if c.contact_type == contact_type]

    @property
    def company_display(self) -> str:
        if self.company:
            return self.company.name
        return self.company_name_raw or ""


CONTACT_TYPES = {
    "tel": "電話",
    "mobile": "携帯",
    "fax": "FAX",
    "email": "メール",
    "url": "URL",
    "sns": "SNS",
}


class CardContact(Base):
    __tablename__ = "card_contact"

    card_contact_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("business_card.card_id", ondelete="CASCADE"), index=True)
    contact_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value_raw: Mapped[str] = mapped_column(String(256), nullable=False)
    value_normalized: Mapped[str] = mapped_column(String(256), index=True, default="")
    label: Mapped[str | None] = mapped_column(String(64))

    card: Mapped[BusinessCard] = relationship(back_populates="contacts")


class CardImage(Base):
    __tablename__ = "card_image"

    card_image_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("business_card.card_id"), index=True)
    import_item_id: Mapped[str | None] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8), default="front")  # front / back
    variant: Mapped[str] = mapped_column(String(16), default="display")  # original/display/thumbnail
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), default="image/jpeg")
    original_mime_type: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str | None] = mapped_column(String(128), index=True)
    correction_applied: Mapped[dict | None] = mapped_column(JSON)
    quality_warning: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    card: Mapped[BusinessCard | None] = relationship(back_populates="images")


# --------------------------------------------------------------------------
# 取込・OCR
# --------------------------------------------------------------------------

ITEM_QUEUED = "queued"
ITEM_OCR = "ocr_processing"
ITEM_REVIEW = "pending_review"
ITEM_REGISTERED = "registered"
ITEM_ERROR = "error"

ITEM_STATUS_LABELS = {
    ITEM_QUEUED: "取込待ち",
    ITEM_OCR: "OCR処理中",
    ITEM_REVIEW: "確認待ち",
    ITEM_REGISTERED: "登録完了",
    ITEM_ERROR: "エラー",
}

REGISTER_ACTIONS = {
    "new_person": "新しい人物として登録する",
    "add_to_person": "既存人物の追加名刺として登録する",
    "overwrite": "既存名刺を新しい内容で上書きする",
    "replace": "旧名刺を削除し、新しい名刺に置き換える",
    "keep_history": "旧名刺を履歴として残し、新しい名刺を最新として登録する",
    "cancel": "登録を中止する",
}


class ImportJob(Base):
    __tablename__ = "import_job"

    import_job_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_by: Mapped[str] = mapped_column(ForeignKey("user.user_id"), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    items: Mapped[list["ImportItem"]] = relationship(back_populates="job", order_by="ImportItem.created_at")
    files: Mapped[list["ImportFile"]] = relationship(back_populates="job", order_by="ImportFile.created_at")
    user: Mapped[User] = relationship()

    @property
    def is_finished(self) -> bool:
        return self.status in ("done", "partially_done", "failed")


FILE_QUEUED = "queued"
FILE_PROCESSING = "processing"
FILE_DONE = "done"
FILE_ERROR = "error"

FILE_STATUS_LABELS = {
    FILE_QUEUED: "取込待ち",
    FILE_PROCESSING: "処理中",
    FILE_DONE: "処理済み",
    FILE_ERROR: "エラー",
}


class ImportFile(Base):
    """アップロードされたファイル1件＝取込キューの1単位。

    アップロード時はここに積むだけで応答を返し、ワーカーが順次処理する。
    """

    __tablename__ = "import_file"

    import_file_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    import_job_id: Mapped[str] = mapped_column(ForeignKey("import_job.import_job_id"), index=True)
    source_file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(32), default="file_upload")
    status: Mapped[str] = mapped_column(String(16), default=FILE_QUEUED, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(64))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    job: Mapped["ImportJob"] = relationship(back_populates="files")

    @property
    def status_label(self) -> str:
        return FILE_STATUS_LABELS.get(self.status, self.status)


class ImportItem(Base):
    __tablename__ = "import_item"

    import_item_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    import_job_id: Mapped[str] = mapped_column(ForeignKey("import_job.import_job_id"), index=True)
    source_file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer)
    split_index: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default=ITEM_QUEUED, index=True)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("business_card.card_id"))
    duplicate_candidates: Mapped[list | None] = mapped_column(JSON)
    chosen_action: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    job: Mapped[ImportJob] = relationship(back_populates="items")
    ocr_results: Mapped[list["OcrResult"]] = relationship(back_populates="item")

    @property
    def status_label(self) -> str:
        return ITEM_STATUS_LABELS.get(self.status, self.status)


class OcrResult(Base):
    __tablename__ = "ocr_result"

    ocr_result_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    import_item_id: Mapped[str] = mapped_column(ForeignKey("import_item.import_item_id"), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    api_version: Mapped[str | None] = mapped_column(String(64))
    raw_response: Mapped[dict | None] = mapped_column(JSON)
    extracted_fields: Mapped[dict | None] = mapped_column(JSON)
    field_confidence: Mapped[dict | None] = mapped_column(JSON)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    item: Mapped[ImportItem] = relationship(back_populates="ocr_results")


# --------------------------------------------------------------------------
# 変更履歴・監査ログ
# --------------------------------------------------------------------------


class ChangeHistory(Base):
    __tablename__ = "change_history"

    change_history_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(32))
    changed_by_name: Mapped[str | None] = mapped_column(String(128))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    device_id: Mapped[str | None] = mapped_column(String(32))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    before_value: Mapped[dict | None] = mapped_column(JSON)
    after_value: Mapped[dict | None] = mapped_column(JSON)
    change_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_history_target", "target_type", "target_id", "changed_at"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    audit_log_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    user_display_name: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(16), default="success")
    error_message: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    device_id: Mapped[str | None] = mapped_column(String(32))
    user_agent: Mapped[str | None] = mapped_column(Text)
    os_info: Mapped[str | None] = mapped_column(String(128))
    detail: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class CsvExportLog(Base):
    __tablename__ = "csv_export_log"

    csv_export_log_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    audit_log_id: Mapped[str] = mapped_column(ForeignKey("audit_log.audit_log_id"), unique=True)
    export_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    search_condition: Mapped[dict | None] = mapped_column(JSON)
    exported_columns: Mapped[list | None] = mapped_column(JSON)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    control_number: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_large_export: Mapped[bool] = mapped_column(Boolean, default=False)

    audit_log: Mapped[AuditLog] = relationship()


# --------------------------------------------------------------------------
# 設定・通知
# --------------------------------------------------------------------------


class AppSetting(Base):
    __tablename__ = "app_setting"

    setting_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    setting_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(32))


class Notification(Base):
    __tablename__ = "notification"

    notification_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)

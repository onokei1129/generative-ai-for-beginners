"""起動時の設定チェック。

本番運用で危険な設定のまま起動してしまうことを防ぐ。
BCARDS_ENV=production のときは error を1件でも検出したら起動を中止する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import settings

logger = logging.getLogger("bcards.startup")

DEFAULT_SECRET_KEY = "dev-secret-key-change-me"


@dataclass
class Finding:
    level: str  # "error" / "warning"
    message: str


def check_configuration() -> list[Finding]:
    """設定を点検する。production では error があると起動しない。"""
    findings: list[Finding] = []
    production = settings.env == "production"

    if settings.secret_key == DEFAULT_SECRET_KEY:
        findings.append(
            Finding(
                "error" if production else "warning",
                "BCARDS_SECRET_KEY が既定値のままです。セッションを偽造される恐れがあります。",
            )
        )
    elif len(settings.secret_key) < 32:
        findings.append(Finding("warning", "BCARDS_SECRET_KEY が短すぎます。32文字以上を推奨します。"))

    if production and not settings.secure_cookie:
        findings.append(
            Finding("error", "本番では BCARDS_SECURE_COOKIE=1 にしてCookieをHTTPS限定にしてください。")
        )

    if production and not settings.enforce_ip_restriction:
        findings.append(
            Finding("error", "IP制限が無効です（要件§6）。BCARDS_ENFORCE_IP_RESTRICTION=1 にしてください。")
        )

    if production and settings.auto_create_tables:
        findings.append(
            Finding(
                "warning",
                "起動時の自動テーブル作成が有効です。本番では BCARDS_AUTO_CREATE_TABLES=0 とし、"
                "alembic upgrade head でスキーマを管理してください。",
            )
        )

    if production and settings.database_url.startswith("sqlite"):
        findings.append(
            Finding(
                "warning",
                "SQLite で起動しています。複数プロセス構成や本番運用では PostgreSQL 等を推奨します。",
            )
        )

    if production and settings.storage_backend == "local":
        findings.append(
            Finding(
                "warning",
                "画像をローカルディスクに保存しています。サーバーを増やす場合は "
                "BCARDS_STORAGE_BACKEND=s3 などの共有ストレージにしてください。",
            )
        )

    if (
        settings.ocr_provider == "tesseract"
        and settings.worker_concurrency > 1
        and settings.ocr_thread_limit <= 0
    ):
        findings.append(
            Finding(
                "warning",
                "tesseract のスレッド数が無制限のままワーカーを複数動かそうとしています。"
                "CPUの奪い合いで取込が滞留します。BCARDS_OCR_THREAD_LIMIT=1 を推奨します。",
            )
        )

    if settings.storage_backend == "s3" and not settings.s3_bucket:
        findings.append(Finding("error", "BCARDS_STORAGE_BACKEND=s3 ですが BCARDS_S3_BUCKET が未設定です。"))

    if settings.field_extractor == "llm":
        from .services.ocr.llm_extractor import LlmFieldExtractor

        if not LlmFieldExtractor.available():
            findings.append(
                Finding("error", "BCARDS_FIELD_EXTRACTOR=llm ですが Claude API の認証情報がありません。")
            )

    return findings


def verify_startup_configuration() -> list[Finding]:
    """点検結果をログに出し、本番で error があれば例外にする。"""
    findings = check_configuration()
    for finding in findings:
        log = logger.error if finding.level == "error" else logger.warning
        log("設定チェック: %s", finding.message)

    errors = [f for f in findings if f.level == "error"]
    if errors and settings.env == "production":
        raise RuntimeError(
            "本番設定に問題があるため起動を中止しました:\n" + "\n".join(f"- {f.message}" for f in errors)
        )
    return findings

"""アプリケーション設定。

環境変数で上書きできる値のみを扱う。運用中に管理者が変更する値
（無操作ログアウト時間、容量アラート閾値など）は AppSetting テーブル側で管理する。
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR.parent.parent


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool) -> bool:
    return _env(key, "1" if default else "0").lower() in ("1", "true", "yes", "on")


class Settings:
    # 実行環境（development / production）。production では起動時チェックを厳格にする
    env: str = _env("BCARDS_ENV", "development")

    # データベース
    database_url: str = _env("BCARDS_DATABASE_URL", f"sqlite:///{APP_DIR / 'storage' / 'bcards.db'}")
    # 本番では Alembic で管理するため 0 にする（起動時の自動テーブル作成を止める）
    auto_create_tables: bool = _env_bool("BCARDS_AUTO_CREATE_TABLES", True)
    db_pool_size: int = int(_env("BCARDS_DB_POOL_SIZE", "5"))
    db_max_overflow: int = int(_env("BCARDS_DB_MAX_OVERFLOW", "10"))

    # オブジェクトストレージ（local / s3。services/storage.py 参照）
    storage_backend: str = _env("BCARDS_STORAGE_BACKEND", "local")
    storage_dir: Path = Path(_env("BCARDS_STORAGE_DIR", str(APP_DIR / "storage" / "objects")))
    s3_bucket: str = _env("BCARDS_S3_BUCKET", "")
    s3_key_prefix: str = _env("BCARDS_S3_KEY_PREFIX", "business-cards")
    s3_region: str = _env("BCARDS_S3_REGION", "")
    s3_endpoint_url: str = _env("BCARDS_S3_ENDPOINT_URL", "")  # MinIO等のS3互換ストレージ用
    s3_sse: str = _env("BCARDS_S3_SSE", "AES256")  # 保存時暗号化。空文字で無効

    # セッション
    secret_key: str = _env("BCARDS_SECRET_KEY", "dev-secret-key-change-me")
    session_cookie: str = "bcards_session"
    device_cookie: str = "bcards_device"
    secure_cookie: bool = _env_bool("BCARDS_SECURE_COOKIE", False)

    # OCR プロバイダ: mock / tesseract / azure
    ocr_provider: str = _env("BCARDS_OCR_PROVIDER", "tesseract")
    ocr_languages: str = _env("BCARDS_OCR_LANGUAGES", "jpn+jpn_vert+eng")
    # tesseract が使うOpenMPスレッド数。ワーカーを複数動かす場合、既定のまま
    # （＝CPU数）にすると各プロセスがCPUを奪い合って極端に遅くなる（app/README.md 参照）。
    ocr_thread_limit: int = int(_env("BCARDS_OCR_THREAD_LIMIT", "1"))
    # 1回のOCR呼び出しの上限秒数。超えるとそのファイルはエラーにして次へ進む
    ocr_timeout_seconds: int = int(_env("BCARDS_OCR_TIMEOUT_SECONDS", "120"))

    # Azure AI Document Intelligence を使う場合のみ設定（services/ocr/providers.py）
    azure_di_endpoint: str = _env("BCARDS_AZURE_DI_ENDPOINT", "")
    azure_di_key: str = _env("BCARDS_AZURE_DI_KEY", "")

    # 項目分離の方式: rule（ルールベース）/ llm（Claude API）/ auto（LLMが使えれば使う）
    field_extractor: str = _env("BCARDS_FIELD_EXTRACTOR", "auto")
    llm_model: str = _env("BCARDS_LLM_MODEL", "claude-opus-5")
    llm_effort: str = _env("BCARDS_LLM_EFFORT", "low")

    # 取込ワーカー（キュー方式）
    worker_enabled: bool = _env_bool("BCARDS_WORKER_ENABLED", True)
    worker_concurrency: int = int(_env("BCARDS_WORKER_CONCURRENCY", "2"))
    worker_poll_seconds: float = float(_env("BCARDS_WORKER_POLL_SECONDS", "1.0"))
    worker_lease_seconds: int = int(_env("BCARDS_WORKER_LEASE_SECONDS", "600"))

    # 画像
    display_max_edge: int = int(_env("BCARDS_DISPLAY_MAX_EDGE", "1600"))
    thumbnail_max_edge: int = int(_env("BCARDS_THUMBNAIL_MAX_EDGE", "400"))
    min_card_width_px: int = int(_env("BCARDS_MIN_CARD_WIDTH_PX", "600"))
    blur_threshold: float = float(_env("BCARDS_BLUR_THRESHOLD", "80"))

    # 保存容量（アラート判定に使用。本番では契約容量を設定する）
    storage_quota_bytes: int = int(_env("BCARDS_STORAGE_QUOTA_BYTES", str(50 * 1024 ** 3)))

    # IP制限を強制するか（開発時は 0 にして無効化できる）
    enforce_ip_restriction: bool = _env_bool("BCARDS_ENFORCE_IP_RESTRICTION", True)

    # X-Forwarded-For を信用してよいプロキシのCIDR（カンマ区切り）。
    # 未設定の場合はヘッダを一切信用せず、TCP接続元のアドレスを使う。
    # ロードバランサやリバースプロキシの背後で動かす場合のみ設定する。
    trusted_proxy_cidrs: list[str] = [
        cidr.strip() for cidr in _env("BCARDS_TRUSTED_PROXIES", "").split(",") if cidr.strip()
    ]


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
(APP_DIR / "storage").mkdir(parents=True, exist_ok=True)

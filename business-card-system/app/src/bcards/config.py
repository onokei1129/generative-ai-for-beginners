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
    # データベース
    database_url: str = _env("BCARDS_DATABASE_URL", f"sqlite:///{APP_DIR / 'storage' / 'bcards.db'}")

    # オブジェクトストレージ相当（本番ではS3/Blob/GCSに置き換える。services/storage.py 参照）
    storage_dir: Path = Path(_env("BCARDS_STORAGE_DIR", str(APP_DIR / "storage" / "objects")))

    # セッション
    secret_key: str = _env("BCARDS_SECRET_KEY", "dev-secret-key-change-me")
    session_cookie: str = "bcards_session"
    device_cookie: str = "bcards_device"
    secure_cookie: bool = _env_bool("BCARDS_SECURE_COOKIE", False)

    # OCR プロバイダ: mock / tesseract / azure
    ocr_provider: str = _env("BCARDS_OCR_PROVIDER", "tesseract")
    ocr_languages: str = _env("BCARDS_OCR_LANGUAGES", "jpn+eng")

    # Azure AI Document Intelligence を使う場合のみ設定（services/ocr/azure_provider.py）
    azure_di_endpoint: str = _env("BCARDS_AZURE_DI_ENDPOINT", "")
    azure_di_key: str = _env("BCARDS_AZURE_DI_KEY", "")

    # 画像
    display_max_edge: int = int(_env("BCARDS_DISPLAY_MAX_EDGE", "1600"))
    thumbnail_max_edge: int = int(_env("BCARDS_THUMBNAIL_MAX_EDGE", "400"))
    min_card_width_px: int = int(_env("BCARDS_MIN_CARD_WIDTH_PX", "600"))
    blur_threshold: float = float(_env("BCARDS_BLUR_THRESHOLD", "80"))

    # 保存容量（アラート判定に使用。本番では契約容量を設定する）
    storage_quota_bytes: int = int(_env("BCARDS_STORAGE_QUOTA_BYTES", str(50 * 1024 ** 3)))

    # IP制限を強制するか（開発時は 0 にして無効化できる）
    enforce_ip_restriction: bool = _env_bool("BCARDS_ENFORCE_IP_RESTRICTION", True)


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
(APP_DIR / "storage").mkdir(parents=True, exist_ok=True)

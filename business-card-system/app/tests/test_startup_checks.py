"""起動時の設定チェック。危険な設定のまま本番起動しないことを確認する。"""

from __future__ import annotations

import pytest

from bcards.config import settings
from bcards.startup import DEFAULT_SECRET_KEY, check_configuration, verify_startup_configuration


@pytest.fixture
def production(monkeypatch):
    """本番相当の正しい設定を用意する。個々のテストで一部だけ壊す。"""
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "secret_key", "x" * 48)
    monkeypatch.setattr(settings, "secure_cookie", True)
    monkeypatch.setattr(settings, "enforce_ip_restriction", True)
    monkeypatch.setattr(settings, "auto_create_tables", False)
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u:p@db/bcards")
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "bcards")
    monkeypatch.setattr(settings, "field_extractor", "rule")
    return settings


def _messages(findings) -> str:
    return " / ".join(f.message for f in findings)


def test_correct_production_settings_pass(production):
    assert verify_startup_configuration() == []


def test_default_secret_key_blocks_production(production, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", DEFAULT_SECRET_KEY)
    with pytest.raises(RuntimeError) as excinfo:
        verify_startup_configuration()
    assert "BCARDS_SECRET_KEY" in str(excinfo.value)


def test_default_secret_key_is_only_a_warning_in_development(monkeypatch):
    monkeypatch.setattr(settings, "env", "development")
    monkeypatch.setattr(settings, "secret_key", DEFAULT_SECRET_KEY)
    findings = verify_startup_configuration()  # 開発では止めない
    assert any(f.level == "warning" and "BCARDS_SECRET_KEY" in f.message for f in findings)


def test_insecure_cookie_blocks_production(production, monkeypatch):
    monkeypatch.setattr(settings, "secure_cookie", False)
    with pytest.raises(RuntimeError):
        verify_startup_configuration()


def test_disabled_ip_restriction_blocks_production(production, monkeypatch):
    monkeypatch.setattr(settings, "enforce_ip_restriction", False)
    with pytest.raises(RuntimeError) as excinfo:
        verify_startup_configuration()
    assert "IP制限" in str(excinfo.value)


def test_s3_without_bucket_blocks_startup(production, monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", "")
    with pytest.raises(RuntimeError):
        verify_startup_configuration()


def test_sqlite_and_auto_create_are_warnings(production, monkeypatch):
    monkeypatch.setattr(settings, "database_url", "sqlite:///x.db")
    monkeypatch.setattr(settings, "auto_create_tables", True)
    monkeypatch.setattr(settings, "storage_backend", "local")
    findings = check_configuration()
    assert findings and all(f.level == "warning" for f in findings)
    assert "SQLite" in _messages(findings)
    assert "alembic" in _messages(findings)


def test_llm_without_credentials_blocks_startup(production, monkeypatch):
    monkeypatch.setattr(settings, "field_extractor", "llm")
    monkeypatch.setattr(
        "bcards.services.ocr.llm_extractor.LlmFieldExtractor.available", staticmethod(lambda: False)
    )
    with pytest.raises(RuntimeError):
        verify_startup_configuration()


def test_unbounded_tesseract_threads_warns_when_workers_are_parallel(production, monkeypatch):
    """OCRがCPUを奪い合って取込が滞留する設定を検出する（app/README.md 参照）。"""
    monkeypatch.setattr(settings, "ocr_provider", "tesseract")
    monkeypatch.setattr(settings, "worker_concurrency", 2)
    monkeypatch.setattr(settings, "ocr_thread_limit", 0)
    findings = check_configuration()
    assert "BCARDS_OCR_THREAD_LIMIT" in _messages(findings)
    assert all(f.level == "warning" for f in findings)

    monkeypatch.setattr(settings, "ocr_thread_limit", 1)
    assert check_configuration() == []


def test_the_combined_provider_gets_the_same_warning(production, monkeypatch):
    """併用構成は内側で tesseract を動かすため、同じ奪い合いが起きる。"""
    monkeypatch.setattr(settings, "ocr_provider", "combined")
    monkeypatch.setattr(settings, "worker_concurrency", 2)
    monkeypatch.setattr(settings, "ocr_thread_limit", 0)

    assert "BCARDS_OCR_THREAD_LIMIT" in _messages(check_configuration())

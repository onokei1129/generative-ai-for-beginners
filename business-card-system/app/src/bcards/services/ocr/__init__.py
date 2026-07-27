"""OCRサービスの選択（要件§8）。"""

from __future__ import annotations

from PIL import Image

from ...config import settings
from .base import OcrOutput, OcrProvider
from .parser import parse_fields
from .providers import AzureDocumentIntelligenceProvider, MockOcrProvider, TesseractOcrProvider

__all__ = ["OcrOutput", "OcrProvider", "get_provider", "recognize_card", "parse_fields"]

_PROVIDERS = {
    "mock": MockOcrProvider,
    "tesseract": TesseractOcrProvider,
    "azure": AzureDocumentIntelligenceProvider,
}


def get_provider(name: str | None = None) -> OcrProvider:
    key = (name or settings.ocr_provider or "mock").lower()
    factory = _PROVIDERS.get(key)
    if factory is None:
        raise ValueError(f"未知のOCRプロバイダです: {key}")
    try:
        return factory()
    except Exception:
        if key != "mock":
            # OCRサービスが利用できない場合でも取込フローは止めず、mock で代替する。
            # （実運用では管理者へ通知し、再処理で正しいプロバイダを使う）
            return MockOcrProvider()
        raise


def recognize_card(image: Image.Image, provider_name: str | None = None) -> tuple[OcrOutput, dict]:
    """OCRを実行し、項目分離まで行う。結果の確定は利用者の確認後（要件§8）。"""
    provider = get_provider(provider_name)
    output = provider.recognize(image)
    parsed = parse_fields(output.lines or output.text.splitlines())
    return output, parsed

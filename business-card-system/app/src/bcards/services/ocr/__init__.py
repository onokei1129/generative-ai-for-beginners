"""OCRサービスの選択（要件§8）。"""

from __future__ import annotations

from PIL import Image

from ...config import settings
from .base import OcrOutput, OcrProvider
from .llm_extractor import get_llm_extractor
from .parser import parse_fields
from .providers import (
    AzureDocumentIntelligenceProvider,
    EasyOcrProvider,
    MockOcrProvider,
    PaddleOcrProvider,
    TesseractOcrProvider,
)

__all__ = [
    "OcrOutput",
    "OcrProvider",
    "get_provider",
    "recognize_card",
    "parse_fields",
    "extract_fields",
]

_PROVIDERS = {
    "mock": MockOcrProvider,
    "tesseract": TesseractOcrProvider,
    "paddle": PaddleOcrProvider,
    "easyocr": EasyOcrProvider,
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


def extract_fields(image: Image.Image, output: OcrOutput, method: str | None = None) -> dict:
    """OCR結果を項目に分離する（論点C：方式1=ルール / 方式2=LLM）。

    method: rule / llm / auto（既定。LLMが使えればLLM、無ければルール）
    """
    method = (method or settings.field_extractor or "rule").lower()
    if method in ("llm", "auto"):
        extractor = get_llm_extractor()
        if extractor is not None:
            try:
                parsed = extractor.extract(image, output.text)
                parsed["method"] = "llm"
                return parsed
            except Exception as exc:
                if method == "llm":
                    raise
                # auto の場合はルールベースへフォールバックする
                parsed = parse_fields(output.lines or output.text.splitlines())
                parsed["method"] = "rule"
                parsed["fallback_reason"] = str(exc)
                return parsed
        if method == "llm":
            raise RuntimeError(
                "LLMによる項目分離が要求されましたが、Claude API の認証情報が設定されていません。"
            )
    parsed = parse_fields(output.lines or output.text.splitlines())
    parsed["method"] = "rule"
    return parsed


def recognize_card(image: Image.Image, provider_name: str | None = None) -> tuple[OcrOutput, dict]:
    """OCRを実行し、項目分離まで行う。結果の確定は利用者の確認後（要件§8）。"""
    provider = get_provider(provider_name)
    output = provider.recognize(image)
    parsed = extract_fields(image, output)
    return output, parsed

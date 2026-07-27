"""OCRプロバイダのインターフェース（要件§8）。

外部クラウドOCRへ送信するのは「OCR処理に必要な画像」のみ。
結果は自動確定せず、利用者が確認・修正してから登録する（要件§8）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from PIL import Image


@dataclass
class OcrOutput:
    provider: str
    api_version: str | None
    text: str
    lines: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None


class OcrProvider(Protocol):
    name: str

    def recognize(self, image: Image.Image) -> OcrOutput:  # pragma: no cover - Protocol
        ...

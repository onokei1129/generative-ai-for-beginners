"""LLMによる名刺項目の抽出（open-issues-v0.3.md 論点C「方式2」）。

汎用OCRのテキストと名刺画像をClaudeに渡し、構造化出力（JSON Schema）で
氏名・会社名・役職などの項目に分離する。ルールベース抽出（parser.py）と
同じ辞書構造を返すため、設定だけで差し替えられる。

認証情報が無い環境では利用できない。その場合は get_llm_extractor() が None を返し、
呼び出し側はルールベース抽出にフォールバックする。
"""

from __future__ import annotations

import io
import os
from typing import Any

from PIL import Image
from pydantic import BaseModel, Field

from ...config import settings

SYSTEM_PROMPT = """あなたは日本語の名刺をデータ化する専門家です。
名刺画像とOCRで読み取ったテキストの両方を見て、名刺に記載されている項目を正確に抜き出してください。

守ること:
- 名刺に書かれていない項目は空文字にする。推測で補わない。
- OCRテキストに誤認識があると判断できる場合は、画像を優先して読み取る。
- 氏名は姓と名に分ける。日本語名で区切りが不明な場合は、一般的な姓の長さで分ける。
- ふりがな（ひらがな・カタカナのみの行）は氏名とは別に扱う。
- 電話・FAX・携帯は、ラベル（TEL / FAX / Mobile など）と番号の対応を取り違えない。
- 郵便番号は 123-4567 の形式に整える。
- 縦書きの名刺は行の並びが崩れている場合があるため、画像のレイアウトを見て判断する。
- 会社名は法人格（株式会社など）を含めて記載どおりに書く。
- 部署と役職が同じ行にある場合は分離する。"""


class ExtractedCardFields(BaseModel):
    """名刺から抽出する項目。parser.parse_fields() と同じキー構成。"""

    last_name: str = Field(default="", description="姓。名刺に無ければ空文字")
    first_name: str = Field(default="", description="名。名刺に無ければ空文字")
    last_name_kana: str = Field(default="", description="姓のふりがな")
    first_name_kana: str = Field(default="", description="名のふりがな")
    company_name: str = Field(default="", description="会社名（法人格を含む記載どおりの表記）")
    department_name: str = Field(default="", description="部署・部門名")
    title: str = Field(default="", description="役職")
    postal_code: str = Field(default="", description="郵便番号（123-4567 形式）")
    address: str = Field(default="", description="住所（郵便番号を除く）")
    tel: str = Field(default="", description="固定電話番号")
    mobile: str = Field(default="", description="携帯電話番号")
    fax: str = Field(default="", description="FAX番号")
    email: str = Field(default="", description="メールアドレス")
    url: str = Field(default="", description="WebサイトのURL")
    note: str = Field(default="", description="上記に当てはまらない記載事項")


class LlmFieldExtractor:
    """Claude API を使った項目分離。"""

    name = "llm"

    def __init__(self, model: str | None = None, effort: str | None = None) -> None:
        import anthropic

        self.model = model or settings.llm_model
        # 抽出は単純なタスクのため既定は低いエフォート。精度が不足する場合は
        # BCARDS_LLM_EFFORT=medium / high に上げる。
        self.effort = effort or settings.llm_effort
        self.client = anthropic.Anthropic()

    @staticmethod
    def available() -> bool:
        """認証情報が設定されているか（SDKはプロファイルも参照する）。"""
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return True
        from pathlib import Path

        config_dir = Path(os.environ.get("ANTHROPIC_CONFIG_DIR", Path.home() / ".config" / "anthropic"))
        return (config_dir / "credentials").is_dir()

    def extract(self, image: Image.Image, ocr_text: str) -> dict[str, Any]:
        import base64

        buffer = io.BytesIO()
        # 送信するのはOCR処理に必要な画像のみ（要件§8）。長辺1600pxで十分。
        resized = image
        if max(image.width, image.height) > 1600:
            ratio = 1600 / max(image.width, image.height)
            resized = image.resize((int(image.width * ratio), int(image.height * ratio)), Image.LANCZOS)
        resized.convert("RGB").save(buffer, format="JPEG", quality=88)
        encoded = base64.standard_b64encode(buffer.getvalue()).decode("ascii")

        response = self.client.messages.parse(
            model=self.model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            output_config={"effort": self.effort},
            output_format=ExtractedCardFields,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded},
                        },
                        {
                            "type": "text",
                            "text": (
                                "この名刺の項目を抽出してください。\n\n"
                                "参考：OCRで読み取ったテキスト（誤認識を含む可能性があります）\n"
                                "----\n"
                                f"{ocr_text.strip() or '(テキストを取得できませんでした)'}\n"
                                "----"
                            ),
                        },
                    ],
                }
            ],
        )

        if response.stop_reason == "refusal":
            raise RuntimeError("LLMが応答を拒否しました。画像の内容を確認してください。")

        fields = response.parsed_output.model_dump()
        # 抽出できた項目数を簡易的な信頼度として扱う（確認画面の表示用）
        filled = sum(1 for key, value in fields.items() if key != "note" and value)
        confidence = {key: 0.9 for key, value in fields.items() if value}
        confidence["_overall"] = round(min(1.0, filled / 10), 3)
        return {"fields": fields, "confidence": confidence, "usage": _usage_of(response)}


def _usage_of(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }


def get_llm_extractor() -> LlmFieldExtractor | None:
    """利用可能なら抽出器を返す。認証情報や依存が無い場合は None。"""
    if not LlmFieldExtractor.available():
        return None
    try:
        return LlmFieldExtractor()
    except Exception:
        return None

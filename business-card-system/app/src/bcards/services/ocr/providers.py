"""OCRプロバイダの実装。

- mock      : 外部通信なしの擬似OCR（デモ・テスト用）
- tesseract : ローカルOCR。画像を外部へ送信しない
- azure     : Azure AI Document Intelligence（prebuilt-read）アダプタ

要件§8のとおり、いずれのプロバイダでも結果は自動確定せず確認画面を経由する。
"""

from __future__ import annotations

import hashlib
import io
import time
from typing import Any

from PIL import Image

from ...config import settings
from .base import OcrOutput


class MockOcrProvider:
    """外部通信を行わない擬似OCR。画像の内容ではなくハッシュから決定的に生成する。

    OCRサービス未契約の段階でも、取込〜確認〜登録の一連の流れを検証できるようにするためのもの。
    """

    name = "mock"

    _SAMPLES = [
        [
            "株式会社サンプル商事",
            "営業本部 第一営業部",
            "部長",
            "やまだ たろう",
            "山田 太郎",
            "〒100-0001 東京都千代田区千代田1-1-1",
            "TEL 03-1234-5678  FAX 03-1234-5679",
            "Mobile 090-1234-5678",
            "taro.yamada@example.co.jp",
            "https://www.example.co.jp",
        ],
        [
            "テクノロジー株式会社",
            "開発部",
            "シニアエンジニア",
            "さとう はなこ",
            "佐藤 花子",
            "〒530-0001 大阪府大阪市北区梅田2-2-2",
            "TEL 06-9876-5432",
            "hanako.sato@example.jp",
        ],
        [
            "合同会社みらいデザイン",
            "クリエイティブ室",
            "代表取締役",
            "鈴木 一郎",
            "〒460-0008 愛知県名古屋市中区栄3-3-3",
            "TEL 052-111-2222  FAX 052-111-2223",
            "ichiro@mirai-design.example",
        ],
    ]

    def recognize(self, image: Image.Image) -> OcrOutput:
        buffer = io.BytesIO()
        image.resize((64, 40)).save(buffer, format="PNG")
        digest = hashlib.sha256(buffer.getvalue()).hexdigest()
        lines = self._SAMPLES[int(digest[:8], 16) % len(self._SAMPLES)]
        return OcrOutput(
            provider=self.name,
            api_version="mock-1",
            text="\n".join(lines),
            lines=list(lines),
            raw={"note": "mock provider（外部送信なし）", "digest": digest[:16]},
            confidence=0.5,
        )


class TesseractOcrProvider:
    """ローカルの tesseract を使う。画像を外部サービスへ送信しない構成。"""

    name = "tesseract"

    def __init__(self, languages: str | None = None) -> None:
        self.languages = languages or settings.ocr_languages

    def recognize(self, image: Image.Image) -> OcrOutput:
        import pytesseract

        # 名刺はレイアウトが多様なため複数のページ分割モードを試し、最も情報量の多い結果を採用する
        best: dict[str, Any] | None = None
        for psm in (4, 6, 11):
            data = pytesseract.image_to_data(
                image,
                lang=self.languages,
                config=f"--psm {psm}",
                output_type=pytesseract.Output.DICT,
            )
            lines = self._to_lines(data)
            text = "\n".join(lines)
            score = len(text.replace(" ", ""))
            if best is None or score > best["score"]:
                best = {"lines": lines, "text": text, "score": score, "psm": psm, "data": data}

        assert best is not None
        confidences = [float(c) for c in best["data"]["conf"] if str(c) not in ("-1", "")]
        return OcrOutput(
            provider=self.name,
            api_version=str(pytesseract.get_tesseract_version()),
            text=best["text"],
            lines=best["lines"],
            raw={"psm": best["psm"], "languages": self.languages, "word_count": len(confidences)},
            confidence=round(sum(confidences) / len(confidences) / 100, 3) if confidences else None,
        )

    @staticmethod
    def _to_lines(data: dict[str, Any]) -> list[str]:
        buckets: dict[tuple[int, int, int], list[str]] = {}
        for index, word in enumerate(data["text"]):
            if not word.strip():
                continue
            try:
                conf = float(data["conf"][index])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 20:  # 日本語は信頼度が低めに出るため閾値を緩める
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            buckets.setdefault(key, []).append(word)
        return [" ".join(words).strip() for _, words in sorted(buckets.items()) if words]


class AzureDocumentIntelligenceProvider:
    """Azure AI Document Intelligence（prebuilt-read）アダプタ。

    注意：名刺専用の prebuilt-businessCard は v4.0 以降サポートされないため、
    汎用の読み取りモデル（prebuilt-read）でテキストを取得し、
    項目分離は parser.py 側で行う構成にしている（open-issues-v0.3.md 論点C）。

    本アダプタはエンドポイントとキーを設定した環境でのみ動作する。
    """

    name = "azure"
    api_version = "2024-11-30"

    def __init__(self, endpoint: str | None = None, key: str | None = None) -> None:
        self.endpoint = (endpoint or settings.azure_di_endpoint).rstrip("/")
        self.key = key or settings.azure_di_key
        if not self.endpoint or not self.key:
            raise RuntimeError(
                "Azure OCR を使うには BCARDS_AZURE_DI_ENDPOINT と BCARDS_AZURE_DI_KEY の設定が必要です。"
            )

    def recognize(self, image: Image.Image) -> OcrOutput:
        import httpx

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        url = (
            f"{self.endpoint}/documentintelligence/documentModels/prebuilt-read:analyze"
            f"?api-version={self.api_version}"
        )
        headers = {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "image/jpeg"}
        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, content=buffer.getvalue())
            response.raise_for_status()
            operation_url = response.headers.get("operation-location")
            if not operation_url:
                raise RuntimeError("Azure OCR: operation-location ヘッダが返却されませんでした。")
            for _ in range(30):
                time.sleep(1)
                poll = client.get(operation_url, headers={"Ocp-Apim-Subscription-Key": self.key})
                poll.raise_for_status()
                payload = poll.json()
                status = payload.get("status")
                if status == "succeeded":
                    break
                if status == "failed":
                    raise RuntimeError(f"Azure OCR に失敗しました: {payload}")
            else:
                raise RuntimeError("Azure OCR がタイムアウトしました。")

        analyze = payload.get("analyzeResult", {})
        lines: list[str] = []
        for page in analyze.get("pages", []):
            for line in page.get("lines", []):
                if line.get("content"):
                    lines.append(line["content"])
        return OcrOutput(
            provider=self.name,
            api_version=self.api_version,
            text="\n".join(lines),
            lines=lines,
            raw={"modelId": analyze.get("modelId"), "pages": len(analyze.get("pages", []))},
            confidence=None,
        )

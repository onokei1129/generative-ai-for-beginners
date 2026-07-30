"""OCRプロバイダの実装。

- mock      : 外部通信なしの擬似OCR（デモ・テスト用）
- tesseract : ローカルOCR。画像を外部へ送信しない
- paddle    : ローカルOCR（PaddleOCR）。同上。追加インストールが必要
- easyocr   : ローカルOCR（EasyOCR）。同上。追加インストールが必要
- azure     : Azure AI Document Intelligence（prebuilt-read）アダプタ

要件§8のとおり、いずれのプロバイダでも結果は自動確定せず確認画面を経由する。

PaddleOCR と EasyOCR は依存が大きい（それぞれ1〜3GB）ため、
`requirements.txt` には入れず任意インストールとする（app/README.md）。
読み込みは実際に使うときだけ行い、入っていなければ分かる例外を出す。
"""

from __future__ import annotations

import hashlib
import io
import os
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


def _limit_tesseract_threads() -> None:
    """tesseract 子プロセスのOpenMPスレッド数を制限する。

    tesseract は既定でCPU数ぶんのスレッドを使う。ワーカーを2並列で動かすと
    4コアのサーバーでも 2×CPU数 のスレッドが同時に走り、コンテキストスイッチで
    かえって遅くなる（実測: 1枚あたり 2.9秒 → 100秒超で滞留）。
    pytesseract は子プロセスに os.environ をそのまま渡すため、ここで設定する。
    """
    limit = settings.ocr_thread_limit
    if limit > 0:
        os.environ["OMP_THREAD_LIMIT"] = str(limit)


class TesseractOcrProvider:
    """ローカルの tesseract を使う。画像を外部サービスへ送信しない構成。"""

    name = "tesseract"

    def __init__(self, languages: str | None = None) -> None:
        self.languages = languages or settings.ocr_languages
        _limit_tesseract_threads()

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
                timeout=settings.ocr_timeout_seconds,
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


def group_boxes_into_lines(boxes: list[tuple[float, float, float, str]]) -> list[str]:
    """文字領域を行にまとめる（PaddleOCR・EasyOCR 共通）。

    どちらも「領域ごとの文字列」を返すため、そのまま並べると1行の中の語が
    別々の行になる。項目分離は行を単位に判定しているので（`TEL 03-…` の
    ラベルと番号の関係など）、y座標の近いものを同じ行に寄せてから
    左から右へ並べる。

    寄せる幅は**その領域の文字の高さ**で決める。名刺全体の間隔の中央値で
    決めていたときは、行間の狭い名刺で別の行まで巻き込んでいた。実測では
    郵便番号の行と役職の行が1行になり、郵便番号を抜いた残り（`代表社員`）が
    住所として登録されていた（16枚中3枚）。

    boxes: (中心y, 左端x, 高さ, 文字列)
    """
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda box: (box[0], box[1]))
    lines: list[list[tuple[float, float, float, str]]] = [[ordered[0]]]
    for box in ordered[1:]:
        previous = lines[-1][-1]
        # 高さの小さいほうを基準にする（大小が混ざる行で寄せすぎないため）
        tolerance = min(box[2], previous[2]) * 0.5 or 1.0
        if abs(box[0] - previous[0]) <= tolerance:
            lines[-1].append(box)
        else:
            lines.append([box])
    result = []
    for line in lines:
        text = " ".join(item[3] for item in sorted(line, key=lambda item: item[1])).strip()
        if text:
            result.append(text)
    return result


class PaddleOcrProvider:
    """PaddleOCR（ローカル）。画像を外部サービスへ送信しない構成。

    tesseract との比較用（論点C）。傾き・レイアウト検出を内蔵するため、
    縦書きや装飾の多い名刺で差が出るかを見る。

    初回実行時にモデルの重みを取得するため、外部への通信が必要
    （HuggingFace / ModelScope / BOS のいずれか）。取得後はオフラインで動く。
    """

    name = "paddle"
    _engine: Any = None

    def __init__(self, language: str | None = None) -> None:
        self.language = language or settings.ocr_paddle_language
        self._ensure_engine()

    def _ensure_engine(self) -> None:
        if PaddleOcrProvider._engine is not None:
            return
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:  # pragma: no cover - 任意インストール
            raise RuntimeError(
                "PaddleOCR が入っていません。"
                "pip install -r requirements-paddle.txt を実行してください。"
            ) from exc
        # 起動が数秒かかるためプロセス内で1つだけ持つ
        PaddleOcrProvider._engine = PaddleOCR(
            lang=self.language,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )

    def recognize(self, image: Image.Image) -> OcrOutput:
        import numpy

        array = numpy.asarray(image.convert("RGB"))
        results = PaddleOcrProvider._engine.predict(array)

        boxes: list[tuple[float, float, float, str]] = []
        scores: list[float] = []
        for page in results or []:
            texts = page.get("rec_texts") or []
            confidences = page.get("rec_scores") or []
            polygons = page.get("rec_polys") or page.get("dt_polys") or []
            for index, text in enumerate(texts):
                if not str(text).strip():
                    continue
                if index < len(polygons):
                    points = polygons[index]
                    ys = [float(point[1]) for point in points]
                    xs = [float(point[0]) for point in points]
                    boxes.append((sum(ys) / len(ys), min(xs), max(ys) - min(ys), str(text)))
                else:
                    # 座標が無い場合は順番だけを頼りに1行ずつ扱う
                    boxes.append((float(index), 0.0, 0.0, str(text)))
                if index < len(confidences):
                    scores.append(float(confidences[index]))

        lines = group_boxes_into_lines(boxes)
        return OcrOutput(
            provider=self.name,
            api_version=_installed_version("paddleocr"),
            text="\n".join(lines),
            lines=lines,
            raw={"language": self.language, "box_count": len(boxes)},
            confidence=round(sum(scores) / len(scores), 3) if scores else None,
        )


class EasyOcrProvider:
    """EasyOCR（ローカル）。画像を外部サービスへ送信しない構成。

    tesseract との比較用（論点C）。初回実行時にモデルの重みを取得する。
    """

    name = "easyocr"
    _engine: Any = None

    def __init__(self, languages: str | None = None) -> None:
        self.languages = languages or settings.ocr_easyocr_languages
        self._ensure_engine()

    def _ensure_engine(self) -> None:
        if EasyOcrProvider._engine is not None:
            return
        try:
            import easyocr
        except ImportError as exc:  # pragma: no cover - 任意インストール
            raise RuntimeError(
                "EasyOCR が入っていません。"
                "pip install -r requirements-easyocr.txt を実行してください。"
            ) from exc
        EasyOcrProvider._engine = easyocr.Reader(
            [lang.strip() for lang in self.languages.split(",") if lang.strip()],
            gpu=False,
            verbose=False,
        )

    def recognize(self, image: Image.Image) -> OcrOutput:
        import numpy

        array = numpy.asarray(image.convert("RGB"))
        results = EasyOcrProvider._engine.readtext(array)

        boxes: list[tuple[float, float, float, str]] = []
        scores: list[float] = []
        for points, text, score in results:
            if not str(text).strip():
                continue
            ys = [float(point[1]) for point in points]
            xs = [float(point[0]) for point in points]
            boxes.append((sum(ys) / len(ys), min(xs), max(ys) - min(ys), str(text)))
            scores.append(float(score))

        lines = group_boxes_into_lines(boxes)
        return OcrOutput(
            provider=self.name,
            api_version=_installed_version("easyocr"),
            text="\n".join(lines),
            lines=lines,
            raw={"languages": self.languages, "box_count": len(boxes)},
            confidence=round(sum(scores) / len(scores), 3) if scores else None,
        )


def _installed_version(package: str) -> str | None:
    from importlib import metadata

    try:
        return metadata.version(package)
    except Exception:  # pragma: no cover - 版が取れないだけなので無視する
        return None


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

"""OCRサービスの選択（要件§8）。"""

from __future__ import annotations

import re

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
    "COMBINED",
    "COMBINED_ENGINES",
    "merge_fields",
]

_PROVIDERS = {
    "mock": MockOcrProvider,
    "tesseract": TesseractOcrProvider,
    "paddle": PaddleOcrProvider,
    "easyocr": EasyOcrProvider,
    "azure": AzureDocumentIntelligenceProvider,
}

# 2つの読み取りエンジンを両方かけて、項目ごとに取れたほうを採る構成。
#
# 論点Cの計測（ocr-decision-2026-08.md）で、両者の弱点が重ならないことが
# 分かった。EasyOCR は日本語の字を続けて読めるが英数字の記号を落とし
# （`foods.example` が `foodsexample`、`//` が `Il`）、tesseract は逆に
# 英数字は取れるが日本語を1字ずつ切って空白を挟む。
#
# 先に挙げたエンジンの値を優先し、空のときだけ次のエンジンの値を使う。
# 項目ごとに担当を決める案も測ったが、単純な優先順のほうが良かった。
COMBINED = "combined"
COMBINED_ENGINES = ("easyocr", "tesseract")


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


# 形が決まっている項目だけ、採る前に形を確かめる。
#
# EasyOCR は英数字の記号を落とすため、空ではなく「もっともらしい誤り」を
# 返すことがある（`taro@example.co.jp` → `taro@exampleco.jp`）。空欄なら
# 人が気づくが、それらしい誤りは気づかずに登録されるため、形が違うものは
# 次のエンジンへ譲る。
#
# 合成サンプル20枚では、この検査の有無で正答率は変わらなかった（どちらも
# 76.8%）。防いでいるのは点数ではなく、見逃される誤りのほう。
_SHAPES = {
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"),
    "url": re.compile(r"^(?:https?://)?[^\s/]+\.[A-Za-z]{2,}"),
}


def _has_expected_shape(key: str, value: str) -> bool:
    shape = _SHAPES.get(key)
    return True if shape is None else bool(shape.match(value.strip()))


# 1行を分けて作る項目。別々のエンジンから寄せ集めると、1人の名前にならない。
#
# 実データ 13枚目では、EasyOCR が飾りを `町こ` と読んで姓に入れ、名は空、
# tesseract は `HIDEYA KOBAYASHI` を正しく読んでいた。項目ごとに採ると
# 姓『町こ』／ 名『HIDEYA』という別人ができあがる。
#
# まとめて片方から採る。どちらを採るかは埋まった数の多いほうで決める
# （姓も名も読めているエンジンのほうが確からしい）。同数なら先のエンジン。
_GROUPS = (
    ("last_name", "first_name"),
    ("last_name_kana", "first_name_kana"),
)


def _merge_groups(results: list[dict], fields: dict, confidence: dict) -> None:
    for group in _GROUPS:
        best: dict | None = None
        best_filled = -1
        for parsed in results:
            values = parsed.get("fields") or {}
            filled = sum(1 for key in group if (values.get(key) or "").strip())
            if filled > best_filled:
                best, best_filled = parsed, filled
        if best is None:
            continue
        values = best.get("fields") or {}
        scores = best.get("confidence") or {}
        for key in group:
            fields[key] = values.get(key, "")
            if scores.get(key) is not None:
                confidence[key] = scores[key]


def merge_fields(results: list[dict]) -> dict:
    """先に挙げた結果の値を優先し、空のときだけ次の結果の値を使う。

    形が決まっている項目で先の値が形を満たさない場合は、次の結果へ譲る。
    どこにも形を満たすものが無ければ、最初に見つけた値を残す（人が直せる
    ように、空にはしない）。確信度は採用した値のものを持ち回る。
    """
    fields: dict = {}
    confidence: dict = {}
    # 形を満たさないまま拾った値。形を満たすものが後から出れば置き換える。
    provisional: set[str] = set()

    for parsed in results:
        values = parsed.get("fields") or {}
        scores = parsed.get("confidence") or {}
        for key, value in values.items():
            if fields.get(key) and key not in provisional:
                continue
            if not value:
                fields.setdefault(key, value)
                continue
            good = _has_expected_shape(key, value)
            if fields.get(key) and not good:
                continue
            fields[key] = value
            if scores.get(key) is not None:
                confidence[key] = scores[key]
            elif key in confidence:
                del confidence[key]
            provisional.discard(key) if good else provisional.add(key)

    _merge_groups(results, fields, confidence)
    return {"fields": fields, "confidence": confidence, "method": "rule"}


def _recognize_combined(image: Image.Image) -> tuple[OcrOutput, dict]:
    """2つのエンジンを両方かけて併合する。

    片方が使えなければ、動いたほうだけで続ける。両方だめなら例外を出す
    （ここで mock に落とすと、擬似OCRの値を読み取り結果として保存してしまう）。
    """
    outputs: list[OcrOutput] = []
    parsed_list: list[dict] = []
    failures: list[str] = []
    for name in COMBINED_ENGINES:
        try:
            output = _PROVIDERS[name]().recognize(image)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue
        outputs.append(output)
        parsed_list.append(parse_fields(output.lines or output.text.splitlines()))

    if not outputs:
        raise RuntimeError("読み取りエンジンがどれも使えませんでした（" + " / ".join(failures) + "）")

    merged = OcrOutput(
        provider=COMBINED,
        api_version="+".join(filter(None, (o.api_version for o in outputs))) or None,
        # 確認画面の「OCRが読んだ文字を見る」に両方を出す。どちらが読めたのかを
        # 見分けられないと、報告を受けても原因を切り分けられない。
        text="\n".join(f"--- {o.provider} ---\n{o.text}" for o in outputs),
        lines=[line for o in outputs for line in (o.lines or [])],
        raw={"engines": [o.provider for o in outputs], "failures": failures},
        confidence=next((o.confidence for o in outputs if o.confidence is not None), None),
    )
    return merged, merge_fields(parsed_list)


def recognize_card(image: Image.Image, provider_name: str | None = None) -> tuple[OcrOutput, dict]:
    """OCRを実行し、項目分離まで行う。結果の確定は利用者の確認後（要件§8）。"""
    if (provider_name or settings.ocr_provider or "mock").lower() == COMBINED:
        return _recognize_combined(image)
    provider = get_provider(provider_name)
    output = provider.recognize(image)
    parsed = extract_fields(image, output)
    return output, parsed

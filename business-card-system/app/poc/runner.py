"""OCR精度PoCの実行と計測（open-issues-v0.3.md 論点C）。

    PYTHONPATH=src ./.venv/bin/python -m poc.runner --out ../ocr-poc-report.md

計測するもの（論点Cのとおり）:
  - 項目別の正答率
  - 1枚あたりの処理時間
  - 1枚あたりの費用（LLM利用時のトークン数から算出）
  - 確認画面での修正操作回数（=誤り項目数の平均）

比較する構成:
  A 前処理なし + tesseract + ルールベース抽出
  B 改善前の前処理（表示用の強い補正をOCRにも適用）+ ルールベース抽出
  C 改善後の前処理（切り出し＋傾き補正のみ）+ ルールベース抽出
  D 改善後 + 縦書き言語データ併用 + ルールベース抽出（現行実装）
  E 改善後 + LLM抽出（Claude API。認証情報がある場合のみ）
  F 改善後 + PaddleOCR（読み取りエンジンの差し替え）
  G 改善後 + EasyOCR（読み取りエンジンの差し替え）
  H 改善後 + EasyOCR と tesseract の併用（項目ごとに取れたほうを採る）
"""

from __future__ import annotations

import argparse
import io
import json
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from bcards.services import images as image_service  # noqa: E402
from bcards.services.ocr import parse_fields  # noqa: E402
from bcards.services.ocr.base import OcrOutput  # noqa: E402
from bcards.services.ocr.llm_extractor import get_llm_extractor  # noqa: E402
from bcards.services.ocr.providers import TesseractOcrProvider  # noqa: E402
from poc.samples import FIELD_KEYS, Sample, build_samples, load_real_samples  # noqa: E402

# 1Mトークンあたりの単価（claude-opus-5）。モデルを変える場合はここも変える。
LLM_INPUT_USD_PER_MTOK = 5.0
LLM_OUTPUT_USD_PER_MTOK = 25.0


# --------------------------------------------------------------------------
# 正規化と一致判定
# --------------------------------------------------------------------------

_PHONE_FIELDS = {"tel", "mobile", "fax"}
_CASE_FIELDS = {"email", "url"}


def normalize_value(key: str, value: str) -> str:
    text = unicodedata.normalize("NFKC", (value or "").strip())
    if key in _PHONE_FIELDS:
        return re.sub(r"\D", "", text)
    if key in _CASE_FIELDS:
        return re.sub(r"\s+", "", text).lower().rstrip("/")
    if key == "postal_code":
        return re.sub(r"\D", "", text)
    return re.sub(r"[\s　]+", "", text)


def matches(key: str, predicted: str, truth: str) -> bool:
    return normalize_value(key, predicted) == normalize_value(key, truth)


# --------------------------------------------------------------------------
# パイプライン
# --------------------------------------------------------------------------


@dataclass
class PipelineResult:
    fields: dict[str, str]
    seconds: float
    usage: dict[str, int] = field(default_factory=dict)
    ocr_text: str = ""


def _to_jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def preprocess_raw(image: Image.Image) -> Image.Image:
    """前処理なし（ページ画像そのまま）。"""
    return image_service.load_pages(_to_jpeg(image), "sample.jpg")[0].image


def preprocess_legacy(image: Image.Image) -> Image.Image:
    """改善前の前処理：表示用と同じ強い補正をOCRにも掛けていた状態を再現する。"""
    page = preprocess_raw(image)
    quads = image_service.detect_card_quads(page)
    card = image_service.warp_quad(page, quads[0]) if quads else page
    card, _ = image_service.orient_landscape(card)
    card, _ = image_service.deskew(card, min_angle=0.3)
    card, _ = image_service.enhance(card)
    return card


def preprocess_current(image: Image.Image) -> Image.Image:
    """改善後：アプリが実際にOCRへ渡す画像（切り出し＋傾き補正のみ）。"""
    cards = image_service.process_file(_to_jpeg(image), "sample.jpg", correct=True)
    return cards[0].ocr_image if cards else image


PREPROCESSORS: dict[str, Callable[[Image.Image], Image.Image]] = {
    "raw": preprocess_raw,
    "legacy": preprocess_legacy,
    "current": preprocess_current,
}


class RulePipeline:
    """tesseract + ルールベース抽出。"""

    def __init__(self, label: str, *, preprocessor: str, languages: str | None = None) -> None:
        self.label = label
        self.preprocessor = PREPROCESSORS[preprocessor]
        self.provider = TesseractOcrProvider(languages)

    def run(self, sample: Sample) -> PipelineResult:
        started = time.perf_counter()
        prepared = self.preprocessor(sample.image)
        output = self.provider.recognize(prepared)
        parsed = parse_fields(output.lines or output.text.splitlines())
        elapsed = time.perf_counter() - started
        return PipelineResult(fields=parsed["fields"], seconds=elapsed, ocr_text=output.text)


class EnginePipeline:
    """tesseract 以外のローカルOCR（PaddleOCR / EasyOCR）＋ルールベース抽出。

    比較の条件を揃えるため、前処理と項目分離は構成Dと同じにして、
    **読み取りエンジンだけ**を差し替える（論点C）。

    プロバイダは `get_provider()` を使わずに直接作る。あちらは利用できない
    ときに mock で代替する作りで、それでは擬似OCRの数字を「PaddleOCRの精度」
    として報告してしまう。ここでは作れなければ例外にして未計測と記録する。
    """

    def __init__(self, label: str, provider_name: str) -> None:
        self.label = label
        self.provider_name = provider_name
        self.provider: Any = None

    def _ensure_provider(self) -> Any:
        if self.provider is None:
            from bcards.services.ocr.providers import EasyOcrProvider, PaddleOcrProvider

            factories = {"paddle": PaddleOcrProvider, "easyocr": EasyOcrProvider}
            self.provider = factories[self.provider_name]()
        return self.provider

    def run(self, sample: Sample) -> PipelineResult:
        provider = self._ensure_provider()
        started = time.perf_counter()
        prepared = preprocess_current(sample.image)
        output = provider.recognize(prepared)
        parsed = parse_fields(output.lines or output.text.splitlines())
        elapsed = time.perf_counter() - started
        return PipelineResult(fields=parsed["fields"], seconds=elapsed, ocr_text=output.text)


class CombinedEnginePipeline:
    """複数の読み取りエンジンを両方かけ、項目ごとに取れたほうを採る。

    構成DとGの比較で、両者の弱点が重ならないことが分かったため測る。
    前処理と項目分離は構成Dと揃える（差は読み取りエンジンだけ）。
    """

    def __init__(self, label: str, engines: tuple[str, ...]) -> None:
        self.label = label
        self.engines = engines
        self.providers: list[Any] = []

    def _ensure_providers(self) -> list[Any]:
        if not self.providers:
            from bcards.services.ocr.providers import EasyOcrProvider, PaddleOcrProvider

            factories: dict[str, Any] = {
                "paddle": PaddleOcrProvider,
                "easyocr": EasyOcrProvider,
                "tesseract": lambda: TesseractOcrProvider("jpn+jpn_vert+eng"),
            }
            self.providers = [factories[name]() for name in self.engines]
        return self.providers

    def run(self, sample: Sample) -> PipelineResult:
        from bcards.services.ocr import merge_fields

        providers = self._ensure_providers()
        started = time.perf_counter()
        prepared = preprocess_current(sample.image)
        outputs = [provider.recognize(prepared) for provider in providers]
        merged = merge_fields([parse_fields(o.lines or o.text.splitlines()) for o in outputs])
        elapsed = time.perf_counter() - started
        return PipelineResult(
            fields=merged["fields"],
            seconds=elapsed,
            ocr_text="\n".join(f"--- {o.provider} ---\n{o.text}" for o in outputs),
        )


class LlmPipeline:
    """tesseract + LLMによる項目分離。"""

    def __init__(self, label: str, model: str | None = None, effort: str | None = None) -> None:
        self.label = label
        self.provider = TesseractOcrProvider()
        self.extractor = get_llm_extractor()
        if self.extractor is not None:
            if model:
                self.extractor.model = model
            if effort:
                self.extractor.effort = effort

    def run(self, sample: Sample) -> PipelineResult:
        if self.extractor is None:
            raise RuntimeError("Claude API の認証情報が設定されていません。")
        started = time.perf_counter()
        prepared = preprocess_current(sample.image)
        output: OcrOutput = self.provider.recognize(prepared)
        parsed = self.extractor.extract(prepared, output.text)
        elapsed = time.perf_counter() - started
        return PipelineResult(
            fields=parsed["fields"], seconds=elapsed, usage=parsed.get("usage", {}), ocr_text=output.text
        )


# --------------------------------------------------------------------------
# 集計
# --------------------------------------------------------------------------


@dataclass
class Aggregate:
    label: str
    per_field_correct: dict[str, int] = field(default_factory=dict)
    per_field_total: dict[str, int] = field(default_factory=dict)
    false_positives: dict[str, int] = field(default_factory=dict)
    edits_per_card: list[int] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)
    per_variant_edits: dict[str, list[int]] = field(default_factory=dict)
    usage_input: int = 0
    usage_output: int = 0
    errors: list[str] = field(default_factory=list)
    cards: int = 0

    def add(self, sample: Sample, result: PipelineResult) -> None:
        self.cards += 1
        self.seconds.append(result.seconds)
        self.usage_input += result.usage.get("input_tokens", 0)
        self.usage_output += result.usage.get("output_tokens", 0)

        edits = 0
        for key in FIELD_KEYS:
            truth = sample.truth.get(key, "")
            predicted = result.fields.get(key, "") or ""
            if truth:
                self.per_field_total[key] = self.per_field_total.get(key, 0) + 1
                if matches(key, predicted, truth):
                    self.per_field_correct[key] = self.per_field_correct.get(key, 0) + 1
                else:
                    edits += 1
            else:
                if normalize_value(key, predicted):
                    self.false_positives[key] = self.false_positives.get(key, 0) + 1
                    edits += 1
        self.edits_per_card.append(edits)
        self.per_variant_edits.setdefault(sample.variant, []).append(edits)

    def field_accuracy(self, key: str) -> float | None:
        total = self.per_field_total.get(key, 0)
        if not total:
            return None
        return self.per_field_correct.get(key, 0) / total

    @property
    def overall_accuracy(self) -> float:
        total = sum(self.per_field_total.values())
        return (sum(self.per_field_correct.values()) / total) if total else 0.0

    @property
    def mean_edits(self) -> float:
        return statistics.mean(self.edits_per_card) if self.edits_per_card else 0.0

    @property
    def mean_seconds(self) -> float:
        return statistics.mean(self.seconds) if self.seconds else 0.0

    @property
    def cost_per_card_usd(self) -> float:
        if not self.cards or not (self.usage_input or self.usage_output):
            return 0.0
        cost = (
            self.usage_input / 1_000_000 * LLM_INPUT_USD_PER_MTOK
            + self.usage_output / 1_000_000 * LLM_OUTPUT_USD_PER_MTOK
        )
        return cost / self.cards


FIELD_LABELS = {
    "last_name": "姓",
    "first_name": "名",
    "last_name_kana": "せい",
    "first_name_kana": "めい",
    "company_name": "会社名",
    "department_name": "部署",
    "title": "役職",
    "postal_code": "郵便番号",
    "address": "住所",
    "tel": "電話",
    "mobile": "携帯",
    "fax": "FAX",
    "email": "メール",
    "url": "URL",
}


def build_report(aggregates: list[Aggregate], sample_count: int, note: str) -> str:
    lines: list[str] = []
    lines.append("### 計測条件")
    lines.append("")
    lines.append(f"- サンプル枚数：{sample_count} 枚（レイアウト4種 × 撮影条件2種 × 人物違い）")
    lines.append("- 一致判定：全角半角・空白・記号を正規化したうえでの完全一致（電話番号は数字のみで比較）")
    lines.append("- 修正操作回数：正解と一致しなかった項目数（未取得・誤り・余分な出力の合計）")
    if note:
        lines.append(f"- {note}")
    lines.append("")

    lines.append("### 構成別の結果")
    lines.append("")
    lines.append("| 構成 | 項目正答率 | 1枚あたり修正項目数 | 処理時間/枚 | 費用/枚 |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for agg in aggregates:
        if not agg.cards:
            lines.append(f"| {agg.label} | 未計測 | 未計測 | 未計測 | 未計測 |")
            continue
        cost = f"${agg.cost_per_card_usd:.4f}" if agg.cost_per_card_usd else "—"
        lines.append(
            f"| {agg.label} | {agg.overall_accuracy * 100:.1f}% | {agg.mean_edits:.1f} 項目 | "
            f"{agg.mean_seconds:.2f} 秒 | {cost} |"
        )
    lines.append("")

    lines.append("### 項目別の正答率")
    lines.append("")
    header = "| 項目 | " + " | ".join(agg.label for agg in aggregates) + " |"
    lines.append(header)
    lines.append("| --- | " + " | ".join("---:" for _ in aggregates) + " |")
    for key in FIELD_KEYS:
        cells = []
        for agg in aggregates:
            accuracy = agg.field_accuracy(key)
            cells.append("—" if accuracy is None else f"{accuracy * 100:.0f}%")
        lines.append(f"| {FIELD_LABELS[key]} | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("### レイアウト・撮影条件別の修正項目数（1枚あたり）")
    lines.append("")
    variants = sorted({variant for agg in aggregates for variant in agg.per_variant_edits})
    lines.append("| 条件 | " + " | ".join(agg.label for agg in aggregates) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in aggregates) + " |")
    for variant in variants:
        cells = []
        for agg in aggregates:
            values = agg.per_variant_edits.get(variant, [])
            cells.append(f"{statistics.mean(values):.1f}" if values else "—")
        lines.append(f"| {variant} | " + " | ".join(cells) + " |")
    lines.append("")

    failing = [agg for agg in aggregates if agg.errors]
    if failing:
        lines.append("### 実行できなかった構成")
        lines.append("")
        for agg in failing:
            lines.append(f"- **{agg.label}**：{agg.errors[0]}")
        lines.append("")
    return "\n".join(lines)


# 出力先に人が書いた考察がある場合、この目印の間だけを差し替える。
# 目印が無ければ従来どおりファイル全体を計測結果で置き換える。
BEGIN_MARK = "<!-- 計測結果ここから（poc.runner が自動で書き換えます。手で編集しないこと） -->"
END_MARK = "<!-- 計測結果ここまで -->"


def merge_report(out_path: Path, report: str) -> str:
    """既存レポートの目印の内側だけを差し替える。

    レポートには計測値のほかに人が書いた考察・判断の経緯が含まれる。
    再計測のたびに全体を上書きすると、その考察ごと消えてしまう（実際に消した）。
    """
    try:
        current = out_path.read_text(encoding="utf-8")
    except OSError:
        return report

    begin = current.find(BEGIN_MARK)
    end = current.find(END_MARK, begin + 1)
    if begin < 0 or end < 0:
        return report

    head = current[: begin + len(BEGIN_MARK)]
    tail = current[end:]
    return f"{head}\n\n{report}\n{tail}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("poc-result.md"), help="レポートの出力先")
    parser.add_argument("--json", type=Path, default=None, help="生データのJSON出力先")
    parser.add_argument("--count", type=int, default=None, help="サンプル枚数の上限")
    parser.add_argument("--real", type=Path, default=None, help="実名刺サンプルのディレクトリ")
    parser.add_argument("--save-samples", type=Path, default=None, help="生成サンプルの保存先")
    parser.add_argument("--only", default=None, help="実行する構成の記号（例: --only A,D,E）")
    parser.add_argument("--llm-model", default=None, help="LLM抽出のモデル（既定は BCARDS_LLM_MODEL）")
    parser.add_argument("--llm-effort", default=None, help="LLM抽出のエフォート（low/medium/high）")
    args = parser.parse_args()

    samples = load_real_samples(args.real) if args.real else build_samples(args.count)
    if not samples:
        raise SystemExit("サンプルがありません。")
    if args.save_samples:
        from poc.samples import save_samples

        save_samples(samples, args.save_samples)

    pipelines: list[Any] = [
        RulePipeline("A 前処理なし", preprocessor="raw", languages="jpn+eng"),
        RulePipeline("B 改善前の前処理", preprocessor="legacy", languages="jpn+eng"),
        RulePipeline("C 改善後(横書き言語)", preprocessor="current", languages="jpn+eng"),
        RulePipeline("D 改善後(縦書き言語追加)", preprocessor="current", languages="jpn+jpn_vert+eng"),
    ]
    llm_pipeline = LlmPipeline("E 改善後+LLM抽出", model=args.llm_model, effort=args.llm_effort)
    pipelines.append(llm_pipeline)
    # F・G は読み取りエンジンの比較（構成Dと前処理・項目分離を揃えている）。
    # 依存が大きいため任意インストール。入っていなければ「未計測」と出る。
    pipelines.append(EnginePipeline("F 改善後+PaddleOCR", "paddle"))
    pipelines.append(EnginePipeline("G 改善後+EasyOCR", "easyocr"))
    pipelines.append(CombinedEnginePipeline("H 改善後+EasyOCR/tesseract併用", ("easyocr", "tesseract")))

    if args.only:
        wanted = {token.strip().upper() for token in args.only.split(",") if token.strip()}
        pipelines = [p for p in pipelines if p.label.split()[0].upper() in wanted]
        if not pipelines:
            raise SystemExit(f"--only の指定に一致する構成がありません: {args.only}")

    aggregates: list[Aggregate] = []
    raw: dict[str, Any] = {"samples": [s.sample_id for s in samples], "results": {}}

    for pipeline in pipelines:
        agg = Aggregate(label=pipeline.label)
        details = []
        for sample in samples:
            try:
                result = pipeline.run(sample)
            except Exception as exc:
                agg.errors.append(str(exc))
                break
            agg.add(sample, result)
            details.append(
                {
                    "sample": sample.sample_id,
                    "variant": sample.variant,
                    "seconds": round(result.seconds, 3),
                    "fields": result.fields,
                    "truth": sample.truth,
                }
            )
        aggregates.append(agg)
        raw["results"][pipeline.label] = {
            "overall_accuracy": agg.overall_accuracy,
            "mean_edits": agg.mean_edits,
            "mean_seconds": agg.mean_seconds,
            "cost_per_card_usd": agg.cost_per_card_usd,
            "errors": agg.errors,
            "details": details,
        }
        status = agg.errors[0] if agg.errors else (
            f"正答率 {agg.overall_accuracy * 100:.1f}% / 修正 {agg.mean_edits:.1f} 項目 / "
            f"{agg.mean_seconds:.2f} 秒"
        )
        print(f"{pipeline.label}: {status}")

    note = ""
    if llm_pipeline.extractor is None:
        note = (
            "構成E（LLM抽出）は Claude API の認証情報が無い環境のため未計測。"
            "ANTHROPIC_API_KEY を設定して同じコマンドを実行すると計測される"
        )
    report = build_report([a for a in aggregates if a.cards or a.errors], len(samples), note)
    args.out.write_text(merge_report(args.out, report), encoding="utf-8")
    print(f"\nレポートを書き出しました: {args.out}")

    if args.json:
        args.json.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"生データ: {args.json}")


if __name__ == "__main__":
    main()

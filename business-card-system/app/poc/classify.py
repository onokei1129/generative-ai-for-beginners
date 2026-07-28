"""名刺と領収書が混在したスキャンフォルダから、名刺だけを取り出す。

ScanSnap の保存先のように名刺・領収書・その他の書類が同じフォルダに入っている場合、
そのままPoCに掛けると領収書まで名刺として採点されてしまう。
このツールで先に仕分けを行う。

    # 判定するだけ（ファイルは動かさない）
    PYTHONPATH=src .venv/bin/python poc/classify.py "C:/Users/xxx/Dropbox/ScanSnap"

    # 名刺と判定したファイルを別フォルダへコピーする
    PYTHONPATH=src .venv/bin/python poc/classify.py <入力> --copy-to ./poc/real-cards

    # 判定結果をCSVとMarkdownで残す
    PYTHONPATH=src .venv/bin/python poc/classify.py <入力> --csv result.csv --report report.md

判定の考え方（外部サービスへ送信せず、ローカルだけで完結する）:

1. **形状** 名刺は 91×55mm（縦横比 約1.65）。領収書は細長いレシートかA4が多い
2. **文字** 「領収書」「合計」「税込」等と、「株式会社」「TEL」「E-mail」等の
   出現数を数える。OCRは判定用に1パスだけ掛ける（本処理より軽い）
3. 1と2のスコアを合算し、閾値で 名刺 / 領収書 / 不明 に分ける

**不明** に落ちたものは人が見て振り分ける前提。誤って領収書を名刺として
処理するより、迷ったら人に投げるほうが安全なため、閾値は控えめにしてある。
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".heic", ".pdf")

# 名刺の縦横比。91×55mm = 1.655。スキャン時の余白や裁ち落としで前後する
CARD_RATIO = 91 / 55
RATIO_TOLERANCE = 0.28

RECEIPT_WORDS = (
    "領収書", "領収証", "レシート", "納品書", "請求書", "見積書",
    "合計", "小計", "税込", "税抜", "消費税", "内税", "外税", "軽減税率",
    "但し", "上記正に領収", "お預り", "お預かり", "お釣り", "おつり", "釣銭",
    "点数", "単価", "数量", "金額", "税率", "適格請求書", "インボイス",
    "毎度ありがとう", "ありがとうございました", "レジ", "取引", "伝票",
)

CARD_WORDS = (
    "株式会社", "有限会社", "合同会社", "合資会社", "一般社団法人", "財団法人",
    "TEL", "Tel", "FAX", "Fax", "E-mail", "E-MAIL", "Mail", "MOBILE", "Mobile",
    "代表取締役", "取締役", "部長", "課長", "係長", "主任", "支店長", "所長",
    "本部", "事業部", "営業部", "開発部", "総務部", "経理部",
    "http", "www", "@",
)

# 明らかに領収書を示す語。1つでも出れば強く減点する
RECEIPT_STRONG = ("領収書", "領収証", "上記正に領収", "適格請求書", "軽減税率", "お預り")

AMOUNT_PATTERN = re.compile(r"[¥￥]\s?[\d,]{3,}|[\d,]{3,}\s?円")
INVOICE_NO_PATTERN = re.compile(r"T\d{13}")


@dataclass
class Verdict:
    path: Path
    label: str  # "business_card" / "receipt" / "unknown"
    score: float  # 正が名刺寄り、負が領収書寄り
    width: int = 0
    height: int = 0
    ratio: float = 0.0
    reasons: list[str] = field(default_factory=list)
    text: str = ""
    error: str = ""

    @property
    def label_ja(self) -> str:
        return {"business_card": "名刺", "receipt": "領収書", "unknown": "不明"}[self.label]


def load_image(path: Path) -> Image.Image:
    """1枚目のページだけを読む（判定にはそれで足りる）。

    読み込みはアプリ本体と同じ実装（services/images.py）を使う。
    HEIC・TIFF・PDF の扱いが本処理とずれないようにするため。
    """
    from bcards.services.images import load_pages

    pages = load_pages(path.read_bytes(), path.name)
    if not pages:
        raise ValueError("ページを読み取れませんでした。")
    return pages[0].image


def quick_ocr(image: Image.Image, languages: str = "jpn+eng") -> str:
    """判定用の軽いOCR。本処理と違い1パスだけ・縦書き言語なし・縮小して掛ける。"""
    import pytesseract

    from bcards.config import settings

    work = image
    if max(work.size) > 1200:
        scale = 1200 / max(work.size)
        work = work.resize((int(work.width * scale), int(work.height * scale)), Image.LANCZOS)
    try:
        return pytesseract.image_to_string(
            work, lang=languages, config="--psm 6", timeout=settings.ocr_timeout_seconds
        )
    except Exception:
        return ""


def score_shape(width: int, height: int) -> tuple[float, list[str]]:
    """形状によるスコア。縦横比が名刺に近いほど加点する。"""
    if not width or not height:
        return 0.0, []
    ratio = max(width, height) / min(width, height)
    reasons: list[str] = []

    if abs(ratio - CARD_RATIO) <= RATIO_TOLERANCE:
        reasons.append(f"縦横比 {ratio:.2f} が名刺(1.65)に近い")
        return 2.0, reasons
    if ratio >= 2.2:
        reasons.append(f"縦横比 {ratio:.2f} が細長い（レシート形状）")
        return -2.0, reasons
    if 1.35 <= ratio <= 1.48:
        reasons.append(f"縦横比 {ratio:.2f} がA4/A5に近い（書類形状）")
        return -1.0, reasons
    reasons.append(f"縦横比 {ratio:.2f}")
    return 0.0, reasons


def score_text(text: str) -> tuple[float, list[str]]:
    """本文の語からのスコア。"""
    reasons: list[str] = []
    score = 0.0

    strong = [word for word in RECEIPT_STRONG if word in text]
    if strong:
        score -= 4.0
        reasons.append("領収書を示す語: " + "、".join(strong))

    receipt_hits = [word for word in RECEIPT_WORDS if word in text and word not in strong]
    if receipt_hits:
        score -= min(3.0, 0.5 * len(receipt_hits))
        reasons.append(f"領収書系の語 {len(receipt_hits)}種")

    card_hits = [word for word in CARD_WORDS if word in text]
    if card_hits:
        score += min(4.0, 0.6 * len(card_hits))
        reasons.append(f"名刺系の語 {len(card_hits)}種")

    amounts = AMOUNT_PATTERN.findall(text)
    if len(amounts) >= 2:
        score -= 2.0
        reasons.append(f"金額表記 {len(amounts)}箇所")

    if INVOICE_NO_PATTERN.search(text):
        score -= 2.0
        reasons.append("インボイス登録番号(T+13桁)")

    # 名刺は文字数が少ない。レシートは明細が並ぶぶん多くなる
    compact = re.sub(r"\s+", "", text)
    if 0 < len(compact) <= 220:
        score += 1.0
        reasons.append(f"文字数 {len(compact)}（名刺相当）")
    elif len(compact) > 500:
        score -= 1.5
        reasons.append(f"文字数 {len(compact)}（書類相当）")

    return score, reasons


def classify_file(path: Path, *, use_ocr: bool = True) -> Verdict:
    try:
        image = load_image(path)
    except Exception as exc:
        return Verdict(path=path, label="unknown", score=0.0, error=f"読み込めません: {exc}")

    width, height = image.size
    ratio = max(width, height) / min(width, height) if min(width, height) else 0.0
    shape_score, reasons = score_shape(width, height)

    text = quick_ocr(image) if use_ocr else ""
    text_score, text_reasons = score_text(text) if text else (0.0, ["OCRテキストなし"])

    total = shape_score + text_score
    if total >= 2.0:
        label = "business_card"
    elif total <= -2.0:
        label = "receipt"
    else:
        label = "unknown"

    return Verdict(
        path=path,
        label=label,
        score=round(total, 2),
        width=width,
        height=height,
        ratio=round(ratio, 3),
        reasons=reasons + text_reasons,
        text=text,
    )


def collect_files(directory: Path, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in directory.glob(pattern)
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def write_csv(verdicts: list[Verdict], out: Path) -> None:
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ファイル", "判定", "スコア", "幅", "高さ", "縦横比", "根拠", "エラー"])
        for verdict in verdicts:
            writer.writerow([
                str(verdict.path), verdict.label_ja, verdict.score,
                verdict.width, verdict.height, verdict.ratio,
                " / ".join(verdict.reasons), verdict.error,
            ])


def write_report(verdicts: list[Verdict], out: Path, source: Path) -> None:
    counts = {key: sum(1 for v in verdicts if v.label == key) for key in ("business_card", "receipt", "unknown")}
    lines = [
        "# スキャンフォルダの仕分け結果",
        "",
        f"- 対象: `{source}`",
        f"- ファイル数: {len(verdicts)}",
        "",
        "| 判定 | 件数 |",
        "| --- | --- |",
        f"| 名刺 | {counts['business_card']} |",
        f"| 領収書 | {counts['receipt']} |",
        f"| 不明（要目視） | {counts['unknown']} |",
        "",
        "## 不明と判定したファイル",
        "",
        "自動で振り分けず、目視で確認してください。",
        "",
        "| ファイル | スコア | 縦横比 | 根拠 |",
        "| --- | --- | --- | --- |",
    ]
    unknown = [v for v in verdicts if v.label == "unknown"]
    for verdict in unknown:
        lines.append(
            f"| {verdict.path.name} | {verdict.score} | {verdict.ratio} | {' / '.join(verdict.reasons)} |"
        )
    if not unknown:
        lines.append("| （なし） | | | |")

    lines += ["", "## 名刺と判定したファイル", "", "| ファイル | スコア | 縦横比 |", "| --- | --- | --- |"]
    for verdict in verdicts:
        if verdict.label == "business_card":
            lines.append(f"| {verdict.path.name} | {verdict.score} | {verdict.ratio} |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", help="スキャンファイルの入っているフォルダ")
    parser.add_argument("--copy-to", help="名刺と判定したファイルのコピー先")
    parser.add_argument("--copy-unknown", action="store_true", help="不明もコピー先へ入れる（unknown/ 配下）")
    parser.add_argument("--csv", help="判定結果のCSV出力先")
    parser.add_argument("--report", help="判定結果のMarkdown出力先")
    parser.add_argument("--recursive", action="store_true", help="サブフォルダも対象にする")
    parser.add_argument("--no-ocr", action="store_true", help="OCRを使わず形状だけで判定する（高速だが精度は落ちる）")
    parser.add_argument("--limit", type=int, default=0, help="先頭N件だけ処理する（動作確認用）")
    args = parser.parse_args()

    source = Path(args.directory).expanduser()
    if not source.is_dir():
        print(f"フォルダが見つかりません: {source}", file=sys.stderr)
        return 2

    files = collect_files(source, args.recursive)
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"対象ファイルがありません（{'/'.join(IMAGE_SUFFIXES)}）: {source}", file=sys.stderr)
        return 2

    print(f"{len(files)} 件を判定します...")
    verdicts: list[Verdict] = []
    for index, path in enumerate(files, start=1):
        verdict = classify_file(path, use_ocr=not args.no_ocr)
        verdicts.append(verdict)
        print(f"  [{index}/{len(files)}] {path.name}: {verdict.label_ja}（{verdict.score:+.1f}）")

    counts = {key: sum(1 for v in verdicts if v.label == key) for key in ("business_card", "receipt", "unknown")}
    print()
    print(f"名刺 {counts['business_card']} / 領収書 {counts['receipt']} / 不明 {counts['unknown']}")

    if args.copy_to:
        dest = Path(args.copy_to).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        for verdict in verdicts:
            if verdict.label == "business_card":
                shutil.copy2(verdict.path, dest / verdict.path.name)
                copied += 1
            elif verdict.label == "unknown" and args.copy_unknown:
                (dest / "unknown").mkdir(exist_ok=True)
                shutil.copy2(verdict.path, dest / "unknown" / verdict.path.name)
        print(f"{copied} 件を {dest} へコピーしました。")
        print("PoCに掛ける場合は、各画像に同名の .json（正解ラベル）を用意してから")
        print(f"  PYTHONPATH=src .venv/bin/python poc/runner.py --real {dest} --out real.md")

    if args.csv:
        write_csv(verdicts, Path(args.csv))
        print(f"CSV: {args.csv}")
    if args.report:
        write_report(verdicts, Path(args.report), source)
        print(f"レポート: {args.report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

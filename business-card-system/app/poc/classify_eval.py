"""仕分け（poc/classify.py）の正答率を測る。

    PYTHONPATH=src .venv/bin/python -m poc.receipts --out /tmp/mixed
    PYTHONPATH=src .venv/bin/python -m poc.classify_eval /tmp/mixed

`_truth.csv`（poc/receipts.py が生成）を正解として、混同行列と正答率を出す。
実データで検証する場合は、同じ形式で `_truth.csv` を手で用意すればよい。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from .classify import classify_file  # noqa: E402

LABELS = ("business_card", "receipt", "unknown")
LABEL_JA = {"business_card": "名刺", "receipt": "領収書", "unknown": "不明"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--out", help="Markdownレポートの出力先")
    args = parser.parse_args()

    directory = Path(args.directory)
    truth_path = directory / "_truth.csv"
    if not truth_path.exists():
        print(f"_truth.csv がありません: {truth_path}", file=sys.stderr)
        return 2

    with truth_path.open(encoding="utf-8") as handle:
        truth = {row["file"]: row["truth"] for row in csv.DictReader(handle)}

    matrix = {actual: dict.fromkeys(LABELS, 0) for actual in ("business_card", "receipt")}
    mistakes: list[tuple[str, str, str, float, str]] = []

    for name, actual in sorted(truth.items()):
        verdict = classify_file(directory / name, use_ocr=not args.no_ocr)
        matrix[actual][verdict.label] += 1
        if verdict.label != actual:
            mistakes.append((name, actual, verdict.label, verdict.score, " / ".join(verdict.reasons)))

    total = len(truth)
    correct = sum(matrix[label][label] for label in matrix)
    unknown = sum(matrix[label]["unknown"] for label in matrix)
    wrong = total - correct - unknown

    lines = [
        "# 名刺／領収書の仕分け精度",
        "",
        f"- 対象: `{directory}` {total} 件",
        f"- OCR: {'使わない（形状のみ）' if args.no_ocr else '使う'}",
        "",
        "## 混同行列",
        "",
        "| 実際＼判定 | 名刺 | 領収書 | 不明 |",
        "| --- | --- | --- | --- |",
    ]
    for actual in ("business_card", "receipt"):
        row = matrix[actual]
        lines.append(
            f"| {LABEL_JA[actual]} | {row['business_card']} | {row['receipt']} | {row['unknown']} |"
        )

    lines += [
        "",
        "## 集計",
        "",
        "| 指標 | 値 |",
        "| --- | --- |",
        f"| 正答 | {correct} / {total}（{correct / total * 100:.1f}%） |",
        f"| 不明（人が確認） | {unknown}（{unknown / total * 100:.1f}%） |",
        f"| **誤判定** | **{wrong}（{wrong / total * 100:.1f}%）** |",
        "",
        "誤判定のうち、領収書を名刺と判定したものが実害の大きい誤りです。",
        f"件数: {matrix['receipt']['business_card']}",
        "",
    ]

    if mistakes:
        lines += [
            "## 正解と一致しなかったファイル",
            "",
            "| ファイル | 実際 | 判定 | スコア | 根拠 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name, actual, got, score, reasons in mistakes:
            lines.append(f"| {name} | {LABEL_JA[actual]} | {LABEL_JA[got]} | {score:+.1f} | {reasons} |")

    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"レポート: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

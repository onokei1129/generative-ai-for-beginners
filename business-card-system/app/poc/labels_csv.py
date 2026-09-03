"""正解ラベルを CSV で受け渡しする（Excelで入力したい場合）。

入力画面（`poc/label.py`）を使わず、Excelで入力したい・入力を他の人に頼みたい
場合はこちらを使う。

    # 1. 空の雛形を書き出す（画像1枚につき1行）
    PYTHONPATH=src .venv/bin/python -m poc.labels_csv export ./poc/real-cards --out labels.csv

    # 2. labels.csv を Excel で開いて入力する（file 列は変更しない）

    # 3. 取り込む（画像と同じ場所に .json が作られる）
    PYTHONPATH=src .venv/bin/python -m poc.labels_csv import ./poc/real-cards --csv labels.csv

CSV は Excel でそのまま開けるよう UTF-8 BOM 付きで書き出す。
既に `.json` がある画像は、その内容を初期値として書き出す（続きから入力できる）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poc.label import IMAGE_SUFFIXES, LABELS  # noqa: E402
from poc.samples import FIELD_KEYS  # noqa: E402

# Excel での見出しは日本語にする。取り込み時は英語キーでも日本語見出しでも受け付ける
HEADER = ["file"] + [LABELS[key] for key in FIELD_KEYS]
JA_TO_KEY = {LABELS[key]: key for key in FIELD_KEYS}


def images_in(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


def do_export(directory: Path, out: Path) -> int:
    images = images_in(directory)
    if not images:
        print(f"画像が見つかりません: {directory}", file=sys.stderr)
        return 2

    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        filled = 0
        for image in images:
            label = image.with_suffix(".json")
            values = {}
            if label.exists():
                values = json.loads(label.read_text(encoding="utf-8"))
                filled += 1
            writer.writerow([image.name] + [str(values.get(k, "") or "") for k in FIELD_KEYS])

    print(f"{len(images)} 行の雛形を書き出しました: {out}")
    if filled:
        print(f"  うち {filled} 行は入力済みの内容を反映しています。")
    print("\nExcel で開いて入力してください。")
    print("  - file 列は変更しないでください（画像との対応が取れなくなります）")
    print("  - 名刺に記載の無い項目は空欄のままにしてください")
    print(f"\n入力後: python -m poc.labels_csv import {directory} --csv {out}")
    return 0


def do_import(directory: Path, csv_path: Path) -> int:
    images = {p.name: p for p in images_in(directory)}
    if not csv_path.exists():
        print(f"CSVが見つかりません: {csv_path}", file=sys.stderr)
        return 2

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        print("CSVに行がありません。", file=sys.stderr)
        return 2

    # 見出しが日本語でも英語キーでも受け付ける
    columns = rows[0].keys()
    mapping: dict[str, str] = {}
    for column in columns:
        name = (column or "").strip()
        if name in JA_TO_KEY:
            mapping[column] = JA_TO_KEY[name]
        elif name in FIELD_KEYS:
            mapping[column] = name

    missing = set(FIELD_KEYS) - set(mapping.values())
    if missing:
        print(
            "CSVに次の列が見当たりません: "
            + "、".join(LABELS[k] for k in FIELD_KEYS if k in missing),
            file=sys.stderr,
        )
        print("  見出し行を書き換えていないか確認してください。", file=sys.stderr)
        return 2

    written = 0
    skipped: list[str] = []
    empty: list[str] = []
    for row in rows:
        name = (row.get("file") or row.get("ファイル") or "").strip()
        if not name:
            continue
        image = images.get(name)
        if image is None:
            skipped.append(name)
            continue
        values = {key: "" for key in FIELD_KEYS}
        for column, key in mapping.items():
            values[key] = str(row.get(column) or "").strip()
        if not any(values.values()):
            empty.append(name)
            continue
        image.with_suffix(".json").write_text(
            json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written += 1

    print(f"{written} 件の正解ラベルを保存しました: {directory}")
    if empty:
        print(f"  未入力のため飛ばした行: {len(empty)} 件（{', '.join(empty[:5])}{' ほか' if len(empty) > 5 else ''}）")
    if skipped:
        print(
            f"  対応する画像が無い行: {len(skipped)} 件（{', '.join(skipped[:5])}"
            f"{' ほか' if len(skipped) > 5 else ''}）",
            file=sys.stderr,
        )
    if written:
        print(f"\n精度を測る: python poc/runner.py --real {directory} --out real.md")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="空の雛形CSVを書き出す")
    p_export.add_argument("directory")
    p_export.add_argument("--out", default="labels.csv")

    p_import = sub.add_parser("import", help="入力済みCSVを取り込む")
    p_import.add_argument("directory")
    p_import.add_argument("--csv", default="labels.csv")

    args = parser.parse_args()
    directory = Path(args.directory).expanduser().resolve()
    if not directory.is_dir():
        print(f"フォルダが見つかりません: {directory}", file=sys.stderr)
        return 2

    if args.command == "export":
        return do_export(directory, Path(args.out))
    return do_import(directory, Path(args.csv))


if __name__ == "__main__":
    raise SystemExit(main())

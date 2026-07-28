"""ラベル付けがどこまで進んだかを表示する。

    .venv/bin/python -m poc.progress ./poc/real-cards

測定に入る前に「あと何枚か」「未確認の欄が残っていないか」を確認するために使う。
未確認（OCRの下書きを人が触っていない欄）が残ったまま測ると、精度が実際より
良く出てしまうため、ここで気づけるようにしている。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .samples import FIELD_KEYS

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic")

# 測定に足りる枚数の目安（論点C）
RECOMMENDED = 30


def collect(directory: Path) -> dict:
    images: list[Path] = []
    for path in sorted(directory.glob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            images.append(path)

    labeled: list[Path] = []
    unlabeled: list[Path] = []
    unverified: dict[str, list[str]] = {}
    empty: list[Path] = []

    for image in images:
        label_path = image.with_suffix(".json")
        if not label_path.exists():
            unlabeled.append(image)
            continue
        labeled.append(image)
        try:
            truth = json.loads(label_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            unverified[image.name] = ["（ラベルファイルが壊れています）"]
            continue
        pending = truth.get("_unverified") or []
        if pending:
            unverified[image.name] = list(pending)
        elif not any(str(truth.get(key) or "").strip() for key in FIELD_KEYS):
            empty.append(image)

    return {
        "images": images,
        "labeled": labeled,
        "unlabeled": unlabeled,
        "unverified": unverified,
        "empty": empty,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", nargs="?", default="./poc/real-cards", help="名刺画像のフォルダ")
    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.exists():
        print(f"フォルダがありません: {directory.resolve()}", file=sys.stderr)
        print("先に「名刺を仕分ける」を実行してください。", file=sys.stderr)
        return 2

    result = collect(directory)
    total = len(result["images"])
    done = len(result["labeled"])
    unverified = result["unverified"]

    print(f"対象フォルダ: {directory.resolve()}")
    print()

    if total == 0:
        print("画像が1枚もありません。")
        print("先に「名刺を仕分ける」を実行してください。")
        return 1

    bar_width = 30
    filled = round(bar_width * done / total)
    print(f"  ラベル付け  [{'#' * filled}{'.' * (bar_width - filled)}]  {done} / {total} 枚")
    if unverified:
        print(f"  未確認の欄  {len(unverified)} 枚に残っています")
    print()

    unknown_dir = directory / "unknown"
    if unknown_dir.is_dir():
        pending = [p for p in unknown_dir.glob("*") if p.suffix.lower() in IMAGE_SUFFIXES]
        if pending:
            print(f"【要対応】「不明」が {len(pending)} 枚あります: {unknown_dir.resolve()}")
            print("  名刺なら1つ上のフォルダへ移してください。領収書などはそのままで構いません。")
            print()

    if result["unlabeled"]:
        print(f"未入力: {len(result['unlabeled'])} 枚")
        for path in result["unlabeled"][:5]:
            print(f"  - {path.name}")
        if len(result["unlabeled"]) > 5:
            print(f"  ほか {len(result['unlabeled']) - 5} 枚")
        print()

    if unverified:
        print("【注意】人が確認していない欄が残っています。")
        print("  OCRの下書きがそのまま正解になるため、精度が実際より良く出ます。")
        for name, fields in list(unverified.items())[:5]:
            print(f"  - {name}: {', '.join(fields)}")
        if len(unverified) > 5:
            print(f"  ほか {len(unverified) - 5} 枚")
        print()

    if result["empty"]:
        print(f"全項目が空のラベルが {len(result['empty'])} 枚あります（名刺でない可能性）:")
        for path in result["empty"][:5]:
            print(f"  - {path.name}")
        print()

    # 次にやることを1つだけ示す
    print("-" * 44)
    if result["unlabeled"]:
        print(f"次にやること: 「ラベル入力（実際の名刺）」で残り {len(result['unlabeled'])} 枚を入力する")
    elif unverified:
        print(f"次にやること: 「ラベル入力（実際の名刺）」で黄色い欄（{len(unverified)} 枚）を確認する")
    elif done < RECOMMENDED:
        print(f"次にやること: 枚数が {done} 枚です。{RECOMMENDED} 枚以上あると精度の数字が安定します")
        print("            このまま測ることもできます（「精度を測る」）")
    else:
        print("次にやること: 「精度を測る」を実行する")
    print("-" * 44)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

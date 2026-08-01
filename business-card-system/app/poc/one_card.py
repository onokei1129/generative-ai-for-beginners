"""名刺1枚ぶんの重い処理を、別プロセスで行うための入口。

    python -m poc.one_card ocr   <ファイル>            → 結果をJSONで標準出力へ
    python -m poc.one_card image <ファイル> <出力.jpg> → 表示用のJPEGを書き出す

## なぜ別プロセスにするのか

実テスト（222枚）で、ラベル入力の画面が2度、途中で応答しなくなった。
画像が出なくなり、下書きも止まったままになる。

PDFの描画（pypdfium2）とOCR（tesseract）は C のライブラリを呼ぶ。ここが
落ちるとプロセスごと消えるため、Python 側には何も残らない。同じ入口で
動かしている限り、1枚の名刺で落ちると**そのあとの全部が止まる**。

別のプロセスに出せば、落ちるのは子だけで済む。画面には「この1枚は失敗」と
出て、次の名刺へ進める。どの工程で落ちたかも終了コードとして残る。

1枚ごとにプロセスが終わるので、抱えた画像も確実に解放される。
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run_ocr(path: Path) -> dict:
    from bcards.services.images import process_file
    from bcards.services.ocr import recognize_card

    # 使うのは1枚目だけ。1ページに絞らないと、複数ページPDFでページごとに
    # 補正まで走る（実測：20ページで 1.17GB / 23秒 → 1ページなら 78MB / 1.2秒）。
    cards = process_file(path.read_bytes(), path.name, page_limit=1)
    if not cards:
        raise RuntimeError("画像を1枚も取り出せませんでした")

    output, parsed = recognize_card(cards[0].ocr_image)
    return {
        "fields": {key: str(value or "") for key, value in parsed["fields"].items()},
        "text": output.text if output is not None else "",
    }


def write_image(path: Path, out: Path) -> None:
    from bcards.services.images import load_pages

    pages = load_pages(path.read_bytes(), path.name, limit=1)
    if not pages:
        raise RuntimeError("ページがありません")

    buffer = io.BytesIO()
    pages[0].image.convert("RGB").save(buffer, format="JPEG", quality=85)
    out.write_bytes(buffer.getvalue())


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("使い方: one_card.py ocr <ファイル> | image <ファイル> <出力>", file=sys.stderr)
        return 2

    mode, target = argv[0], Path(argv[1])
    if mode == "ocr":
        json.dump(run_ocr(target), sys.stdout, ensure_ascii=False)
        return 0
    if mode == "image":
        if len(argv) < 3:
            print("出力先が要ります", file=sys.stderr)
            return 2
        write_image(target, Path(argv[2]))
        return 0

    print(f"知らない指定です: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

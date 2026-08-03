"""名刺1枚ぶんの重い処理を、別プロセスで行うための入口。

    python -m poc.one_card ocr   <ファイル>            → 結果をJSONで標準出力へ
    python -m poc.one_card image <ファイル> <出力.jpg> → 表示用のJPEGを書き出す
    python -m poc.one_card serve                       → 常駐して何枚でも受ける

## なぜ別プロセスにするのか

実テスト（222枚）で、ラベル入力の画面が2度、途中で応答しなくなった。
画像が出なくなり、下書きも止まったままになる。

PDFの描画（pypdfium2）とOCR（tesseract）は C のライブラリを呼ぶ。ここが
落ちるとプロセスごと消えるため、Python 側には何も残らない。同じ入口で
動かしている限り、1枚の名刺で落ちると**そのあとの全部が止まる**。

別のプロセスに出せば、落ちるのは子だけで済む。画面には「この1枚は失敗」と
出て、次の名刺へ進める。どの工程で落ちたかも終了コードとして残る。

## なぜ常駐させるのか（serve）

はじめは名刺1枚ごとにこのプロセスを作り直していた。併用構成（EasyOCR +
tesseract）を既定にしたあと、実測で**1枚あたり 1.4GB / 12秒**かかっている。
毎回 EasyOCR のモデルを読み直すためで、先読みの裏方と重なると同時に2つ
動き、ピークは約2.8GBになる。224枚を通す作りではない。

`serve` は標準入力から1行1件のJSONを受け、1行1件のJSONを返す。

    {"mode": "ocr", "args": ["/path/card.jpg"]}
    → {"ok": true, "result": {"fields": {...}, "text": "..."}}
    → {"ok": false, "error": "..."}

モデルの読み込みは最初の1枚だけで済む。別プロセスである以上、C の
ライブラリが落ちて道連れになるのは子だけ、という当初の狙いは変わらない
（親は落ちたことに気づいて作り直す）。
"""

from __future__ import annotations

import io
import json
import sys
import traceback
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


def emit(payload: dict) -> None:
    """結果は UTF-8 のバイトで書く。文字として書いてはいけない。

    `sys.stdout` は**画面の文字コード**で書く。Windows の日本語環境では
    そこが cp932 になる。cp932 の「ソ」は 0x83 0x5C で、2バイト目が円記号
    （UTF-8 では \\）。親は UTF-8 として読むため、この \\ が直後の引用符を
    打ち消し、JSON の文字列が閉じなくなる。

    実テストの1枚（姓が「ソ」）で、画面にこう出た:

        OCR（別プロセス）で失敗（Expecting ',' delimiter: line 1 column 33 (char 32)）

    「ソ」に限らず、日本語が入っていれば cp932 のバイト列は UTF-8 として
    読めない。つまり**日本語の項目が取れた名刺ほど失敗する**。
    """
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()


def warn(text: str) -> None:
    """理由も UTF-8 のバイトで書く（画面にそのまま出るため）。"""
    sys.stderr.buffer.write(f"{text}\n".encode("utf-8"))
    sys.stderr.buffer.flush()


class BadRequest(RuntimeError):
    """指定が足りない、または知らない指定。"""


def dispatch(mode: str, args: list[str]) -> dict:
    """1件ぶんの仕事をする。一度きりの呼び出しでも `serve` でも、ここを通す。"""
    if mode == "ocr":
        if not args:
            raise BadRequest("ファイルが要ります")
        return run_ocr(Path(args[0]))
    if mode == "image":
        if len(args) < 2:
            raise BadRequest("出力先が要ります")
        write_image(Path(args[0]), Path(args[1]))
        return {}
    if mode == "echo":
        # 受け渡しそのものを確かめるためだけの指定（cp932 の「ソ」問題など）。
        # 重い処理を動かさずに、文字が壊れずに往復するかを見る。
        return {"echo": args[0] if args else ""}
    raise BadRequest(f"知らない指定です: {mode}")


def emit_line(payload: dict) -> None:
    """`serve` の返事を1行で書く。`emit` と同じく UTF-8 のバイトで書く。"""
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def serve() -> int:
    """標準入力から1行1件のJSONを受け、1行1件のJSONを返す。

    ここでは**例外で終わらない**。1枚の失敗でこのプロセスが終わると、
    そのあとの名刺すべてがモデルの読み直しから始まってしまう。失敗は
    `{"ok": false, "error": ...}` として返し、次の1行を待つ。

    C のライブラリが落ちた場合はそもそもここへ戻ってこない。そのときは
    標準出力が閉じるので、親が気づいて作り直す。
    """
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return 0
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            reply = {"ok": True, "result": dispatch(request.get("mode", ""), request.get("args") or [])}
        except Exception as exc:  # noqa: BLE001 - 失敗も返事として返す
            # traceback は**返事に入れて**渡す。標準エラーへ書くだけだと、親は
            # 標準出力と標準エラーを別々の裏方で読むため、返事のほうが先に
            # 届いて記録が空になることがある（実際にテストで再現した）。
            reply = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        emit_line(reply)


def main(argv: list[str]) -> int:
    if not argv:
        warn("使い方: one_card.py ocr <ファイル> | image <ファイル> <出力> | serve")
        return 2

    if argv[0] == "serve":
        return serve()

    try:
        emit(dispatch(argv[0], argv[1:]))
    except BadRequest as exc:
        warn(str(exc))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

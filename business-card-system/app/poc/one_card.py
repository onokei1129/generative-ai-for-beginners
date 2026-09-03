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

import faulthandler
import io
import json
import sys
import traceback
from pathlib import Path

# C のライブラリが落ちた瞬間の位置を標準エラーへ書く。
#
# PDFの描画（pypdfium2）・OCR（tesseract）・EasyOCR（PyTorch）はどれも C を
# 呼ぶ。ここが落ちるとプロセスはその場で消え、`except` も `finally` も通らない
# ため、`serve` の失敗の返事すら出せない。**それが唯一の手がかりになる。**
#
# 親は標準エラーを読み続けているので、記録（ラベル入力ログ.txt）へ移される。
faulthandler.enable(all_threads=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# その回の1枚目だと伝えられたときの合図と、そのとき使う軽い読み取り機。
FIRST_CARD_HINT = "first"
QUICK_PROVIDER = "tesseract"


def provider_for(hint: str | None) -> str | None:
    """1枚目の合図を、実際に使う読み取り機に直す。None は設定どおり。

    落とすのは**併用構成のときだけ**。併用は EasyOCR のモデルを読み込むため
    最初の1枚に実測45秒かかるが、それ以外の構成ではその読み込みが無いので、
    落とす理由も無い。設定を無視して tesseract を強制すると、擬似OCRや
    別のサービスを指定している環境まで置き換えてしまう。
    """
    if hint != FIRST_CARD_HINT:
        return None

    from bcards.config import settings
    from bcards.services.ocr import COMBINED

    if (settings.ocr_provider or "").lower() != COMBINED:
        return None
    return QUICK_PROVIDER


def run_ocr(path: Path, hint: str | None = None) -> dict:
    """1枚を読む。`hint` に1枚目の合図が来たら、軽い読み取り機で済ませる。"""
    from bcards.services.images import process_file
    from bcards.services.ocr import recognize_card

    # 使うのは1枚目だけ。1ページに絞らないと、複数ページPDFでページごとに
    # 補正まで走る（実測：20ページで 1.17GB / 23秒 → 1ページなら 78MB / 1.2秒）。
    cards = process_file(path.read_bytes(), path.name, page_limit=1)
    if not cards:
        raise RuntimeError("画像を1枚も取り出せませんでした")

    output, parsed = recognize_card(cards[0].ocr_image, provider_for(hint))
    return {
        "fields": {key: str(value or "") for key, value in parsed["fields"].items()},
        "text": output.text if output is not None else "",
    }


def write_image(path: Path, out: Path, turn: int = 0) -> None:
    """画面に出す画像を書き出す。**向きを直したものを出す。**

    横型の名刺を読み取り機に横向きに置くと、画像は90度回った状態で入って
    くる。取り込みの仕組みはこれを直しているのに、画面に出す側は補正を
    通しておらず、利用者には横倒しのまま見えていた。手で入力するときに
    読みづらく、画像と欄を見比べられない。

    直すのは**向きだけ**にする。はじめは取り込みの補正を丸ごと通したが、
    実測で重すぎた。

        load_pages のみ    0.2秒 / 最大RSS  94MB
        process_file 全部  6.0秒 / 最大RSS 249MB

    輪郭の切り出し・傾き補正・明るさ補正は表示のためには要らないうえ、
    これがOCRの子プロセスと**同時に**動く。実テストでサーバーが落ちた。

    向きの検出は**余白を落とした縮小の写しで**行う。原寸のままだと実測で
    1枚あたり 4.5〜5.6秒かかっていた（利用者の環境でも約5秒）。ただし
    **ページごと縮めてはいけない**——名刺が小さくなりすぎて判定不能になり、
    実テスト25枚目が逆さのまま出た（`detect_rotation_on_page` を参照）。
    回すのは原寸の画像。

    縦型の名刺を横倒しにしないこと
    ------------------------------
    はじめは検出のあとに `orient_landscape`（縦長なら90度回して横長にする）
    も通していた。**これが縦型の名刺を横倒しにする。** 実測:

        縦書きの縦型名刺 1240x1754
          → 向きの検出は 0度（正しい。回す必要なし）
          → orient_landscape が -90度回す
          → 画面には 1754x1240 の横倒しで出る

    名刺の形だけを見て回す判定は、縦書き名刺を巻き添えにすることが
    PoCの時点で分かっていた（services/orientation の説明を参照）。
    表示でも同じで、日本語の縦型名刺は**縦長のままが正しい**。

    向きの検出（OSD）だけで、読み取り機に横向きに置かれた名刺は戻せる
    （横型を90度回して置いた画像に対し、OSDは 270度と答える）。検出が
    効かなかった名刺は取り込んだままの向きで出る——**回しすぎて読めなく
    するより良い**。

    補正に失敗しても画像は出す。出ないと手入力の手がかりが消える。

    利用者が回す分（turn）
    ----------------------
    向きの検出は外すことがある。実テストでは、22枚目は直ったのに25枚目は
    外したまま、という状態になった。**外した1枚を利用者が直せないと、その
    名刺は手入力にも使えない。** 自動の判定に足す形で、時計回りの角度を
    受け取る（90/180/270）。
    """
    from bcards.services.images import load_pages
    from bcards.services.orientation import MIN_CONFIDENCE, detect_rotation_on_page

    pages = load_pages(path.read_bytes(), path.name, limit=1)
    if not pages:
        raise RuntimeError("ページがありません")

    shown = pages[0].image
    try:
        degrees, confidence = detect_rotation_on_page(shown)
        if degrees and confidence >= MIN_CONFIDENCE:
            # OSD の rotate は「この角度だけ時計回りに回すと正立する」。
            # PIL は反時計回りなので符号を反転する。
            shown = shown.rotate(-degrees, expand=True)
    except Exception:  # noqa: BLE001 - 直せなくても元の画像を出す
        shown = pages[0].image

    turn %= 360
    if turn:
        shown = shown.rotate(-turn, expand=True)

    buffer = io.BytesIO()
    shown.convert("RGB").save(buffer, format="JPEG", quality=85)
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
        hint = args[1] if len(args) > 1 else None
        return run_ocr(Path(args[0]), hint)
    if mode == "image":
        if len(args) < 2:
            raise BadRequest("出力先が要ります")
        turn = int(args[2]) if len(args) > 2 and args[2] else 0
        write_image(Path(args[0]), Path(args[1]), turn)
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

"""実名刺に正解ラベルを付けるための入力画面。

    PYTHONPATH=src .venv/bin/python poc/label.py ./poc/real-cards

ブラウザで http://127.0.0.1:8100/ を開き、名刺画像を見ながら項目を入力する。
画像と同じ名前の `.json` が同じフォルダに保存され、そのまま
`poc/runner.py --real` で精度測定に使える。

OCR精度の比較（論点C）には、**人が確認した正解**が要る。
この画面はその作成を楽にするためのもので、外部へは何も送信しない。

## 目安

名刺1枚あたり14項目、40枚で560項目になる。1枚1〜2分として1時間強。
記載のない項目は空欄のままでよい（空欄も「その項目は無い」という正解になる）。

## OCRの下書きについて

既定でOCRが下書きを入れる（実際のアプリと同じ流れ）。OCRが入れた欄は
**黄色＋「未確認」**で示され、その欄に触れると印が消える。

保存時、触っていない欄は `_unverified` として記録する。
その正解ラベルで精度を測ると `poc/runner.py` が警告を出す。
OCRの下書きをそのまま正解にすると、測定値が実際より良く出るため。

空欄から入力したい場合は `--no-prefill` を付ける。
"""

from __future__ import annotations

import argparse
import atexit
import glob
import json
import os
import queue
import sys
import threading
import traceback
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `python poc/label.py` でも動くように

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse  # noqa: E402

from poc.samples import FIELD_KEYS  # noqa: E402

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".heic", ".pdf")

LABELS = {
    "last_name": "姓",
    "first_name": "名",
    "last_name_kana": "姓（ふりがな）",
    "first_name_kana": "名（ふりがな）",
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

HINTS = {
    "last_name": "例: 山田",
    "first_name": "例: 太郎",
    "last_name_kana": "名刺に記載が無ければ空欄",
    "first_name_kana": "名刺に記載が無ければ空欄",
    "company_name": "「株式会社」も含めて記載どおりに",
    "department_name": "例: 営業本部 第一営業部",
    "title": "例: 部長",
    "postal_code": "例: 100-0001（〒は不要）",
    "address": "記載どおりに。改行は空白1つに",
    "tel": "記載どおりに（ハイフンも）",
    "mobile": "携帯番号。無ければ空欄",
    "fax": "無ければ空欄",
    "email": "",
    "url": "例: https://www.example.co.jp",
}


def _disk_version() -> str:
    """いま**ディスクにある**版を返す。動いている版とは限らない。"""
    import subprocess

    root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%h %cd", "--date=format:%m/%d %H:%M"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # git が使えない環境では、このファイルの更新時刻で代用する
    import datetime

    stamp = datetime.datetime.fromtimestamp(Path(__file__).stat().st_mtime)
    return stamp.strftime("%m/%d %H:%M")


# 起動した時点の版。**このサーバーが動かしている**コードの版はこちら。
#
# 以前は要求のたびにディスクを見ていた。取得（git pull）はサーバーを立てた
# まま行えるため、ディスクだけが新しくなり、画面には新しい版が出るのに
# 動いているのは古いコード、という状態になる。版を出したのは「更新できて
# いるか」をその場で確かめるためなので、これでは逆に取り違えを招く。
_RUNNING_VERSION = _disk_version()


def _version() -> str:
    """画面に出す版。動いている版を示し、ディスクと違えば併記する。"""
    disk = _disk_version()
    if disk != _RUNNING_VERSION:
        return f"{_RUNNING_VERSION}（動作中／ディスクは {disk}。開き直してください）"
    return _RUNNING_VERSION


# 重い処理を任せる子プロセスの入口。
ONE_CARD = Path(__file__).resolve().parent / "one_card.py"

# 1枚にかける上限。これを超えたら子を打ち切る（待ち続けるより空欄のほうがよい）。
CHILD_TIMEOUT = 120

# 作り直した子の1枚目だけは長めに待つ。EasyOCR のモデルの読み込みが入るため
# （実測で 1回目 99.3秒 / 2回目 12.4秒。2回目も毎回読み直していた頃の値）。
FIRST_CALL_TIMEOUT = 300


class ChildFailed(RuntimeError):
    """子プロセスが失敗した。終了コードと標準エラーを添える。"""


# 失敗の全文を残す先。コンソールは流れて消えるうえ、閉じると何も残らない。
# 実テストでは「画面にこう出た」だけが手がかりで、原因の特定に往復していた。
LOG_PATH = Path(__file__).resolve().parent / "ラベル入力ログ.txt"


def _log_failure(what: str) -> None:
    """失敗の全文をコンソールとファイルの両方へ書く。

    コンソールへの出力は、そこで例外を出さないようにすること。Windows の
    日本語環境では画面の文字コードが cp932 で、書けない文字があると
    `print` 自体が UnicodeEncodeError を出す。それが握られていない場所で
    起きると、元の失敗ではなくそちらが表に出て、原因が分からなくなる。
    """
    _log_text(what, traceback.format_exc())


# C のライブラリが落ちた瞬間の位置を書く先。
CRASH_PATH = Path(__file__).resolve().parent / "落ちた記録.txt"

# `faulthandler` に渡したファイルは開いたまま持っておくこと。
# 閉じられると（回収されると）記録が無効になる。
_CRASH_FILE = None


def enable_crash_report() -> None:
    """落ちた瞬間を記録に残す。

    Python の例外なら `_log_failure` が拾える。しかし **C のライブラリが
    落ちるとプロセスはその場で消える**ため、`except` も `finally` も通らない。
    PDFの描画（pypdfium2）・OCR（tesseract）・EasyOCR（PyTorch）はどれも C を
    呼ぶので、ここが落ちると Python 側には何も残らない。

    実テストで、サーバーが応答しなくなったときに記録が空のまま終わっていた
    （5・6枚目、8枚目、「前へ」で戻ったとき）。手がかりが1つも無い状態だった。

    書けなくても起動は止めない。記録は手がかりであって、目的ではない。
    """
    import faulthandler

    global _CRASH_FILE
    try:
        _CRASH_FILE = CRASH_PATH.open("a", encoding="utf-8")
        faulthandler.enable(file=_CRASH_FILE, all_threads=True)
    except Exception:  # noqa: BLE001 - 記録できなくても本筋を止めない
        pass


def report_last_crash() -> None:
    """前回落ちた記録が残っていれば、起動時に在り処を知らせる。

    利用者は「サーバーが応答していません」を見て黒い画面を開き直す。その
    ときに出しておかないと、せっかく残した手がかりが読まれないまま終わる。
    """
    try:
        if not CRASH_PATH.exists() or not CRASH_PATH.read_text(encoding="utf-8").strip():
            return
    except Exception:  # noqa: BLE001 - 読めなくても起動を止めない
        return
    print()
    print("【前回、途中で落ちた記録があります】")
    print(f"  {CRASH_PATH}")
    print("  このファイルと、下の記録を送っていただけると原因を追えます。")
    print(f"  {LOG_PATH}")
    print()


def _log_step(what: str) -> None:
    """いま何をしているかを1行だけ記録に残す。

    実テストで、特定の名刺を開くと**サーバー自体が応答しなくなる**（5・6枚目、
    そのあと8枚目）。重い処理は別プロセスに出してあるので子が落ちても親は
    生き残るはずで、子を1つ保つ形にしても直らなかった。

    落ちると Python 側には何も残らない。例外も traceback も出ないので
    `_log_failure` は動かない。そこで**始める前に**書いておく。記録の最後の
    行が「どの名刺の、どの工程で止まったか」を示す。

    書けなくても本筋を止めない（記録は手がかりであって、目的ではない）。
    """
    import datetime

    stamp = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}  {what}\n")
    except Exception:  # noqa: BLE001 - 記録できなくても本筋を止めない
        pass


def _log_text(what: str, body: str) -> None:
    """本文を指定して記録する（子プロセス側の traceback を残すのに使う）。"""
    import datetime

    stamp = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
    text = f"\n===== {stamp}  {what} =====\n{body}"
    try:
        sys.stderr.buffer.write(text.encode("utf-8", "replace"))
        sys.stderr.buffer.flush()
    except Exception:  # noqa: BLE001 - 記録できなくても本筋を止めない
        pass
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(text)
    except Exception:  # noqa: BLE001 - 同上
        pass


class _Worker:
    """重い処理を任せる子プロセス。1つを保ち続ける。

    標準出力・標準エラーの2本は、それぞれ裏方が読み続ける。読まずに放っておくと
    パイプ（既定で64KB）が埋まった時点で、子は書き込みのところで止まる。
    1枚ごとに作り直していた頃は最後にまとめて読めばよかったが、常駐させる
    以上は読み続けるしかない。標準エラーには、子が失敗を返すたびに traceback
    の全文が流れる（poc/one_card.py の serve）。
    """

    def __init__(self) -> None:
        import collections
        import subprocess

        # 子の標準出力・標準エラーを UTF-8 に固定する。Windows の日本語環境では
        # 既定が cp932 で、Python が出す traceback もそちらの文字コードで届く。
        # 結果そのものは子が UTF-8 のバイトで書く（poc/one_card.py の emit_line）。
        self.process = subprocess.Popen(
            [sys.executable, str(ONE_CARD), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.replies: queue.Queue[bytes | None] = queue.Queue()
        # 落ちたときに理由を示せるよう、直近の標準エラーだけ持っておく。
        self.errors: collections.deque[str] = collections.deque(maxlen=40)
        self.used = False
        threading.Thread(target=self._read_replies, daemon=True).start()
        threading.Thread(target=self._read_errors, daemon=True).start()

    def _read_replies(self) -> None:
        for line in self.process.stdout:
            self.replies.put(line)
        # 標準出力が閉じた＝子が終わった。待っている側を起こす。
        self.replies.put(None)

    def _read_errors(self) -> None:
        for line in self.process.stderr:
            self.errors.append(line.decode("utf-8", "replace").rstrip())

    def alive(self) -> bool:
        return self.process.poll() is None

    def last_error(self) -> str:
        for line in reversed(self.errors):
            if line.strip():
                return line.strip()
        return f"終了コード {self.process.poll()}"

    def drain_errors_into_log(self, what: str) -> None:
        """溜まっている標準エラーを記録へ移す。移した分は捨てる。

        捨てないと、次に失敗したときに前回ぶんまで一緒に出て、どこからが
        今回なのか分からなくなる。
        """
        lines: list[str] = []
        while self.errors:
            lines.append(self.errors.popleft())
        if any(line.strip() for line in lines):
            _log_text(what, "\n".join(lines))

    def ask(self, mode: str, args: list[str]) -> dict:
        request = json.dumps({"mode": mode, "args": args}, ensure_ascii=False)
        try:
            self.process.stdin.write(request.encode("utf-8") + b"\n")
            self.process.stdin.flush()
        except OSError as exc:
            # 既に落ちている子への書き込み。`BrokenPipeError` とだけ出しても
            # 何も分からないので、子が最後に残した理由を添える。
            raise ChildFailed(f"子プロセスへ渡せませんでした（{self.last_error()}）") from exc

        # 最初の1枚だけは長めに待つ。EasyOCR のモデルの読み込みが入るため。
        limit = CHILD_TIMEOUT if self.used else FIRST_CALL_TIMEOUT
        self.used = True
        line = self.replies.get(timeout=limit)
        if line is None:
            raise ChildFailed(f"子プロセスが終了しました（{self.last_error()}）")
        # bytes のまま渡す（json は UTF-8 として読む）。ここで文字へ直すと、
        # 直し方を間違えたときに JSON の構文エラーとして出てきて原因が見えない。
        reply = json.loads(line)
        if not reply.get("ok"):
            # 画面に出せるのは1行だけ。全文は返事に入って届くので記録へ移す。
            detail = reply.get("traceback")
            if detail:
                _log_text(f"子プロセス（{mode}）", str(detail))
            raise ChildFailed(str(reply.get("error") or "理由が分かりませんでした"))
        return reply.get("result") or {}

    def stop(self) -> None:
        try:
            self.process.stdin.close()
        except Exception:  # noqa: BLE001 - 既に閉じている場合がある
            pass
        try:
            self.process.wait(timeout=5)
        except Exception:  # noqa: BLE001 - 応答しなければ待たない
            self.kill()

    def kill(self) -> None:
        try:
            self.process.kill()
            self.process.wait(timeout=5)
        except Exception:  # noqa: BLE001 - 後始末で本筋を止めない
            pass


_worker: _Worker | None = None

# 頼みごとを1件ずつ順に渡すための錠。**片付ける側はこれを待たない**。
# 待つ作りにすると、OCRの最中に Ctrl-C やウィンドウを閉じたときに、その1枚が
# 終わるまで（最長300秒）止まって見える。落とせば待っている側は
# 「子プロセスが終了しました」を受け取って進めるので、待つ理由がない。
_worker_lock = threading.Lock()


def _take_worker() -> _Worker | None:
    """いまの子を手放して返す。次に頼まれたときに作り直される。"""
    global _worker
    current, _worker = _worker, None
    return current


def stop_worker() -> None:
    """子プロセスを片付ける（終了時とテストの前後）。"""
    current = _take_worker()
    if current is not None:
        current.stop()


def kill_worker() -> None:
    """子プロセスを即座に落とす。C のライブラリが落ちた状態を作るのに使う。"""
    current = _take_worker()
    if current is not None:
        current.kill()


def worker_pid() -> int | None:
    """いま動いている子プロセスの番号。作り直されたかを見るのに使う。"""
    current = _worker
    return current.process.pid if current is not None and current.alive() else None


atexit.register(stop_worker)


def run_in_child(args: list[str]) -> dict:
    """PDFの描画とOCRを別プロセスで行う。子は1つを保ち続ける。

    実テスト（222枚）で、ラベル入力の画面が2度、途中で応答しなくなった。
    PDFの描画（pypdfium2）とOCR（tesseract）は C のライブラリを呼ぶため、
    ここが落ちるとプロセスごと消え、Python 側には何も残らない。同じ入口で
    動かしている限り、1枚で落ちるとそのあとの全部が止まる。別プロセスに
    出せば、落ちるのは子だけ。画面には「この1枚は失敗」と出て、次へ進める。

    はじめは1枚ごとに子を作り直していた。併用構成（EasyOCR + tesseract）を
    既定にしたあと、実測で**1枚あたり 1.4GB / 12秒**かかっている。毎回
    モデルを読み直すためで、先読みの裏方と重なると同時に2つ動く。実テストの
    5・6枚目でサーバーが応答しなくなったのは、これが原因の候補にあたる。

    子を1つ保てば、モデルの読み込みは1回で済み、同時に2つ動くこともない。
    落ちたら次の呼び出しで作り直すので、1枚だけ失敗して先へ進める点は同じ。
    """
    if not args:
        raise ChildFailed("指定がありません")
    mode, rest = args[0], [str(a) for a in args[1:]]

    # 1件ずつ順に渡す。同時に2枚を頼めないので、抱える画像も1枚分で済む。
    with _worker_lock:
        global _worker
        worker = _worker
        if worker is None or not worker.alive():
            if worker is not None:
                worker.kill()
            worker = _worker = _Worker()

        def drop() -> None:
            # 片付ける側は錠を待たないので、その間に別の子へ差し替わっていることが
            # ある。自分が使っていた子のときだけ手放す。
            global _worker
            if _worker is worker:
                _worker = None
            worker.kill()

        try:
            return worker.ask(mode, rest)
        except ChildFailed:
            # 子が落ちた場合は返事が来ないので、標準エラーに残ったものを拾う
            # （1枚ごとの失敗の traceback は返事に入って `ask` が記録済み）。
            if not worker.alive():
                worker.drain_errors_into_log(f"子プロセスが落ちました（{mode}）")
            # 1枚の失敗（ファイルが無いなど）で子を捨てない。生きているなら使い続ける。
            if not worker.alive():
                drop()
            raise
        except queue.Empty as exc:
            # 返事が来ない子は、あとから返してくる。次の名刺の返事として
            # 読み違えるので、ここで捨てる。
            drop()
            raise ChildFailed(f"{CHILD_TIMEOUT}秒たっても返事がありませんでした") from exc
        except Exception as exc:  # noqa: BLE001 - 経路そのものが壊れた場合
            drop()
            raise ChildFailed(f"{type(exc).__name__}: {exc}") from exc


def build_app(directory: Path, prefill: bool) -> FastAPI:
    app = FastAPI(title="正解ラベル入力", docs_url=None, redoc_url=None)

    # OCRは1枚あたり数秒かかるため、結果を覚えておき、次の分は裏で先に処理する。
    #
    # _running は「いま処理中のファイル」。これが無いと、先読みが終わる前に
    # 利用者がその名刺へ進んだとき、同じ画像を2回OCRしてしまう
    # （実測：3枚に対してOCRが4回走っていた）。CPUを二重に使うだけでなく、
    # 表示が出るまでの待ちも長くなる。
    # 覚えておく枚数の上限。1件あたりOCRの読み取り文字を丸ごと持つため、
    # 222枚を通すと積み上がる。行き来するのは前後数枚なので、これで足りる。
    CACHE_LIMIT = 40

    _ocr_cache: OrderedDict[str, tuple[dict[str, str], str | None, str]] = OrderedDict()
    _running: dict[str, threading.Event] = {}
    _cache_lock = threading.Lock()

    # 先読みは1本ずつ。実テストで、222枚を続けて進めている最中にサーバーが
    # 落ちた。先読みは押すたびにスレッドを最大2本立てる作りで、上限が無かった。
    # 1本あたり画像1枚（実測78MB）と tesseract のプロセスを抱えるため、
    # 速く進めるほど積み上がる。1本に絞れば、余分は多くても1枚分で済む。
    _warm_queue: queue.Queue[Path] = queue.Queue()
    _warm_started = threading.Event()

    def _remember(name: str, result: tuple[dict[str, str], str | None, str]) -> None:
        """結果を覚える。上限を超えたら古いものから捨てる。"""
        with _cache_lock:
            _ocr_cache[name] = result
            _ocr_cache.move_to_end(name)
            while len(_ocr_cache) > CACHE_LIMIT:
                _ocr_cache.popitem(last=False)

    def image_files() -> list[Path]:
        return sorted(
            p for p in directory.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        )

    def label_path(image: Path) -> Path:
        return image.with_suffix(".json")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return HTMLResponse(PAGE)

    @app.get("/api/files")
    def api_files() -> JSONResponse:
        rows = []
        for path in image_files():
            saved = label_path(path)
            rows.append({
                "name": path.name,
                "stem": path.stem,
                "labeled": saved.exists(),
            })
        return JSONResponse({
            "directory": str(directory),
            "version": _version(),
            "fields": [
                {"key": key, "label": LABELS[key], "hint": HINTS.get(key, "")}
                for key in FIELD_KEYS
            ],
            "files": rows,
            "prefill": prefill,
        })

    @app.get("/api/image/{name}")
    def api_image(name: str):
        path = directory / name
        if not path.is_file() or path.parent.resolve() != directory.resolve():
            return JSONResponse({"error": "見つかりません"}, status_code=404)
        if path.suffix.lower() in (".pdf", ".heic", ".tif", ".tiff"):
            # ブラウザが表示できない形式はJPEGに変換して返す。
            # 失敗しても壊れた画像アイコンだけを出さず、理由を返す
            # （実テストで1枚だけ画像が出ず、原因が分からない状態になった）。
            import tempfile

            from fastapi.responses import Response

            # 描画は子プロセスに任せる。ここが落ちてもサーバーは生き残る
            # （`run_in_child` の説明を参照）。1ページだけ読むのも子の側。
            _log_step(f"開始 画像の表示 {path.name}")
            with tempfile.TemporaryDirectory() as work:
                out = Path(work) / "page.jpg"
                try:
                    run_in_child(["image", str(path), str(out)])
                    data = out.read_bytes()
                except Exception as exc:  # noqa: BLE001 - 画面に理由を出すため握る
                    _log_failure(f"画像の表示（{path.name}）")
                    return JSONResponse(
                        {"error": f"画像を表示できません: {type(exc).__name__}: {exc}"},
                        status_code=415,
                    )
                finally:
                    _log_step(f"完了 画像の表示 {path.name}")
            return Response(content=data, media_type="image/jpeg")
        return FileResponse(path)

    @app.get("/api/label/{name}")
    def api_get_label(name: str, draft: str | None = None) -> JSONResponse:
        """下書きを返す。**ここから例外を出さない。**

        例外を出すと FastAPI が本文なしの 500 を返す。画面側はJSONとして
        読もうとして失敗し、「OCRの結果を取得できませんでした」という、
        原因の分からない文言だけが出る（実テストで発生）。

        理由が分からないと報告の往復になるので、何が起きても中身をJSONで
        返し、画面に理由をそのまま出す。
        """
        try:
            return _label_payload(name, draft)
        except Exception as exc:  # noqa: BLE001 - 画面に理由を出すため握る
            _log_failure(f"下書きの作成（{name}）")
            # ここは最後の受け皿なので、原因になりうるものに一切頼らない。
            # 空の辞書で返す（画面側は項目ごとに `|| ''` で受けている）。
            return JSONResponse({
                "values": {},
                "source": f"下書きを作れませんでした: {type(exc).__name__}: {exc}",
                "kind": "error",
                "prefilled": [],
                "ocr_text": "",
            })

    @app.get("/api/ocr-text/{name}")
    def api_ocr_text(name: str) -> JSONResponse:
        """OCRが読んだ文字だけを返す（保存済みの札を見直すとき用）。

        保存済みではOCRを走らせないため、画面の欄を開いたときにここへ来る。
        ここも例外を出さない。原因は本文に入れて返す（画面がJSONとして
        読めないと、何が起きたのか分からないまま報告の往復になる）。
        """
        try:
            _, error, ocr_text = _ocr_draft(directory / name)
        except Exception as exc:
            _log_failure(f"OCRが読んだ文字の取得（{name}）")
            return JSONResponse({"ocr_text": f"取得できませんでした: {type(exc).__name__}: {exc}"})
        return JSONResponse({"ocr_text": ocr_text or (error or "（読めた文字がありませんでした）")})

    def _label_payload(name: str, draft: str | None) -> JSONResponse:
        path = directory / name
        saved = label_path(path)
        if saved.exists():
            data = json.loads(saved.read_text(encoding="utf-8"))
            return JSONResponse({
                "values": {k: str(data.get(k, "") or "") for k in FIELD_KEYS},
                "source": "保存済み",
                "kind": "saved",
                "prefilled": [],
                # 保存済みではOCRを走らせない（戻るたびに数秒待たされるため）。
                # 読んだ文字は、画面で欄を開いたときに取りに行く。
                "ocr_text": "",
                "ocr_text_available": True,
            })

        use_draft = prefill if draft is None else (draft == "1")
        if not use_draft:
            return JSONResponse({
                "values": {key: "" for key in FIELD_KEYS},
                "source": "未入力",
                "kind": "empty",
                "prefilled": [],
            })

        values, error, ocr_text = _ocr_draft(path)
        _warm_next(name)
        if error:
            return JSONResponse({
                "values": {key: "" for key in FIELD_KEYS},
                "source": f"OCRを使えませんでした: {error}",
                "kind": "error",
                "prefilled": [],
                "ocr_text": "",
            })
        filled = [k for k, v in values.items() if v]
        return JSONResponse({
            "values": values,
            "source": "OCRの下書きです。黄色の欄は未確認です。画像と見比べて直してください。",
            "kind": "draft",
            "prefilled": filled,
            "ocr_text": ocr_text,
        })

    def _ocr_draft(path: Path) -> tuple[dict[str, str], str | None, str]:
        """OCRで下書きを作る。結果はファイルごとにキャッシュする。

        戻り値の3つ目は**OCRが読んだ文字そのもの**。項目が空のとき、
        読めていないのか取り出せていないのかは、これを見ないと切り分けられない。
        画面に出しておくことで、報告の往復を減らす。
        """
        while True:
            with _cache_lock:
                hit = _ocr_cache.get(path.name)
                if hit is not None:
                    return hit
                running = _running.get(path.name)
                if running is None:
                    # 自分が処理する。他は待つ
                    _running[path.name] = threading.Event()
                    break
            # 他が処理中。終わるまで待ってからキャッシュを見に戻る。
            # 待ち手が落ちても止まらないよう上限を置く（超えたら自分で処理し直す）。
            running.wait(timeout=180)

        # どの工程で落ちたかを残す。工程名が無いと、画像の読み込みなのか
        # OCRなのか切り分けられず、原因の報告だけで何往復もすることになる。
        step = "準備"
        # 落ちても手がかりが残るよう、**始める前に**書く（`_log_step` を参照）。
        _log_step(f"開始 OCR {path.name}")
        try:
            try:
                step = "OCR（別プロセス）"
                payload = run_in_child(["ocr", str(path)])
                values = {key: str(payload["fields"].get(key, "") or "") for key in FIELD_KEYS}
                result = (values, None, payload.get("text", ""))
            except Exception as exc:
                # 画面には要約しか出せないので、原因を追えるようにコンソールへ全文を出す
                _log_failure(f"{step}（{path.name}）")
                detail = str(exc) or exc.__class__.__name__
                # 失敗はキャッシュしない。一時的な失敗（メモリ不足、他プロセスとの
                # 競合など）を覚え込むと、原因を直しても画面を開き直すまで
                # 失敗したままになる。次に開いたときにやり直せるようにする。
                return {key: "" for key in FIELD_KEYS}, f"{step}で失敗（{detail}）", ""

            _remember(path.name, result)
            return result
        finally:
            _log_step(f"完了 OCR {path.name}")
            # 成功・失敗どちらでも待ち手を解放する。ここを漏らすと、
            # 待っている側が上限（180秒）まで固まる。
            with _cache_lock:
                finished = _running.pop(path.name, None)
            if finished is not None:
                finished.set()

    def _warm_worker() -> None:
        """並んだ先読みを1件ずつ片付ける。この裏方は1本しか立てない。"""
        while True:
            target = _warm_queue.get()
            try:
                _ocr_draft(target)
            except Exception:  # 先読みの失敗で止まらない
                _log_failure(f"先読み（{target.name}）")
            finally:
                _warm_queue.task_done()

    def _warm_next(name: str) -> None:
        """次の名刺のOCRを裏で先に済ませておく（1枚あたり数秒かかるため）。

        並べるだけで、実際に処理するのは1本の裏方。速く進めても積み上がらない。
        """
        if not _warm_started.is_set():
            _warm_started.set()
            threading.Thread(target=_warm_worker, daemon=True).start()

        names = [p.name for p in image_files()]
        if name not in names:
            return
        index = names.index(name)
        for nxt in names[index + 1 : index + 3]:
            with _cache_lock:
                if nxt in _ocr_cache:
                    continue
            # 押すのが速いと並びが伸びる。伸びたぶんは捨てる（先読みは
            # 速くするための仕掛けで、無くても動く）。
            if _warm_queue.qsize() >= 4:
                return
            _warm_queue.put(directory / nxt)

    @app.post("/api/label/{name}")
    async def api_save_label(name: str, request: Request) -> JSONResponse:
        path = directory / name
        if not path.is_file():
            return JSONResponse({"error": "見つかりません"}, status_code=404)
        payload = await request.json()
        values = {key: str(payload.get(key, "") or "").strip() for key in FIELD_KEYS}

        # OCRの下書きをそのまま採用した項目を記録する。
        # 精度を測るとき、正解がOCR由来だと数値が実際より良く出るため、
        # あとから「どれを人が確認したか」を追えるようにしておく。
        unverified = [k for k in payload.get("_unverified", []) if k in FIELD_KEYS]
        record: dict = dict(values)
        if unverified:
            record["_unverified"] = unverified
        label_path(path).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return JSONResponse({"ok": True, "unverified": len(unverified)})

    @app.delete("/api/label/{name}")
    def api_delete_label(name: str) -> JSONResponse:
        path = label_path(directory / name)
        if path.exists():
            path.unlink()
        return JSONResponse({"ok": True})

    @app.post("/api/inspect/{name}")
    def api_inspect(name: str) -> JSONResponse:
        """この1枚の読み取りをファイルに書き出す。

        実テストで、画面の写真から不具合を再現しようとして**何度も食い違った**。
        OCRが読んだ文字は目で書き写すには長く、`テ`と`了`、`一`と`ー`、`9`と`９`、
        `-`(ASCII) と `‐`(U+2010) のような1文字の違いがそのまま結果を変える。
        写真では区別が付かない。

        ファイルにして渡せるようにすれば、同じ文字で再現できる。
        """
        path = directory / name
        if not path.is_file() or path.parent.resolve() != directory.resolve():
            return JSONResponse({"error": "見つかりません"}, status_code=404)

        out = directory / f"読み取り-{path.name}.txt"
        try:
            values, error, ocr_text = _ocr_draft(path)
        except Exception as exc:  # noqa: BLE001 - 失敗も書き出す（それが手がかりになる）
            _log_failure(f"この1枚を調べる（{name}）")
            values, error, ocr_text = {}, f"{type(exc).__name__}: {exc}", ""

        lines = [
            f"名刺: {path.name}",
            f"版: {_version()}",
            "",
            "--- OCRが読んだ文字 ---",
            ocr_text or "（読めた文字がありませんでした）",
            "",
            "--- 取り出した項目 ---",
        ]
        if error:
            lines.append(f"失敗: {error}")
        for key in FIELD_KEYS:
            lines.append(f"{LABELS[key]}: {values.get(key, '')}")
        # UTF-8 で書く。cp932 では `ソ` などが壊れる（poc/one_card.py の emit を参照）。
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return JSONResponse({"ok": True, "path": str(out)})

    @app.post("/api/not-a-card/{name}")
    def api_not_a_card(name: str) -> JSONResponse:
        """名刺でないものを一覧から外す。

        仕分けは名刺と判定したファイルをこのフォルダへ**コピー**するため、
        取りこぼした領収書などは、仕分けをやり直しても残り続ける。
        入力する人が自分で外せないと、毎回その1枚から始まることになる。

        消さずに not-cards/ へ移す。仕分けの精度を測り直すときの材料になるため。
        """
        source = directory / name
        if not source.is_file() or source.parent.resolve() != directory.resolve():
            return JSONResponse({"error": "見つかりません"}, status_code=404)

        destination = directory / "not-cards"
        destination.mkdir(exist_ok=True)
        moved = []
        # 画像だけでなく、ラベルやOCRテキストなど同じ名前の付随ファイルもまとめて移す
        for sibling in sorted(directory.glob(f"{glob.escape(source.stem)}.*")):
            if not sibling.is_file():
                continue
            target = destination / sibling.name
            if target.exists():
                target.unlink()
            sibling.rename(target)
            moved.append(sibling.name)

        with _cache_lock:
            _ocr_cache.pop(name, None)
        return JSONResponse({"ok": True, "moved": moved, "to": str(destination)})

    return app


PAGE = """
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>正解ラベル入力</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, "Hiragino Sans", "Meiryo", sans-serif;
         background: #f4f5f7; color: #1a1a1a; }
  header { background: #1f5fa9; color: #fff; padding: 10px 16px; display: flex;
           align-items: center; gap: 16px; flex-wrap: wrap; position: sticky; top: 0; z-index: 10; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  .progress-text { font-size: 13px; opacity: .9; }
  .bar { flex: 1; min-width: 120px; height: 6px; background: rgba(255,255,255,.3); border-radius: 3px; }
  .bar > div { height: 100%; background: #7ec8ff; border-radius: 3px; width: 0; transition: width .2s; }
  main { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(360px, 480px);
         gap: 16px; padding: 16px; align-items: start; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  .panel { background: #fff; border: 1px solid #dfe3e8; border-radius: 8px; padding: 14px; }
  .imgwrap { position: sticky; top: 64px; }
  .imgwrap img { width: 100%; border: 1px solid #dfe3e8; border-radius: 6px; cursor: zoom-in; background:#fff; }
  .imgwrap img.zoom { position: fixed; inset: 8px; width: auto; height: auto;
                      max-width: calc(100vw - 16px); max-height: calc(100vh - 16px);
                      margin: auto; z-index: 100; cursor: zoom-out; box-shadow: 0 8px 40px rgba(0,0,0,.4); }
  .filename { font-size: 13px; color: #555; margin: 0 0 8px; word-break: break-all; }
  .ocrbox { margin-top: 10px; font-size: 13px; }
  .ocrbox summary { cursor: pointer; color: #555; }
  .ocrbox pre { background: #f6f7f9; border: 1px solid #e0e3e8; border-radius: 4px;
                padding: 8px; margin: 6px 0 0; max-height: 260px; overflow: auto;
                white-space: pre-wrap; word-break: break-all; font-size: 12px; }
  .imgerror:empty { display: none; }
  .imgerror { font-size: 13px; padding: 8px 10px; border-radius: 4px; margin: 8px 0;
              background: #fff4e5; border: 1px solid #ffd8a8; color: #8a5300; }
  .source { font-size: 12px; padding: 6px 8px; border-radius: 4px; margin-bottom: 10px; }
  /* 下書き中は文を出さない。空の帯だけが残らないようにする */
  .source:empty { display: none; }
  .source.warn { background: #fff4e5; border: 1px solid #ffd8a8; color: #8a5300; }
  .source.plain { background: #f0f2f5; color: #555; }
  /* OCRの下書き中は、文で伝えるより動いているものを見せるほうが分かりやすい。
     文字は秒数だけにして、進んでいるかどうかはバーの動きで示す。
     どこまで進んだかは分からないため、割合ではなく往復するバーにする。 */
  .ocrbar { position: relative; height: 22px; border-radius: 4px; margin-bottom: 10px;
            background: #e4e7ec; overflow: hidden; }
  .ocrbar::before { content: ''; position: absolute; top: 0; bottom: 0; width: 40%;
                    background: linear-gradient(90deg, #1a73e8aa, #1a73e8);
                    border-radius: 4px; animation: ocrslide 1.1s ease-in-out infinite; }
  .ocrbar span { position: absolute; inset: 0; display: flex; align-items: center;
                 justify-content: center; font-size: 12px; font-weight: 700;
                 color: #10305c; font-variant-numeric: tabular-nums; }
  @keyframes ocrslide { 0% { left: -40%; } 100% { left: 100%; } }
  @media (prefers-reduced-motion: reduce) {
    .ocrbar::before { animation-duration: 3s; }
  }
  .ocrslow { font-size: 12px; color: #8a5300; margin: -4px 0 10px; }
  .ocrslow:empty { display: none; }
  .field { margin-bottom: 10px; }
  .field label { display: block; font-size: 12px; color: #444; margin-bottom: 3px; font-weight: 600; }
  .field input { width: 100%; padding: 7px 9px; font-size: 14px; border: 1px solid #c8ccd4;
                 border-radius: 4px; font-family: inherit; }
  .field input:focus { outline: 2px solid #1f5fa9; outline-offset: -1px; border-color: #1f5fa9; }
  .field input.draft { background: #fff8e1; border-color: #e0b64a; }
  .field.unverified label::after { content: " 未確認"; color: #8a5300; font-weight: 400; }
  .toggle { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #fff; }
  .toggle input { width: auto; }
  .field .hint { font-size: 11px; color: #888; margin-top: 2px; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  /* 入力欄が14項目あるため、操作ボタンは下端に貼り付けて常に見えるようにする。
     以前は最下部にあり、スクロールしないと見えなかった。 */
  .actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; align-items: center;
             position: sticky; bottom: 0; background: #fff; padding: 10px 0;
             border-top: 1px solid #e3e5e8; z-index: 5; }
  .notcard-row { margin: 12px 0 0; }
  .notcard-row button { font-size: 12px; color: #8a4b00; border-color: #e0c49a; background: #fff8ef; }
  .notcard-row button:hover { background: #f6e7d2; }
  button { padding: 9px 14px; font-size: 14px; border-radius: 5px; border: 1px solid #c8ccd4;
           background: #fff; cursor: pointer; font-family: inherit; }
  button.primary { background: #1f5fa9; color: #fff; border-color: #1f5fa9; font-weight: 600; }
  button:disabled { opacity: .45; cursor: default; }
  .files { max-height: 260px; overflow-y: auto; border: 1px solid #dfe3e8; border-radius: 6px; }
  .files button { display: block; width: 100%; text-align: left; border: 0; border-bottom: 1px solid #eef0f3;
                  border-radius: 0; padding: 7px 10px; font-size: 13px; background: #fff; }
  .files button.current { background: #e8f1fb; font-weight: 600; }
  .files button .tick { color: #2f855a; margin-right: 5px; }
  .files button .todo { color: #bbb; margin-right: 5px; }
  .saved { font-size: 13px; color: #2f855a; }
  .kbd { font-size: 11px; color: #666; margin-top: 10px; line-height: 1.7; }
  .kbd code { background: #eef0f3; padding: 1px 5px; border-radius: 3px; }
</style>
</head>
<body>
<header>
  <h1>正解ラベル入力</h1>
  <span class="progress-text" id="progress">読み込み中…</span>
  <div class="bar"><div id="bar"></div></div>
  <label class="toggle"><input type="checkbox" id="draft"> OCRで下書きする</label>
  <span class="progress-text" id="version" title="この画面の版。更新したのに変わらなければ、取得できていません"></span>
</header>
<main>
  <div>
    <div class="panel imgwrap">
      <p class="filename" id="filename">—</p>
      <img id="image" alt="名刺画像" onclick="this.classList.toggle('zoom')"
           onerror="showImageError()">
      <div id="imgerror" class="imgerror"></div>
      <details id="ocrbox" class="ocrbox">
        <summary>OCRが読んだ文字を見る（項目が空のときの手がかり）</summary>
        <pre id="ocrtext"></pre>
      </details>
      <p class="kbd">画像をクリックすると拡大します。</p>
      <!-- 「名刺ではない」は画像を見た時点で判断するので、画像のすぐ下に置く。
           入力欄の下（14項目ぶん下）だと画面外で気づけない。 -->
      <p class="notcard-row">
        <button type="button" id="notcard">これは名刺ではない（一覧から外す）</button>
        <!-- 項目がおかしいときに、その1枚の読み取りをそのまま渡せるようにする。
             画面の写真では `テ`と`了`、`9`と`９` の違いが分からず、
             再現しようとして何度も食い違った。 -->
        <button type="button" id="inspect">この1枚を調べる（読み取りを書き出す）</button>
      </p>
      <p class="kbd" id="inspected"></p>
    </div>
  </div>
  <div>
    <div class="panel">
      <div class="source plain" id="source">—</div>
      <div class="ocrbar" id="ocrbar" hidden><span id="ocrsec"></span></div>
      <div class="ocrslow" id="ocrslow"></div>
      <form id="form" autocomplete="off"></form>
      <div class="actions">
        <button type="button" id="prev">← 前へ</button>
        <button type="button" class="primary" id="next">保存して次へ →</button>
        <button type="button" id="skip">スキップ</button>
        <span class="saved" id="saved"></span>
        <span class="small muted" id="unverified"></span>
      </div>
      <p class="kbd">
        <code>Ctrl</code>+<code>Enter</code> 保存して次へ ／
        <code>Alt</code>+<code>←</code> <code>→</code> 前後の名刺へ<br>
        記載の無い項目は空欄のままにしてください（空欄も正解として扱われます）。
      </p>
    </div>
    <div class="panel" style="margin-top:16px">
      <div class="files" id="files"></div>
    </div>
  </div>
</main>
<script>
let state = { files: [], fields: [], index: 0, prefill: false, unverified: new Set(), timer: null };

async function boot() {
  const meta = await (await fetch('/api/files')).json();
  state.fields = meta.fields;
  state.files = meta.files;
  state.prefill = meta.prefill;
  document.getElementById('version').textContent = '版 ' + (meta.version || '不明');
  const draftBox = document.getElementById('draft');
  draftBox.checked = meta.prefill;
  draftBox.onchange = () => show(state.index);
  if (!state.files.length) {
    document.getElementById('progress').textContent = '画像が見つかりません: ' + meta.directory;
    return;
  }
  buildForm();
  const firstTodo = state.files.findIndex(f => !f.labeled);
  state.index = firstTodo >= 0 ? firstTodo : 0;
  await show(state.index);
}

function buildForm() {
  const form = document.getElementById('form');
  const pairs = [['last_name','first_name'], ['last_name_kana','first_name_kana']];
  const paired = new Set(pairs.flat());
  let html = '';
  for (const [a, b] of pairs) {
    html += '<div class="row2">' + [a, b].map(k => fieldHtml(k)).join('') + '</div>';
  }
  for (const f of state.fields) {
    if (!paired.has(f.key)) html += fieldHtml(f.key);
  }
  form.innerHTML = html;
}

function fieldHtml(key) {
  const f = state.fields.find(x => x.key === key);
  return `<div class="field">
    <label for="f_${f.key}">${f.label}</label>
    <input id="f_${f.key}" name="${f.key}" type="text"
           oninput="confirmField('${f.key}')" onfocus="confirmField('${f.key}')">
    ${f.hint ? `<div class="hint">${f.hint}</div>` : ''}
  </div>`;
}

// 画像が出せないときは、壊れたアイコンではなく理由を出す。
//
// 「この1枚だけの問題」と決めつけないこと。サーバーが落ちていると以降の名刺も
// すべて画像が出ないが、実テストではその場合も「この1枚だけ」と表示していたため、
// 原因を1枚目のファイルだと見誤ることになった。両者を区別して出す。
async function showImageError() {
  const box = document.getElementById('imgerror');
  const file = state.files[state.index];
  box.textContent = '画像を表示できません。原因を調べています…';

  let reason = null;
  try {
    const res = await fetch('/api/image/' + encodeURIComponent(file.name));
    const body = await res.json();
    if (body && body.error) reason = body.error;
  } catch (e) { /* サーバーが応答していない可能性。下で確かめる */ }

  if (reason) {
    box.textContent = reason + '（この1枚だけの問題です。入力は続けられます）';
    return;
  }

  try {
    const alive = await fetch('/api/files', { cache: 'no-store' });
    if (alive.ok) {
      box.textContent = '画像を表示できません（この1枚だけの問題です。入力は続けられます）';
      return;
    }
  } catch (e) { /* 落ちている */ }

  box.innerHTML = '<b>サーバーが応答していません。</b>'
    + 'このあとの名刺もすべて画像が出ません。'
    + '「ラベル付けを始める」の黒い画面を閉じて、もう一度開いてください。'
    + '（黒い画面の最後の行が原因の手がかりです）';
}

async function show(i) {
  state.index = i;
  const file = state.files[i];
  document.getElementById('filename').textContent = file.name;
  document.getElementById('imgerror').textContent = '';
  document.getElementById('ocrtext').textContent = '';
  document.getElementById('image').src = '/api/image/' + encodeURIComponent(file.name);
  document.getElementById('image').classList.remove('zoom');
  document.getElementById('saved').textContent = '';
  clearMarks();

  // 前の名刺の値を消してから読み込む。消さないと、OCRを待っている間に
  // 前の名刺の値が入ったままになり、そのまま保存できてしまう（実テストで発生）。
  for (const f of state.fields) {
    const input = document.getElementById('f_' + f.key);
    if (input) input.value = '';
  }
  // 待たせるのは「保存して次へ」だけ。スキップと「前へ」はOCRの結果に
  // 関係がないので、いつでも押せるようにしておく（OCRが返ってこないときに
  // 先へ進めなくなり、実テストで手が止まった）。
  document.getElementById('next').disabled = true;

  // 枚数・進捗・一覧はOCRの結果に依らないので、待たずに先に出す。
  // 以前はOCRのあとに描いていたため、数秒間ヘッダが「読み込み中…」のままだった。
  document.getElementById('prev').disabled = i === 0;
  renderProgress();
  renderFiles();

  const useDraft = document.getElementById('draft').checked ? '1' : '0';
  const src = document.getElementById('source');
  src.textContent = '';
  src.className = 'source plain';

  // 下書き中は、文ではなくバーで見せる。止まっているのか動いているのかが
  // 一目で分かればよく、読ませる必要はない。バーの中の文字は秒数だけにする。
  // 20秒を超えたときだけ、待たずに進められることをバーの下に添える。
  if (state.timer) clearInterval(state.timer);
  showBar(useDraft === '1' ? 0 : null);
  if (useDraft === '1') {
    const started = Date.now();
    state.timer = setInterval(() => {
      if (state.index !== i) { clearInterval(state.timer); return; }
      showBar(Math.round((Date.now() - started) / 1000));
    }, 1000);
  }

  const url = '/api/label/' + encodeURIComponent(file.name) + '?draft=' + useDraft;
  let data;
  try {
    data = await (await fetch(url)).json();
  } catch (e) {
    // 取れなくても手を止めない。空欄のまま入力できるようにする
    if (state.index !== i) return;
    if (state.timer) clearInterval(state.timer);
    showBar(null);
    document.getElementById('next').disabled = false;
    src.textContent = 'OCRの結果を取得できませんでした。空欄から入力してください。';
    src.className = 'source warn';
    return;
  }
  if (state.index !== i) return;   // 待っている間に別の名刺へ移った
  document.getElementById('next').disabled = false;

  for (const f of state.fields) {
    document.getElementById('f_' + f.key).value = data.values[f.key] || '';
  }
  // OCRが入れた欄は「未確認」として色を付ける。触れば消える
  state.unverified = new Set(data.prefilled || []);
  for (const key of state.unverified) mark(key, true);

  if (state.timer) clearInterval(state.timer);
  showBar(null);
  // 下書きなら本文が既に来ている。保存済みは走らせていないので、
  // 欄を開いたときに取りに行く（戻るたびに数秒待たされないように）。
  state.ocrLoaded = !data.ocr_text_available;
  document.getElementById('ocrtext').textContent =
      data.ocr_text || (data.ocr_text_available ? '' : '（読めた文字がありませんでした）');
  document.getElementById('ocrbox').open = false;
  src.textContent = data.source;
  src.className = 'source ' + (data.kind === 'draft' || data.kind === 'error' ? 'warn' : 'plain');

  renderProgress();
  renderFiles();
  renderUnverified();
  const first = document.getElementById('f_' + state.fields[0].key);
  if (first) first.focus();
}

// OCRの下書き中を示すバー。seconds に数値を渡すと出し、null で消す。
// バーの中に出すのは秒数だけにする（動いていることはバー自体が示す）。
function showBar(seconds) {
  const bar = document.getElementById('ocrbar');
  const slow = document.getElementById('ocrslow');
  if (seconds === null) {
    bar.hidden = true;
    slow.textContent = '';
    return;
  }
  bar.hidden = false;
  document.getElementById('ocrsec').textContent = seconds + '秒';
  // 20秒を超えたら、待たずに進められることだけ添える。バーの外に出すのは、
  // 中を秒数だけにしておくため（実テストで、長い文だと読み飛ばされた）。
  slow.textContent = seconds >= 20
    ? '時間がかかっています。「スキップ」で次へ進めます。'
    : '';
}

function mark(key, on) {
  const input = document.getElementById('f_' + key);
  if (!input) return;
  input.classList.toggle('draft', on);
  input.closest('.field').classList.toggle('unverified', on);
}

function clearMarks() {
  for (const f of state.fields) mark(f.key, false);
  state.unverified = new Set();
}

function confirmField(key) {
  if (!state.unverified.has(key)) return;
  state.unverified.delete(key);
  mark(key, false);
  renderUnverified();
}

function renderUnverified() {
  const n = state.unverified.size;
  document.getElementById('unverified').textContent =
    n ? `未確認 ${n} 項目（黄色の欄）` : '';
}

function renderProgress() {
  const done = state.files.filter(f => f.labeled).length;
  document.getElementById('progress').textContent =
    `${state.index + 1} / ${state.files.length} 枚目　（入力済み ${done} 枚）`;
  document.getElementById('bar').style.width = (done / state.files.length * 100) + '%';
}

function renderFiles() {
  document.getElementById('files').innerHTML = state.files.map((f, i) =>
    `<button type="button" onclick="show(${i})" class="${i === state.index ? 'current' : ''}">
       <span class="${f.labeled ? 'tick' : 'todo'}">${f.labeled ? '✓' : '○'}</span>${f.name}
     </button>`).join('');
}

async function save() {
  const file = state.files[state.index];
  const body = { _unverified: [...state.unverified] };
  for (const f of state.fields) body[f.key] = document.getElementById('f_' + f.key).value;
  await fetch('/api/label/' + encodeURIComponent(file.name), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  file.labeled = true;
  document.getElementById('saved').textContent = '保存しました';
  renderProgress();
  renderFiles();
}

async function saveAndNext() {
  await save();
  if (state.index < state.files.length - 1) await show(state.index + 1);
  else document.getElementById('saved').textContent = 'すべて入力しました';
}

document.getElementById('next').onclick = saveAndNext;
document.getElementById('prev').onclick = () => show(Math.max(0, state.index - 1));
document.getElementById('skip').onclick = () => {
  if (state.index < state.files.length - 1) show(state.index + 1);
};
// 仕分けが取りこぼした領収書などを一覧から外す。消さずに not-cards/ へ移す。
document.getElementById('notcard').onclick = async () => {
  const file = state.files[state.index];
  if (!confirm(file.name + ' を「名刺ではない」として一覧から外します。\\n\\n'
             + 'ファイルは消さず、not-cards フォルダへ移します。')) return;
  const res = await fetch('/api/not-a-card/' + encodeURIComponent(file.name), {method: 'POST'});
  if (!res.ok) { alert('外せませんでした。'); return; }
  const at = state.index;
  const meta = await (await fetch('/api/files')).json();
  state.files = meta.files;
  if (!state.files.length) {
    document.getElementById('progress').textContent = '画像が残っていません';
    return;
  }
  await show(Math.min(at, state.files.length - 1));
  document.getElementById('saved').textContent = '一覧から外しました';
};
// この1枚の読み取りをファイルに書き出す。項目がおかしいときの報告に使う。
document.getElementById('inspect').onclick = async () => {
  const file = state.files[state.index];
  const note = document.getElementById('inspected');
  note.textContent = 'OCRで読んでいます…';
  try {
    const res = await fetch('/api/inspect/' + encodeURIComponent(file.name), {method: 'POST'});
    const data = await res.json();
    note.textContent = data.path
      ? '書き出しました: ' + data.path + '　このファイルを送ってください。'
      : '書き出せませんでした: ' + (data.error || '');
  } catch (err) {
    note.textContent = '書き出せませんでした: ' + err;
  }
};
// 保存済みの札は下書きを作っていないので、欄を開いたときにだけ読みに行く。
// 保存した値の誤りに気づいたとき、何をどう読み違えたのかを見るための欄。
document.getElementById('ocrbox').addEventListener('toggle', async (e) => {
  if (!e.target.open || state.ocrLoaded) return;
  state.ocrLoaded = true;
  const pre = document.getElementById('ocrtext');
  pre.textContent = 'OCRで読んでいます…';
  const name = state.files[state.index].name;
  try {
    const res = await fetch('/api/ocr-text/' + encodeURIComponent(name));
    const data = await res.json();
    // 待っているあいだに別の名刺へ移っていたら、その結果は捨てる
    if (state.files[state.index].name !== name) return;
    pre.textContent = data.ocr_text || '（読めた文字がありませんでした）';
  } catch (err) {
    state.ocrLoaded = false;
    pre.textContent = '取得できませんでした: ' + err;
  }
});
document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); saveAndNext(); }
  if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); if (state.index < state.files.length - 1) show(state.index + 1); }
  if (e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); if (state.index > 0) show(state.index - 1); }
});
boot();
</script>
</body>
</html>
"""


def main() -> int:
    # 前回の記録を先に知らせる（有効にすると追記で混ざるため、その前に読む）。
    report_last_crash()
    # いちばん先に有効にする。落ちるのは重い処理の最中とは限らない。
    enable_crash_report()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", help="名刺画像の入っているフォルダ")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument(
        "--no-prefill",
        action="store_true",
        help="OCRの下書きを使わず、空欄から入力する（測定用の正解を厳密に作る場合）",
    )
    parser.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    args = parser.parse_args()

    directory = Path(args.directory).expanduser().resolve()
    if not directory.is_dir():
        print(f"フォルダが見つかりません: {directory}", file=sys.stderr)
        return 2

    images = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    if not images:
        print(f"画像が見つかりません: {directory}", file=sys.stderr)
        return 2

    labeled = sum(1 for p in images if p.with_suffix(".json").exists())
    print(f"対象: {directory}")
    print(f"画像 {len(images)} 枚（入力済み {labeled} 枚 / 残り {len(images) - labeled} 枚）")
    if args.no_prefill:
        print("\n--no-prefill 指定：空欄から入力します。\n")
    else:
        print("\nOCRが下書きを入れます。黄色い欄は「未確認」です。")
        print("  画像と見比べて直してください。触れば色が消えます。")
        print("  下書きを使わずに入力する場合は --no-prefill を付けてください。\n")
    url = f"http://127.0.0.1:{args.port}/"
    print(f"\n入力画面: {url}")
    print("終了するには、この画面で Ctrl-C を押すか、ウィンドウを閉じてください。")

    if not args.no_browser:
        # サーバーが起動してから開く。起動前に開くと「接続できません」になる
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # 先に自分で束縛して、使えないポートならここで分かりやすく知らせる。
    # uvicorn に任せると内部で捕捉されてしまい、原因が伝わりにくい。
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", args.port))
    except OSError as exc:
        print(
            f"\nポート {args.port} は使用中です（{exc}）。\n"
            f"  すでに入力画面が起動していませんか。その場合はブラウザで {url} を開いてください。\n"
            f"  別のポートを使うなら --port 8101 のように指定します。",
            file=sys.stderr,
        )
        return 1
    finally:
        probe.close()

    import uvicorn

    uvicorn.run(
        build_app(directory, not args.no_prefill),
        host="127.0.0.1", port=args.port, log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

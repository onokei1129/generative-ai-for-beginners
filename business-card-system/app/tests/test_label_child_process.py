"""重い処理を別プロセスで行う（poc/one_card.py, poc/label.py）。

実テスト（222枚）で、ラベル入力の画面が**2度**、途中で応答しなくなった。
画像が壊れたアイコンになり、下書きも止まったままになる。

PDFの描画（pypdfium2）とOCR（tesseract）は C のライブラリを呼ぶ。ここが
落ちるとプロセスごと消えるため、Python 側には例外も traceback も残らない。
同じ入口で動かしている限り、1枚の名刺で落ちると**そのあとの全部が止まる**。

別プロセスに出せば、落ちるのは子だけで済む。画面には「この1枚は失敗」と
出て、次の名刺へ進める。1枚ごとに子が終わるので、抱えた画像も確実に解放
される。

ここでは子プロセスを**実際に動かして**確かめる。中身を読むだけでは、
落ちたときに親が生き残るかどうかは分からない。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
ONE_CARD = APP / "poc" / "one_card.py"
LABEL = APP / "poc" / "label.py"

sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))


def run(*args: str, encoding: str | None = None) -> subprocess.CompletedProcess[bytes]:
    """`encoding` を渡すと、子の画面の文字コードをその名前で動かす。

    Windows の日本語環境（cp932）を、この環境から再現するために使う。
    """
    env = dict(os.environ)
    if encoding is not None:
        env["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [sys.executable, str(ONE_CARD), *args],
        capture_output=True,
        timeout=180,
        env=env,
    )


@pytest.fixture(scope="module")
def card(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """名刺くらいの大きさの画像を1枚。中身は問わない。

    ここで確かめるのは受け渡し——子がJSONを返し、親が読めること。テストの
    OCRは mock なので、何が描いてあっても結果は同じになる。日本語フォントの
    要る合成サンプルを使うと、フォントの無い環境（CI）で作れずに落ちる。
    """
    from PIL import Image

    path = tmp_path_factory.mktemp("cards") / "card.png"
    Image.new("RGB", (1050, 640), "white").save(path)
    return path


class TestTheChildDoesTheWork:
    def test_ocr_returns_every_field_as_json(self, card: Path):
        """どのOCRを使うかはここでは問わない（テストは mock で走る）。

        確かめるのは受け渡し——子が結果をJSONで返し、親が読めること。
        """
        from poc.samples import FIELD_KEYS

        done = run("ocr", str(card))

        assert done.returncode == 0
        payload = json.loads(done.stdout.decode("utf-8"))
        assert set(FIELD_KEYS) <= set(payload["fields"])

    def test_something_is_actually_extracted(self, card: Path):
        payload = json.loads(run("ocr", str(card)).stdout.decode("utf-8"))

        assert any(value for value in payload["fields"].values())

    def test_ocr_returns_the_text_it_read(self, card: Path):
        """項目が空のとき、読めていないのか取り出せていないのかの切り分けに要る。"""
        payload = json.loads(run("ocr", str(card)).stdout.decode("utf-8"))

        assert payload["text"].strip()

    def test_image_writes_a_jpeg(self, card: Path, tmp_path: Path):
        out = tmp_path / "page.jpg"

        assert run("image", str(card), str(out)).returncode == 0
        assert out.read_bytes()[:2] == b"\xff\xd8"  # JPEG の先頭


class TestTheChildAlwaysSpeaksUtf8:
    """画面の文字コードに関わらず、結果は UTF-8 で返すこと。

    実テストで、姓が「ソ」の1枚（`(会社名)_ユンソめ ン.pdf`）の下書きが
    こう出て失敗した:

        OCR（別プロセス）で失敗（Expecting ',' delimiter: line 1 column 33 (char 32)）

    子は `sys.stdout` へ**文字として**書いていた。そこは画面の文字コードで
    書かれるため、Windows の日本語環境では cp932 になる。cp932 の「ソ」は
    0x83 0x5C で、2バイト目が円記号（UTF-8 では \\）。親は UTF-8 として
    読むので、この \\ が直後の引用符を打ち消し、文字列が閉じなくなる。

    「ソ」に限った話ではない。cp932 のバイト列は UTF-8 として読めないため、
    **日本語の項目が取れた名刺ほど失敗する**。別プロセスに出した時点で
    持ち込んだ不具合で、それまでは同じプロセス内で受け渡していた。

    ここでは cp932 を明示して子を動かし、それでも壊れないことを確かめる。
    """

    def test_the_output_is_utf8_even_on_a_cp932_console(self, card: Path):
        done = run("ocr", str(card), encoding="cp932")

        assert done.returncode == 0
        done.stdout.decode("utf-8")  # 置き換えなし。壊れていれば例外

    def test_the_draft_still_parses_on_a_cp932_console(self, card: Path):
        """親と同じ読み方（bytes をそのまま json へ）で確かめる。"""
        payload = json.loads(run("ocr", str(card), encoding="cp932").stdout)

        assert payload["fields"]

    def test_japanese_comes_back_unchanged(self, card: Path):
        """文字化けは「読めた」で通ってしまうため、中身まで比べる。"""
        plain = json.loads(run("ocr", str(card)).stdout)
        cp932 = json.loads(run("ocr", str(card), encoding="cp932").stdout)

        assert cp932 == plain

    def test_the_troublesome_character_survives(self):
        """姓が「ソ」の値をそのまま書かせて往復させる。

        実際に壊れた文字をそのまま置く。画像は要らない——壊れるのは
        受け渡しの側なので、書き出しだけを cp932 の画面で動かす。
        """
        code = (
            f"import sys; sys.path.insert(0, {str(APP)!r});"
            "from poc.one_card import emit;"
            "emit({'fields': {'last_name': 'ソ'}})"
        )
        done = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "cp932"},
        )

        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        assert json.loads(done.stdout)["fields"]["last_name"] == "ソ"

    def test_the_result_never_goes_through_the_text_layer(self):
        """`sys.stdout` へ文字で書く形に戻らないこと（戻ると不具合も戻る）。"""
        source = (APP / "poc" / "one_card.py").read_text(encoding="utf-8")

        assert "sys.stdout.buffer.write" in source
        assert "json.dump(" not in source  # json.dumps(...).encode(...) を使う


class TestAFailureIsReportedNotSwallowed:
    def test_a_missing_file_fails_with_a_reason(self, tmp_path: Path):
        done = run("ocr", str(tmp_path / "none.png"))

        assert done.returncode != 0
        assert b"FileNotFoundError" in done.stderr

    @pytest.mark.parametrize("args", [(), ("ocr",), ("image", "x.png"), ("なにか", "x")])
    def test_a_wrong_call_does_not_look_like_success(self, args: tuple[str, ...]):
        assert run(*args).returncode != 0


class TestTheScreenOnlyCallsTheChild:
    """画面側が自分で重い処理をしないこと。ここが戻ると不具合も戻る。"""

    def source(self) -> str:
        return LABEL.read_text(encoding="utf-8")

    @pytest.mark.parametrize("call", ["run_in_child([\"ocr\"", "run_in_child([\"image\""])
    def test_both_paths_go_through_the_child(self, call: str):
        assert call.replace('"', '"') in self.source()

    @pytest.mark.parametrize("name", ["process_file(", "recognize_card(", "load_pages("])
    def test_the_heavy_work_is_not_done_in_process(self, name: str):
        assert name not in self.source()

    def test_the_child_is_run_with_the_same_python(self):
        """venv の外の python を呼ぶと、必要な部品が入っていない。"""
        assert "[sys.executable, str(ONE_CARD), *args]" in self.source()

    def test_there_is_a_time_limit(self):
        """待ち続けるより、空欄にして次へ進めるほうがよい。"""
        text = self.source()

        assert "CHILD_TIMEOUT = 120" in text
        assert "timeout=CHILD_TIMEOUT" in text

    def test_the_exit_code_reaches_the_screen(self):
        """落ちた理由が分かるよう、終了コードと標準エラーを添えること。"""
        text = self.source()

        assert "class ChildFailed(RuntimeError):" in text
        assert "終了コード" in text

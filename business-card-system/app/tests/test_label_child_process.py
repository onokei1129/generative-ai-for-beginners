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
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
ONE_CARD = APP / "poc" / "one_card.py"
LABEL = APP / "poc" / "label.py"

sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))


def run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(ONE_CARD), *args], capture_output=True, timeout=180
    )


@pytest.fixture(scope="module")
def card(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from poc.samples import build_samples

    path = tmp_path_factory.mktemp("cards") / "card.png"
    build_samples()[0].image.save(path)
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

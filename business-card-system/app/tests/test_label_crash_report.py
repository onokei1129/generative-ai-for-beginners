"""落ちた瞬間を記録に残す（poc/label.py, poc/one_card.py）。

実テストで、ラベル入力のサーバーが**応答しなくなる**。5・6枚目、そのあと
8枚目、さらに「前へ」で戻ったときにも起きた。子プロセスを1つ保つ形にしても
直らず、記録は空のまま終わっていた。

## なぜ記録が空になるのか

Python の例外なら `_log_failure` が拾える。しかし **C のライブラリが落ちると
プロセスはその場で消える**ため、`except` も `finally` も通らない。
PDFの描画（pypdfium2）・OCR（tesseract）・EasyOCR（PyTorch）はどれも C を
呼ぶので、ここが落ちると Python 側には何も残らない。

黒い画面にも出ない（閉じれば消える）。**手がかりが1つも無い状態**だった。

## faulthandler

Python にはこのための仕組みがある。有効にしておくと、アクセス違反などで
落ちた瞬間の位置をファイルへ書く。ここでしか得られない情報なので、
親（サーバー）と子（重い処理）の両方で有効にする。

ファイルは開いたまま持っておくこと。閉じると `faulthandler` が無効になる。
"""

from __future__ import annotations

import faulthandler
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402


class TestTheServerRecordsACrash:
    def test_it_is_enabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(label, "CRASH_PATH", tmp_path / "落ちた記録.txt")

        label.enable_crash_report()

        assert faulthandler.is_enabled()

    def test_the_file_is_opened(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        path = tmp_path / "落ちた記録.txt"
        monkeypatch.setattr(label, "CRASH_PATH", path)

        label.enable_crash_report()

        assert path.exists()

    def test_calling_it_twice_is_safe(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(label, "CRASH_PATH", tmp_path / "落ちた記録.txt")

        label.enable_crash_report()
        label.enable_crash_report()

        assert faulthandler.is_enabled()

    def test_a_place_it_cannot_write_does_not_stop_the_server(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """記録は手がかりであって目的ではない。書けなくても起動を止めない。"""
        monkeypatch.setattr(label, "CRASH_PATH", Path("/ない/場所/落ちた記録.txt"))

        label.enable_crash_report()  # 例外を出さないこと


class TestTheServerActuallyWritesOnACrash:
    def test_a_hard_crash_leaves_the_place_in_the_file(self, tmp_path: Path):
        """本当に書かれるかを、別プロセスをわざと落として確かめる。

        `faulthandler` を信じるだけでは足りない。実際に落として、ファイルに
        残ることを見る（これが残らなければ、この仕掛けを入れる意味がない）。
        """
        out = tmp_path / "落ちた記録.txt"
        code = (
            "import faulthandler, sys;"
            f"handle = open({str(out)!r}, 'a', encoding='utf-8');"
            "faulthandler.enable(file=handle, all_threads=True);"
            "faulthandler._sigsegv()"
        )
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=60)

        assert done.returncode != 0
        assert "Segmentation fault" in out.read_text(encoding="utf-8")


class TestTheChildRecordsToo:
    def test_the_child_enables_it(self):
        """子は標準エラーへ書く。親が読んで記録へ移す。"""
        source = (APP / "poc" / "one_card.py").read_text(encoding="utf-8")

        assert "faulthandler" in source
        assert "faulthandler.enable(" in source


class TestTheNextStartTellsYou:
    """落ちたあと、どこを見ればよいかが分かること。

    利用者は「サーバーが応答していません」を見て黒い画面を開き直す。その
    ときに記録の在り処を出しておかないと、せっかく残した手がかりが読まれない。
    """

    def test_it_says_so_when_a_record_exists(self, tmp_path: Path, capsys, monkeypatch):
        path = tmp_path / "落ちた記録.txt"
        path.write_text("Fatal Python error: Segmentation fault\n", encoding="utf-8")
        monkeypatch.setattr(label, "CRASH_PATH", path)

        label.report_last_crash()

        assert "落ちた記録" in capsys.readouterr().out

    def test_it_says_nothing_when_there_is_none(self, tmp_path: Path, capsys, monkeypatch):
        monkeypatch.setattr(label, "CRASH_PATH", tmp_path / "ない.txt")

        label.report_last_crash()

        assert capsys.readouterr().out == ""

    def test_an_empty_record_is_not_reported(self, tmp_path: Path, capsys, monkeypatch):
        """開いただけで中身が無いファイルは、落ちた証拠ではない。"""
        path = tmp_path / "落ちた記録.txt"
        path.write_text("", encoding="utf-8")
        monkeypatch.setattr(label, "CRASH_PATH", path)

        label.report_last_crash()

        assert capsys.readouterr().out == ""

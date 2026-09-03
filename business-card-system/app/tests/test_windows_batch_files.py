"""Windows 用の .bat が、あちらで正しく読めること。

`.bat` は cmd.exe が CP932 として読む。UTF-8 で書くと画面が文字化けし、
日本語を含む条件分岐が壊れる。

ここは2度踏んだ落とし穴を塞ぐためにある。

  1. 改行を `\\n` として照合し、CRLF の実ファイルと合わずに編集が失敗した
  2. em ダッシュ（U+2014）を書き、CP932 に無くて保存できなかった

どちらも書き換えの最中に気づけたが、気づかなければ**利用者の画面だけが
壊れる**（こちらの試験は素通りする）ため、機械で確かめる。
"""

from __future__ import annotations

from pathlib import Path

import pytest

WINDOWS = Path(__file__).resolve().parents[2] / "windows"
BATCH_FILES = sorted(WINDOWS.glob("*.bat"))


def test_there_are_batch_files_to_check():
    """探し方を間違えて0件を無言で通すことが無いように。"""
    assert len(BATCH_FILES) >= 10


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
class TestEachBatchFile:
    def test_it_is_readable_as_cp932(self, path: Path):
        try:
            path.read_bytes().decode("cp932")
        except UnicodeDecodeError as exc:
            pytest.fail(f"{path.name} が CP932 として読めない: {exc}")

    def test_it_uses_crlf(self, path: Path):
        """cmd.exe は LF だけの行を扱い損ねることがある。"""
        raw = path.read_bytes()
        assert raw.count(b"\n") == raw.count(b"\r\n"), (
            f"{path.name} に CRLF でない改行がある"
        )


class TestTheWayOutIsOffered:
    """同期フォルダから出る手立てが、入口から辿れること。

    原因が分かっても、直す手立てが見つからなければ意味がない。
    """

    def test_the_mover_exists(self):
        assert (WINDOWS / "move-out-of-dropbox.bat").exists()

    def test_the_menu_offers_it(self):
        menu = (WINDOWS / "menu.bat").read_bytes().decode("cp932")
        assert "move-out-of-dropbox.bat" in menu
        assert "同期フォルダの外へ写す" in menu

    def test_the_menu_warns_when_inside_a_sync_folder(self):
        menu = (WINDOWS / "menu.bat").read_bytes().decode("cp932")
        assert "findstr /i \"Dropbox OneDrive iCloud\"" in menu

    def test_the_mover_does_not_copy_the_virtual_environment(self):
        """`.venv` には元の場所が焼き込まれている。写しても動かない。"""
        mover = (WINDOWS / "move-out-of-dropbox.bat").read_bytes().decode("cp932")
        assert "/XD" in mover and ".venv" in mover

    def test_the_mover_keeps_the_original(self):
        """**元は消さない。** 新しい場所で動くと確かめるまでの命綱。"""
        mover = (WINDOWS / "move-out-of-dropbox.bat").read_bytes().decode("cp932")
        assert "/MOVE" not in mover, "robocopy /MOVE は元を消してしまう"
        assert "古い場所は消していません" in mover

    def test_the_mover_reads_robocopy_exit_codes_correctly(self):
        """robocopy は 0〜7 が成功。`errorlevel 1` で見ると誤検知する。"""
        mover = (WINDOWS / "move-out-of-dropbox.bat").read_bytes().decode("cp932")
        assert "errorlevel 8" in mover

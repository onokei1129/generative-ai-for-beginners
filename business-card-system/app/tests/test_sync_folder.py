"""同期フォルダの上で動いていないかを調べる仕組みの試験。

実テストでサーバーが跡形もなく消え続けた原因は、`.venv` ごと Dropbox の
中に置かれていたことだった。詳しい理屈は `poc/sync_folder.py` の冒頭に
書いてある。ここでは、その検出が**当たるべきときに当たり、外れるべき
ときに外れる**ことを確かめる。
"""

from __future__ import annotations

from pathlib import Path

from poc.sync_folder import sync_folder_for


class TestItFindsTheSyncFolder:
    def test_a_dropbox_marker_is_found(self, tmp_path: Path):
        """同期ソフトが置く印で判定する（名前より確か）。"""
        root = tmp_path / "しごと"
        deep = root / "アプリ" / "app" / ".venv" / "Scripts"
        deep.mkdir(parents=True)
        (root / ".dropbox").write_text("", encoding="utf-8")

        found = sync_folder_for(deep / "python.exe")

        assert found == ("Dropbox", root)

    def test_the_folder_name_is_used_when_there_is_no_marker(self, tmp_path: Path):
        """印が無くても、名前で気づけること。

        印は同期ソフトの版によって変わる。名前も見ておかないと、
        本当に危ない置き場所を見逃す。
        """
        root = tmp_path / "Dropbox"
        deep = root / "勝手プロジェクト" / "app" / ".venv"
        deep.mkdir(parents=True)

        found = sync_folder_for(deep / "python.exe")

        assert found == ("Dropbox", root)

    def test_onedrive_with_a_company_name(self, tmp_path: Path):
        """`OneDrive - 会社名` の形も同期フォルダ。"""
        root = tmp_path / "OneDrive - にっぽん商事"
        deep = root / "app" / ".venv"
        deep.mkdir(parents=True)

        found = sync_folder_for(deep / "python.exe")

        assert found == ("OneDrive", root)


class TestItDoesNotCryWolf:
    """**誤った警告は、本当の警告を読み飛ばさせる。**"""

    def test_an_ordinary_folder_is_not_flagged(self, tmp_path: Path):
        deep = tmp_path / "名刺管理アプリケーション" / "app" / ".venv"
        deep.mkdir(parents=True)

        assert sync_folder_for(deep / "python.exe") is None

    def test_a_folder_merely_containing_the_word_is_not_flagged(self, tmp_path: Path):
        """`Dropboxからの移行` のような名前は同期フォルダではない。"""
        deep = tmp_path / "Dropboxからの移行" / "app" / ".venv"
        deep.mkdir(parents=True)

        assert sync_folder_for(deep / "python.exe") is None

    def test_a_missing_path_is_not_flagged(self, tmp_path: Path):
        assert sync_folder_for(tmp_path / "無い" / "python.exe") is None

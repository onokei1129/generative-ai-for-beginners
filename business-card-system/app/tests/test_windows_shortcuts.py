"""デスクトップのショートカット一式（windows/）。

実テストからの3つの報告に対応した形を守るためのテスト。

1. 「押すたびにエクスプローラーの窓が増える」
   更新のたびにフォルダを開いていた。更新から呼ぶときは `/quiet` で開かない。
   自分でこのバッチを押したときは必ず開く——「初回だけ」にしたところ、
   2回目以降は何も起きないように見え、別の報告になった。

2. 「最低でも同じウィンドウが2枚開いている」
   `real-cards` と その中の `unknown` を別々に開いていた。`/select` で
   1つの窓にまとめる。

3. 「ショートカットを減らしてシンプルにしたい」
   続けて実行するものは1つにまとめる（更新＋セットアップ、仕分け＋結果
   確認）。終わった作業の窓は自動で閉じ、失敗したときだけ止めて理由を出す。

バッチはこのテストからは実行できない（Windows専用）ので、中身を読んで
確かめる。バッチは CP932 で保存する（Windows のコマンドプロンプトが
既定で読む文字コード。UTF-8 だと日本語が化ける）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WINDOWS = Path(__file__).resolve().parents[2] / "windows"
SHORTCUTS = WINDOWS / "create-desktop-shortcuts.bat"
UPDATE = WINDOWS / "update.bat"
CARD_FOLDER = WINDOWS / "open-card-folder.bat"


def source(path: Path) -> str:
    return path.read_text(encoding="cp932")


class TestTheUpdateDoesNotPileUpWindows:
    def test_the_update_calls_the_shortcut_batch_quietly(self):
        assert re.search(r'call "%BCWIN%\\create-desktop-shortcuts\.bat" /quiet', source(UPDATE))

    def test_the_shortcut_batch_understands_quiet(self):
        assert 'if /i "%~1"=="/quiet" set "QUIET=1"' in source(SHORTCUTS)

    def test_the_folder_is_not_opened_when_quiet(self):
        """`explorer` より前で抜けること。順序が逆だと窓が開いてしまう。"""
        text = source(SHORTCUTS)

        assert text.index("if defined QUIET exit /b 0") < text.index('explorer "%FOLDER%"')


class TestRunningItDirectlyShowsAResult:
    """自分でこのバッチを押したときは必ずフォルダを開くこと。

    窓が溜まって困るのは「1 準備する」から呼ばれる側（`/quiet`）だけ。
    一度「初回だけ開く」にしたところ、2回目以降は何も起きないように見え、
    「クリックしても何も開始しない」という報告になった。
    """

    def test_the_folder_is_opened_every_time(self):
        text = source(SHORTCUTS)

        assert 'explorer "%FOLDER%"' in text
        assert "if defined FIRST" not in text

    def test_the_open_comes_after_the_quiet_exit(self):
        """`/quiet` で呼ばれたときだけ開かない、という順序を保つこと。"""
        text = source(SHORTCUTS)

        assert text.index("if defined QUIET exit /b 0") < text.index('explorer "%FOLDER%"')

    def test_it_says_what_it_is_doing(self):
        """開く前に一言出す。無言だと動いたのか分からない。"""
        assert "作ったフォルダを開きます。" in source(SHORTCUTS)


class TestTheDesktopIsResolvedByWindows:
    """デスクトップの場所を推測しないこと。

    OneDrive や iCloud Drive で同期していると、`%USERPROFILE%\\Desktop` は
    画面に出ているフォルダとは別のことがある。実テストで、「作成」と出て
    いるのにデスクトップに現れない状態になった。
    """

    def test_windows_is_asked_for_the_path(self):
        assert "[Environment]::GetFolderPath('Desktop')" in source(SHORTCUTS)

    def test_it_no_longer_guesses_from_onedrive(self):
        """同期ソフトごとに場当たりで足さないこと。"""
        assert 'set "DESKTOP=%OneDrive%\\Desktop"' not in source(SHORTCUTS)

    def test_there_is_a_fallback_when_the_lookup_fails(self):
        text = source(SHORTCUTS)

        assert 'if not defined DESKTOP set "DESKTOP=%USERPROFILE%\\Desktop"' in text

    def test_the_path_is_shown(self):
        """どこに作ったかを出す。見つからないときの切り分けに要る。"""
        assert "echo デスクトップ: %DESKTOP%" in source(SHORTCUTS)


class TestTheResultIsVerified:
    """「作成」と出ただけで終わらせないこと。

    `:make` は PowerShell の戻り値しか見ていないため、同期フォルダの都合で
    ファイルが残らなくても成功に見える。
    """

    def test_the_files_are_counted(self):
        text = source(SHORTCUTS)

        assert 'for %%f in ("%FOLDER%\\*.lnk") do set /a MADE+=1' in text

    def test_zero_is_an_error(self):
        text = source(SHORTCUTS)

        assert 'if "%MADE%"=="0" goto :none_made' in text
        assert "ショートカットが1つも残りませんでした" in text

    def test_the_count_is_reported(self):
        assert "%MADE% 個" in source(SHORTCUTS)

    def test_the_check_runs_before_the_quiet_exit(self):
        """更新から静かに呼ばれたときも、0個なら気づけること。"""
        text = source(SHORTCUTS)

        assert text.index('if "%MADE%"=="0"') < text.index("if defined QUIET exit /b 0")


class TestTheSortResultOpensOneWindow:
    """似た見た目の窓を2枚並べないこと。

    実テストで「最低でも同じウィンドウが2枚開いている」という報告があった。
    `real-cards` と その中の `unknown` を別々に開いていたため。
    """

    def test_the_unknown_folder_is_selected_not_opened_separately(self):
        text = source(CARD_FOLDER)

        assert 'explorer /select,"%CD%\\poc\\real-cards\\unknown"' in text

    def test_the_parent_is_not_opened_as_well(self):
        """`/select` で開くときは、親フォルダを重ねて開かないこと。"""
        text = source(CARD_FOLDER)

        assert 'start "" "%CD%\\poc\\real-cards"' not in text
        assert 'start "" "%CD%\\poc\\real-cards\\unknown"' not in text

    def test_the_parent_still_opens_when_there_is_no_unknown_folder(self):
        text = source(CARD_FOLDER)

        assert 'explorer "%CD%\\poc\\real-cards"' in text

    def test_only_one_explorer_runs_per_path(self):
        """どちらか一方だけを通ること（goto で分岐）。"""
        text = source(CARD_FOLDER)

        assert "goto :open_with_unknown" in text
        assert "goto :opened" in text


class TestTheStepsAreChained:
    """押す回数を減らすため、続けて実行するものは1つにまとめる。"""

    def test_preparing_runs_the_setup_too(self):
        assert 'call "%BCWIN%\\setup.bat" /quick' in source(UPDATE)

    def test_the_setup_is_skipped_on_failure(self):
        """更新に失敗したらセットアップへ進まないこと。"""
        text = source(UPDATE)
        after = text.split('call "%BCWIN%\\setup.bat" /quick', 1)[1]

        assert "if errorlevel 1 exit /b 1" in after.split("\n\n", 1)[0]

    def test_sorting_opens_the_result(self):
        text = (WINDOWS / "classify-scans.bat").read_text(encoding="cp932")

        assert 'call "%~dp0open-card-folder.bat" /quiet' in text

    def test_the_first_setup_still_runs_the_checks(self):
        """初回は /quick が付いていても確認テストを走らせること。"""
        text = (WINDOWS / "setup.bat").read_text(encoding="cp932")

        assert 'if not exist ".venv\\Scripts\\python.exe" set "QUICK="' in text


class TestFinishedWorkClosesItsWindow:
    """終わった作業の窓は自動で閉じる。失敗したときだけ止めて理由を出す。"""

    @pytest.mark.parametrize(
        "name", ["update.bat", "classify-scans.bat", "measure-accuracy.bat"]
    )
    def test_the_window_closes_after_a_countdown(self, name: str):
        tail = (WINDOWS / name).read_text(encoding="cp932").rsplit("============", 1)[-1]

        assert "timeout /t" in tail
        assert "pause" not in tail

    @pytest.mark.parametrize(
        "name", ["update.bat", "classify-scans.bat", "measure-accuracy.bat", "setup.bat"]
    )
    def test_failures_still_wait_so_the_reason_can_be_read(self, name: str):
        text = (WINDOWS / name).read_text(encoding="cp932")

        assert "[エラー]" in text
        assert "pause" in text

    @pytest.mark.parametrize("name", ["label-real-cards.bat", "run-app.bat"])
    def test_windows_that_run_a_server_stay_open(self, name: str):
        """サーバーを動かす窓は閉じない（閉じると止まる）。"""
        text = (WINDOWS / name).read_text(encoding="cp932")

        assert "ウィンドウを閉じてください" in text


class TestEveryShortcutPointsAtARealFile:
    """作ったショートカットの飛び先が実在すること。

    飛び先を打ち間違えても作成そのものは成功するため、押すまで気づけない。
    """

    def targets(self) -> list[tuple[str, str]]:
        return re.findall(r'call :make\s+"([^"]+)"\s+"([^"]+)"', source(SHORTCUTS))

    def test_the_list_is_short(self):
        """押す数を増やさないこと。まとめられるものはまとめる方針。"""
        assert 5 <= len(self.targets()) <= 8

    def test_each_target_exists(self):
        missing = [(label, bat) for label, bat in self.targets() if not (WINDOWS / bat).is_file()]

        assert missing == []

    @pytest.mark.parametrize(
        "label",
        [
            "1 準備する（更新とセットアップ）",
            "2 名刺を仕分ける",
            "3 ラベル入力",
            "4 精度を測る",
            "この1枚を調べる",
            "動かないとき（診断）",
        ],
    )
    def test_the_documented_shortcuts_are_present(self, label: str):
        assert label in [name for name, _ in self.targets()]

    def test_the_numbers_run_from_one_without_gaps(self):
        """番号を飛ばさないこと。押す順が分からなくなる。"""
        numbers = [name[0] for name, _ in self.targets() if name[0].isdigit()]

        assert numbers == [str(n) for n in range(1, len(numbers) + 1)]

    def test_the_merged_steps_are_gone(self):
        """まとめた側の入口を二重に置かないこと。"""
        names = [name for name, _ in self.targets()]

        assert not any("セットアップ" == name for name in names)
        assert not any("仕分け結果" in name for name in names)
        assert not any("進み具合" in name for name in names)
        assert not any("練習" in name for name in names)


class TestTheBatchFilesStayReadableOnWindows:
    @pytest.mark.parametrize("path", [SHORTCUTS, UPDATE, CARD_FOLDER])
    def test_the_encoding_is_cp932(self, path: Path):
        path.read_text(encoding="cp932")  # 読めなければ例外

    @pytest.mark.parametrize("path", [SHORTCUTS, UPDATE, CARD_FOLDER])
    def test_the_line_endings_are_crlf(self, path: Path):
        raw = path.read_bytes()

        assert b"\r\n" in raw
        assert raw.replace(b"\r\n", b"") .count(b"\n") == 0

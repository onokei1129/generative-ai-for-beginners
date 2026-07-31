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


def shortcut_targets() -> list[tuple[str, str]]:
    """`call :make "名前" "バッチ"` の並びを読む。"""
    return re.findall(r'call :make\s+"([^"]+)"\s+"([^"]+)"', source(SHORTCUTS))


class TestTheShortcutsLandOnTheDesktopItself:
    """フォルダの中ではなく、デスクトップに直接置くこと。

    以前は「名刺システム」フォルダを作ってその中へ入れていた。画面には
    フォルダが1個見えるだけで、実テストで「デスクトップに作られない」
    という報告になった。画面に並ぶアイコンとして置く。
    """

    def test_no_subfolder_is_created(self):
        text = source(SHORTCUTS)

        assert 'mkdir "%FOLDER%"' not in text

    def test_every_shortcut_is_prefixed(self):
        """`名刺 ` で始めて、他のアイコンと混ざらないようにする。"""
        names = [name for name, _ in shortcut_targets()]

        assert names
        assert all(name.startswith("名刺 ") for name in names)

    def test_they_are_written_to_the_target_directory(self):
        assert r"CreateShortcut('%TARGET%\%~1.lnk')" in source(SHORTCUTS)


class TestOnlyOurOwnShortcutsAreDeleted:
    """作り直すときに、利用者が置いた他のショートカットを消さないこと。"""

    def test_the_delete_is_limited_to_our_prefix(self):
        text = source(SHORTCUTS)

        assert 'del /q "%TARGET%\名刺 *.lnk"' in text
        assert r'del /q "%TARGET%\*.lnk"' not in text

    def test_the_old_folder_is_tidied_up(self):
        """以前の版が作ったフォルダを片付ける。中身が残っていれば触らない。"""
        text = source(SHORTCUTS)

        assert r'del /q "%TARGET%\名刺システム\*.lnk"' in text
        assert 'rd "%TARGET%\名刺システム" 2>nul' in text
        assert "rd /s" not in text


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

        assert 'for %%f in ("%DESKTOP%\\名刺 *.lnk") do set /a MADE+=1' in text

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

    def test_a_second_location_is_tried_when_they_differ(self):
        """場所の取得を誤っていても画面に出るよう、素の場所にも置く。"""
        text = source(SHORTCUTS)

        assert 'set "PLAIN=%USERPROFILE%\\Desktop"' in text
        assert 'if /i "%PLAIN%"=="%DESKTOP%" goto :count' in text


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
        return shortcut_targets()

    def test_the_list_is_short(self):
        """押す数を増やさないこと。まとめられるものはまとめる方針。"""
        assert 5 <= len(self.targets()) <= 8

    def test_each_target_exists(self):
        missing = [(label, bat) for label, bat in self.targets() if not (WINDOWS / bat).is_file()]

        assert missing == []

    @pytest.mark.parametrize(
        "label",
        [
            "名刺 1 準備する（更新とセットアップ）",
            "名刺 2 名刺を仕分ける",
            "名刺 3 ラベル入力",
            "名刺 4 精度を測る",
            "名刺 この1枚を調べる",
            "名刺 動かないとき（診断）",
        ],
    )
    def test_the_documented_shortcuts_are_present(self, label: str):
        assert label in [name for name, _ in self.targets()]

    def test_the_numbers_run_from_one_without_gaps(self):
        """番号を飛ばさないこと。押す順が分からなくなる。"""
        numbers = [name[3] for name, _ in self.targets() if name[3:4].isdigit()]

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

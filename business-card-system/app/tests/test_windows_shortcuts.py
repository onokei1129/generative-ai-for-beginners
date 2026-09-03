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
DOCTOR = WINDOWS / "doctor.bat"
MENU = WINDOWS / "menu.bat"


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
        assert all(name.startswith("名刺") for name in names)

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
        assert 'call :say "デスクトップ: %DESKTOP%"' in source(SHORTCUTS)


class TestTheResultIsVerified:
    """「作成」と出ただけで終わらせないこと。

    `:make` は PowerShell の戻り値しか見ていないため、同期フォルダの都合で
    ファイルが残らなくても成功に見える。
    """

    def test_the_files_are_counted(self):
        text = source(SHORTCUTS)

        assert 'for %%f in ("%~1\\名刺システム.lnk") do set /a MADE+=1' in text
        assert 'for %%f in ("%~1\\名刺システム.bat") do set /a MADE+=1' in text

    def test_zero_is_an_error(self):
        text = source(SHORTCUTS)

        assert 'if "%MADE%"=="0" goto :none_made' in text
        assert "ショートカットが1つも残りませんでした" in text

    def test_what_was_placed_is_reported(self):
        assert 'call :say "デスクトップに「名刺システム」を置きました。"' in source(SHORTCUTS)

    def test_the_check_runs_before_the_quiet_exit(self):
        """更新から静かに呼ばれたときも、0個なら気づけること。"""
        text = source(SHORTCUTS)

        assert text.index('if "%MADE%"=="0"') < text.index("if defined QUIET exit /b 0")

    def test_a_second_location_is_tried_when_they_differ(self):
        """場所の取得を誤っていても画面に出るよう、素の場所にも置く。"""
        text = source(SHORTCUTS)

        assert 'set "PLAIN=%USERPROFILE%\\Desktop"' in text
        assert 'if /i "%PLAIN%"=="%DESKTOP%" goto :verify' in text


class TestPressingItAlsoFetchesTheLatest:
    """自分で押したときは、まず最新版を取ってから作ること。

    実テストで「このバッチを何度押しても直らない」という報告が続いた。
    取得するのは update.bat だけで、このバッチはディスクにある版で作り直す
    だけだった。押す側からは区別がつかない。
    """

    def test_it_pulls_when_pressed_directly(self):
        assert "git pull" in source(SHORTCUTS)

    def test_it_copies_itself_before_pulling(self):
        """git pull は自分自身を書き換えうる。実行中に書き換わると壊れる。"""
        text = source(SHORTCUTS)

        assert 'copy /y "%~f0" "%TEMP%\\bcards-shortcuts.bat"' in text
        assert '"%TEMP%\\bcards-shortcuts.bat" /pull "%HERE%"' in text

    def test_the_fetched_version_does_the_work(self):
        """取得したあとのファイルを呼ぶこと（写しではなく）。"""
        assert 'call "%SRC%\\create-desktop-shortcuts.bat" /nopull' in source(SHORTCUTS)

    @pytest.mark.parametrize("flag", ["/quiet", "/nopull"])
    def test_being_called_from_elsewhere_skips_the_fetch(self, flag: str):
        """「1 準備する」は直前に取得している。二重に取らない。"""
        text = source(SHORTCUTS)

        assert re.search(rf'if /i "%~1"=="{flag}" +set "NOPULL=1"', text)
        assert "if defined NOPULL goto :begin" in text

    def test_a_missing_git_still_creates_the_shortcuts(self):
        text = source(SHORTCUTS)

        assert "goto :pull_no_git" in text
        assert text.index("\n:pull_no_git\n") < text.index("\n:pull_done\n")

    def test_a_failed_copy_still_creates_the_shortcuts(self):
        text = source(SHORTCUTS)
        after = text.split('copy /y "%~f0"', 1)[1]

        assert after.startswith(' "%TEMP%\\bcards-shortcuts.bat" >nul\nif errorlevel 1 goto :begin')


class TestWhichCopyAndWhichVersionIsShown:
    """どの複製の、どの版を動かしているのかを最初に出すこと。

    実テストで、画面の文言が以前のままであることに双方が長く気づけなかった。
    複製が2つあると、更新したほうと押しているほうが食い違う。
    """

    @pytest.mark.parametrize("path", [SHORTCUTS, UPDATE])
    def test_the_commit_is_shown(self, path: Path):
        text = source(path)

        assert "rev-parse --short HEAD" in text
        assert "版:" in text

    def test_the_folder_is_shown(self):
        """どの複製から実行したのかを出す。"""
        assert 'call :say "場所: %HERE%"' in source(SHORTCUTS)

    def test_it_comes_before_any_work(self):
        text = source(SHORTCUTS)

        assert text.index('call :say "版:') < text.index("call :make_all")

    def test_a_missing_git_is_not_an_error(self):
        """git が無い環境でも作成そのものは続けること。"""
        assert 'if not defined REV set "REV=不明"' in source(SHORTCUTS)


class TestTheDiagnosisNamesTheCopy:
    """診断は、どの複製を動かしているかを突き合わせられること。

    実テストで、更新したフォルダと、デスクトップのショートカットが指す
    フォルダが食い違い、直したはずの不具合が直らない状態が続いた。
    画面の文言だけでは双方とも気づけない。
    """

    def test_the_folder_version_and_branch_are_shown(self):
        text = source(DOCTOR)

        assert "echo 場所:" in text
        assert "rev-parse --short HEAD" in text
        assert "rev-parse --abbrev-ref HEAD" in text

    def test_being_behind_origin_is_reported(self):
        text = source(DOCTOR)

        assert "rev-list --count HEAD..origin/%BRANCH%" in text
        assert "未取得:" in text

    def test_the_shortcut_targets_are_listed(self):
        """飛び先が上の「場所」と違えば、複製の食い違いと分かる。"""
        text = source(DOCTOR)

        assert "CreateShortcut($_.FullName).TargetPath" in text

    def test_the_old_folder_is_looked_at_too(self):
        """以前の版が作った「名刺システム」の中も見る。"""
        assert "%DESKTOP%\\名刺システム" in source(DOCTOR)

    def test_it_runs_before_the_setup_check(self):
        """セットアップ前でも、どの複製かは分かること。"""
        text = source(DOCTOR)

        assert text.index("echo 場所:") < text.index('if not exist ".venv\\Scripts\\python.exe"')


class TestTheCountIsTakenAfterAPause:
    """作った直後ではなく、少し待ってから数えること。

    iCloud Drive はデスクトップに置いた `.lnk` を同期の対象として扱わず、
    作った直後に取り除くことがある。その場で数えると 7 個あるように見えて、
    数秒後には消えている。実テストで「作成」と出るのに画面に現れない状態に
    なった。
    """

    def test_it_waits_before_counting(self):
        text = source(SHORTCUTS)
        before = text.split(":verify", 1)[1].split("call :count", 1)[0]

        assert "ping -n" in before

    def test_the_wait_does_not_use_timeout(self):
        """`timeout` は入力が渡されない呼ばれ方だと即座に失敗する。"""
        assert "timeout /t" not in source(SHORTCUTS)


class TestBatchFilesAreTheFallback:
    """`.lnk` が残らないときは、同じ名前のバッチで作り直すこと。

    バッチはただのファイルなので同期ソフトに取り除かれない。飛び先を
    呼ぶだけなので、押したときの動きは `.lnk` と変わらない。
    """

    def test_the_fallback_is_only_used_when_nothing_survived(self):
        text = source(SHORTCUTS)
        after = text.split('if not "%MADE%"=="0" goto :done', 1)[1]

        assert 'set "KIND=bat"' in after.split(":done", 1)[0]

    def test_the_fallback_writes_a_launcher(self):
        text = source(SHORTCUTS)

        assert '>"%TARGET%\\%~1.bat" echo @echo off' in text
        assert '>>"%TARGET%\\%~1.bat" echo call "%HERE%\\%~2"' in text

    def test_the_launcher_moves_to_the_windows_folder_first(self):
        """飛び先のバッチは相対パスで他のファイルを呼ぶ。"""
        assert '>>"%TARGET%\\%~1.bat" echo cd /d "%HERE%"' in source(SHORTCUTS)

    def test_the_old_launchers_are_deleted_too(self):
        assert 'del /q "%TARGET%\\名刺 *.bat"' in source(SHORTCUTS)

    def test_the_shortcut_is_still_the_first_choice(self):
        """既定は `.lnk`。切り替えるのは残らなかったときだけ。"""
        text = source(SHORTCUTS)

        assert text.index('set "KIND="') < text.index('set "KIND=bat"')
        assert 'if /i "%KIND%"=="bat" goto :make_bat' in text


class TestWhatHappenedIsRecorded:
    """うまくいかないときに、後から追える形で残すこと。

    画面は閉じてしまうと読めない。実テストでは「変わらない」という報告に
    対して手掛かりが無く、何度も往復することになった。
    """

    def test_the_log_sits_next_to_the_batch(self):
        assert 'set "LOG=%HERE%\\ショートカット作成ログ.txt"' in source(SHORTCUTS)

    def test_messages_go_to_both_the_screen_and_the_log(self):
        text = source(SHORTCUTS)
        say = text.split("\n:say\n", 1)[1].split("exit /b 0", 1)[0]

        assert "echo %~1" in say
        assert '>>"%LOG%" echo %~1' in say

    def test_the_desktop_path_is_recorded(self):
        assert 'call :say "デスクトップ: %DESKTOP%"' in source(SHORTCUTS)

    def test_the_log_is_not_committed(self):
        ignored = (WINDOWS / ".gitignore").read_text(encoding="utf-8")

        assert "ショートカット作成ログ.txt" in ignored


class TestThePlaceIsOpenedWhenPressedDirectly:
    """置いた場所そのものを開く。

    画面に出ないのか、そもそも作られていないのかを、利用者が1回で
    見分けられるようにする。更新から呼ばれるときは開かない（窓が増える）。
    """

    def test_the_desktop_folder_is_opened(self):
        assert 'explorer "%DESKTOP%"' in source(SHORTCUTS)

    def test_it_is_not_opened_in_quiet_mode(self):
        text = source(SHORTCUTS)
        done = text.split("\n:done\n", 1)[1].split("\n:none_made", 1)[0]

        assert done.index("if defined QUIET exit /b 0") < done.index('explorer "%DESKTOP%"')

    def test_hiding_the_desktop_icons_is_mentioned(self):
        """アイコンの表示が切られている場合もある。"""
        assert "デスクトップ アイコンの表示" in source(SHORTCUTS)


class TestTheRegistryIsTheSecondSource:
    """`GetFolderPath` が空を返したときの控え。"""

    def test_the_shell_folders_key_is_read(self):
        text = source(SHORTCUTS)

        assert "Explorer\\Shell Folders" in text
        assert "/v Desktop" in text

    def test_it_is_tried_before_guessing(self):
        text = source(SHORTCUTS)

        assert text.index("if not defined DESKTOP call :from_registry") < text.index(
            'if not defined DESKTOP set "DESKTOP=%USERPROFILE%\\Desktop"'
        )


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


class TestOnlyOneIconIsPlaced:
    """デスクトップに置くのは1つだけ。

    やることの数だけ並べていた（7〜8個）。実テストで「デスクトップが雑然と
    してしまった」という報告になった。フォルダに入れると今度は画面から
    見えなくなる（それも実テストで報告があった）ので、1つだけ直接置く。
    """

    def test_exactly_one_shortcut_is_made(self):
        assert shortcut_targets() == [("名刺システム", "menu.bat")]

    def test_its_target_exists(self):
        _, bat = shortcut_targets()[0]

        assert (WINDOWS / bat).is_file()

    def test_the_previous_row_of_icons_is_removed(self):
        """以前の版が並べた `名刺 …` を消してから作ること。"""
        text = source(SHORTCUTS)

        assert 'del /q "%TARGET%\\名刺 *.lnk"' in text
        assert 'del /q "%TARGET%\\名刺 *.bat"' in text

    def test_its_own_earlier_copy_is_removed(self):
        text = source(SHORTCUTS)

        assert 'del /q "%TARGET%\\名刺システム.lnk"' in text
        assert 'del /q "%TARGET%\\名刺システム.bat"' in text


class TestTheMenuOffersEveryStep:
    """1つにまとめた代わりに、やることは番号で選べること。"""

    def targets(self) -> list[tuple[str, str]]:
        """`call "%HERE%\bat"` の並びを読む。"""
        return re.findall(r'call "%HERE%\\([a-z0-9-]+\.bat)"', source(MENU))

    def test_each_step_points_at_a_real_file(self):
        missing = [bat for bat in self.targets() if not (WINDOWS / bat).is_file()]

        assert missing == []

    @pytest.mark.parametrize(
        "bat",
        [
            "update.bat",
            "classify-scans.bat",
            "label-real-cards.bat",
            "measure-accuracy.bat",
            "run-app.bat",
            "explain-one.bat",
            "doctor.bat",
        ],
    )
    def test_the_documented_steps_are_reachable(self, bat: str):
        assert bat in self.targets()

    def test_the_numbers_run_from_one_without_gaps(self):
        numbers = re.findall(r'if "%CHOICE%"=="(\d)" goto :do_', source(MENU))

        assert numbers == [str(n) for n in range(1, len(numbers) + 1)]

    def test_zero_closes_it(self):
        assert 'if "%CHOICE%"=="0" exit /b 0' in source(MENU)

    def test_an_unknown_answer_does_not_close_it(self):
        """打ち間違えて閉じてしまわないこと。

        案内する番号の範囲は**メニューの中身から導く**。直書きすると、
        項目を1つ足すたびにこの試験が落ちる——実際に「8 同期フォルダの
        外へ写す」を足したときに落ちた。落ちること自体は正しいが、
        直すのは案内の文だけでよく、試験まで書き換えるのは無駄が多い。
        """
        text = source(MENU)
        highest = max(int(n) for n in re.findall(r"^echo   (\d)  \S", text, re.M))

        assert f"1 から {highest} か 0 を入れてください。" in text, (
            f"メニューは {highest} まであるのに、案内の文が食い違っている"
        )
        assert text.rstrip().endswith("goto :menu")

    def test_it_returns_to_the_menu_after_each_step(self):
        """呼びっぱなしにしない（call で戻る）。"""
        text = source(MENU)
        steps = text.split("\n:do_1\n", 1)[1]

        assert steps.count("goto :menu") == len(self.targets())

    def test_the_merged_steps_have_no_separate_entry(self):
        """まとめた側の入口を二重に置かないこと。"""
        targets = self.targets()

        assert "setup.bat" not in targets
        assert "open-card-folder.bat" not in targets
        assert "check-progress.bat" not in targets
        assert "label-practice.bat" not in targets


class TestTheMenuSurvivesAnUpdate:
    """「1 準備する」は git pull を行い、この入口自身も書き換えうる。

    cmd.exe はバッチを実行しながら少しずつ読むため、実行中に書き換わると
    途中から壊れる。一時フォルダへ写してそちらから動かす（update.bat と同じ）。
    """

    def test_it_copies_itself_first(self):
        text = source(MENU)

        assert 'copy /y "%~f0" "%TEMP%\\bcards-menu.bat"' in text
        assert '"%TEMP%\\bcards-menu.bat" /run "%~dp0."' in text

    def test_the_original_folder_is_passed_along(self):
        """写しから動くので、元のフォルダの場所を引数で渡すこと。"""
        text = source(MENU)

        assert 'set "SRC=%~2"' in text
        assert 'set "HERE=%SRC%"' in text

    def test_a_failed_copy_still_shows_the_menu(self):
        assert "goto :prep_here" in source(MENU)

    def test_which_copy_and_version_is_shown(self):
        text = source(MENU)

        assert "echo  場所: %HERE%" in text
        assert "rev-parse --short HEAD" in text


class TestTheBatchFilesStayReadableOnWindows:
    @pytest.mark.parametrize("path", [SHORTCUTS, UPDATE, CARD_FOLDER, MENU])
    def test_the_encoding_is_cp932(self, path: Path):
        path.read_text(encoding="cp932")  # 読めなければ例外

    @pytest.mark.parametrize("path", [SHORTCUTS, UPDATE, CARD_FOLDER, MENU])
    def test_the_line_endings_are_crlf(self, path: Path):
        raw = path.read_bytes()

        assert b"\r\n" in raw
        assert raw.replace(b"\r\n", b"") .count(b"\n") == 0

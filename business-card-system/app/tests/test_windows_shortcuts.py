"""デスクトップのショートカット一式（windows/）。

実テストからの3つの報告に対応した形を守るためのテスト。

1. 「押すたびにエクスプローラーの窓が増える」
   ショートカットを作り直すたびにフォルダを開いていた。更新から呼ぶときは
   `/quiet`、自分で作り直すときも初回だけ開く。

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


class TestTheFolderOpensOnlyOnTheFirstRun:
    """作り直すたびに開くと窓が溜まる。初回だけ開く。"""

    def test_the_first_run_is_detected(self):
        text = source(SHORTCUTS)

        assert 'if not exist "%FOLDER%" set "FIRST=1"' in text

    def test_the_check_comes_before_the_folder_is_made(self):
        """先に mkdir すると、初回でも「既にある」と見えてしまう。"""
        text = source(SHORTCUTS)

        assert text.index('set "FIRST=1"') < text.index('mkdir "%FOLDER%"')

    def test_the_folder_is_opened_only_when_first(self):
        assert 'if defined FIRST explorer "%FOLDER%"' in source(SHORTCUTS)


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

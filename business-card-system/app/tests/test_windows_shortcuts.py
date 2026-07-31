"""デスクトップのショートカットを作るバッチ（windows/）。

実テストで、「0 最新版に更新する」を押すたびにエクスプローラーの窓が
1つ増え、押すほど溜まっていく、という報告があった。

    create-desktop-shortcuts.bat の末尾に無条件の `explorer "%FOLDER%"` があり、
    update.bat が最後にこのバッチを呼ぶため、更新のたびに窓が開いていた。

更新から呼ぶときは `/quiet` を付け、フォルダを開かない。

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

    def test_the_update_still_waits_for_a_key(self):
        """静かに呼ぶぶん、更新側で止めること。止めないと結果が読めない。"""
        tail = source(UPDATE).rsplit("/quiet", 1)[-1]

        assert "pause" in tail


class TestEveryShortcutPointsAtARealFile:
    """作ったショートカットの飛び先が実在すること。

    飛び先を打ち間違えても作成そのものは成功するため、押すまで気づけない。
    """

    def targets(self) -> list[tuple[str, str]]:
        return re.findall(r'call :make\s+"([^"]+)"\s+"([^"]+)"', source(SHORTCUTS))

    def test_the_list_is_not_empty(self):
        assert len(self.targets()) >= 10

    def test_each_target_exists(self):
        missing = [(label, bat) for label, bat in self.targets() if not (WINDOWS / bat).is_file()]

        assert missing == []

    @pytest.mark.parametrize("label", ["0 最新版に更新する", "この1枚を調べる", "動かないとき（診断）"])
    def test_the_documented_shortcuts_are_present(self, label: str):
        assert label in [name for name, _ in self.targets()]


class TestTheBatchFilesStayReadableOnWindows:
    @pytest.mark.parametrize("path", [SHORTCUTS, UPDATE])
    def test_the_encoding_is_cp932(self, path: Path):
        path.read_text(encoding="cp932")  # 読めなければ例外

    @pytest.mark.parametrize("path", [SHORTCUTS, UPDATE])
    def test_the_line_endings_are_crlf(self, path: Path):
        raw = path.read_bytes()

        assert b"\r\n" in raw
        assert raw.replace(b"\r\n", b"") .count(b"\n") == 0

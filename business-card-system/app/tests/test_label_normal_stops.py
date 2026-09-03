"""止めただけのものを「落ちた」と記録しない（poc/label.py の見張り役）。

実テストの記録に、2種類の「サーバーが落ちました」が残っていた。**どちらも
サーバーの異常終了ではなかった。**

## 1. ウィンドウを閉じた／Ctrl-C

    08/12 13:38:27  サーバーが落ちました: 終了コード 3221225786

`3221225786` は `0xC000013A`（STATUS_CONTROL_C_EXIT）。Windows で Ctrl-C を
押すか黒い画面を閉じたときの終了コードで、利用者が止めただけ。これを落ちた
ことにすると、本物の異常終了と見分けがつかなくなる。

## 2. 二重起動（ポートが取れない）

    00:10:32  --- 開始 ---          1回目
    00:11:24  --- 開始 ---          2回目（二重起動）
    00:11:26  サーバーが落ちました: 終了コード 1
              | ポート 8100 は使用中です（[WinError 10013]）。

見張り役がこれを異常終了とみなし、**16秒間に6回**立ち上げ直していた。
そのたびに同じ失敗を繰り返すので、本当の理由が画面から流れて見えなくなる。
ポートが空くまで何度やっても結果は変わらないため、立ち上げ直さない。
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from poc import label  # noqa: E402


class TestStoppingIsNotCrashing:
    def test_closing_the_window_on_windows(self):
        assert not label.should_restart(label.WINDOWS_CONTROL_C)

    def test_the_code_is_the_windows_one(self):
        """0xC000013A = STATUS_CONTROL_C_EXIT。"""
        assert label.WINDOWS_CONTROL_C == 0xC000013A

    def test_ctrl_c_on_unix(self):
        assert not label.should_restart(130)

    def test_a_normal_finish(self):
        assert not label.should_restart(0)


class TestAStartupThatCannotSucceedIsNotRetried:
    def test_a_usage_error_is_not_retried(self):
        assert not label.should_restart(2)

    def test_the_port_in_use_says_do_not_retry(self, tmp_path: Path, monkeypatch, capsys):
        """ポートを塞いだ状態で立ち上げ、2（立ち上げ直さない）が返ること。"""
        from PIL import Image

        Image.new("RGB", (300, 190), "white").save(tmp_path / "a.png")

        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        port = held.getsockname()[1]
        try:
            monkeypatch.setattr(
                sys, "argv",
                ["label.py", str(tmp_path), "--port", str(port), "--no-browser"],
            )
            assert label.main() == 2, "立ち上げ直しても同じ、と伝えていない"
        finally:
            held.close()

        assert "使用中です" in capsys.readouterr().err


class TestRealCrashesAreStillCaught:
    def test_an_unexpected_code_is_a_crash(self):
        assert label.should_restart(1)

    def test_a_signal_is_a_crash(self):
        """負の値はシグナルで殺されたということ（メモリ不足など）。"""
        assert label.should_restart(-9)

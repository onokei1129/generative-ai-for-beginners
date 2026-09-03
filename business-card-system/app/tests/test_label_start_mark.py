"""記録に「起動の印」と動いている版を残す。

実テストの記録（1048行・8日ぶん）を調べたとき、次の2つが読めなかった。

1. **どの版で動いていたのか。** 直したはずの不具合の話なのか、直す前の話
   なのかが切り分けられない。
2. **どこからが立ち上げ直しなのか。** 記録が突然途切れている箇所が2つ
   あったが、閉じたのか落ちたのかを区別する手がかりが無かった。

起動のたびに印と版を書けば、どちらも読める。終了の印（`--- 終了 ---`）と
対にすることで、「開始はあるのに終了が無い」＝正常な終わり方をしていない、
と分かる。

**この印では落ちた名刺の印を消さない。** 前回の起動の途中で止まった名刺は、
立ち上げ直したあとも飛ばせるようにしておく必要がある。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from poc import label  # noqa: E402


class TestTheMarkIsWritten:
    def test_it_records_the_running_version(self, tmp_path: Path, monkeypatch):
        log = tmp_path / "ログ.txt"
        monkeypatch.setattr(label, "LOG_PATH", log)
        monkeypatch.setattr(label, "_RUNNING_VERSION", "abc1234 08/10 12:00")

        label.note_start()

        written = log.read_text(encoding="utf-8")
        assert label.START_MARK in written
        assert "abc1234 08/10 12:00" in written

    def test_the_marks_make_a_pair(self, tmp_path: Path, monkeypatch):
        """開始があって終了が無ければ、正常な終わり方をしていないと分かる。"""
        log = tmp_path / "ログ.txt"
        monkeypatch.setattr(label, "LOG_PATH", log)

        label.note_start()
        label.note_clean_stop()

        written = log.read_text(encoding="utf-8")
        assert written.index(label.START_MARK) < written.index(label.CLEAN_EXIT_MARK)


class TestTheMarkDoesNotClearCrashedCards:
    def test_a_card_left_over_from_before_is_still_marked(self, tmp_path: Path):
        """立ち上げ直しても、途中で止まった名刺は飛ばせるままにする。"""
        log = tmp_path / "ログ.txt"
        log.write_text(
            "08/10 10:57:26  開始 OCR 落ちた名刺.pdf\n"
            f"08/10 11:17:53  {label.START_MARK} 版 abc1234 08/10 12:00\n"
            "08/10 11:18:00  開始 OCR ふつうの名刺.pdf\n"
            "08/10 11:18:20  完了 OCR ふつうの名刺.pdf\n",
            encoding="utf-8",
        )

        assert label.cards_that_crashed(log) == {"落ちた名刺.pdf"}

    def test_a_clean_stop_still_clears_them(self, tmp_path: Path):
        """終了の印のほうは、これまでどおり消す。"""
        log = tmp_path / "ログ.txt"
        log.write_text(
            "08/10 10:57:26  開始 OCR 落ちた名刺.pdf\n"
            f"08/10 10:58:00  {label.CLEAN_EXIT_MARK}\n"
            f"08/10 11:17:53  {label.START_MARK} 版 abc1234 08/10 12:00\n",
            encoding="utf-8",
        )

        assert label.cards_that_crashed(log) == set()

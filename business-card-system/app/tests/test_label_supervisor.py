"""サーバーが死んでも作業が止まらないようにする（poc/label.py）。

実テストで、入力画面のサーバーが何度も落ちている。原因は特定できていない。
重い処理は別プロセスに出してあり、親は実測で 62〜65MB しか使わないので、
**親が自分の重さで死んでいるのではない**。

原因究明を待つあいだ、利用者は毎回作業を中断して立ち上げ直している。
そこを構造で解く。

    見張り役（親）
      └ サーバー（子）  ← 死んだら見張り役が立ち上げ直す

利用者から見ると、画面を開き直すだけで作業が続く。立ち上げ直しの手間も、
黒い画面を探す手間も要らない。

**死因も必ず残す。** 見張り役は子の終了コードと標準エラーの末尾を記録に
書く。これまで手がかりが取れなかったのは、落ちたのが記録を書く当人だった
ため。見張り役は別プロセスなので、子が消えても書ける。

    強制終了された（メモリ不足など）  →  終了コードが負（シグナル）
    Python の例外で終わった            →  traceback が標準エラーに残る

止めるとき（Ctrl-C・ウィンドウを閉じる）は立ち上げ直さない。利用者が
終わらせたいのに再び起きてくるのは困る。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402


class TestDecidingToRestart:
    def test_a_killed_server_is_restarted(self):
        """シグナルで殺された（メモリ不足など）。立ち上げ直す。"""
        assert label.should_restart(-9)

    def test_a_crashed_server_is_restarted(self):
        """0以外で終わった。立ち上げ直す。"""
        assert label.should_restart(1)
        assert label.should_restart(3)

    def test_a_clean_exit_is_not_restarted(self):
        """利用者が終わらせた。再び起こさない。"""
        assert not label.should_restart(0)

    @pytest.mark.parametrize("code", [2, 130])
    def test_the_reserved_codes_are_not_restarted(self, code: int):
        """使い方の誤り（2）と Ctrl-C（130）は立ち上げ直さない。"""
        assert not label.should_restart(code)


class TestWhatIsWrittenDown:
    def test_the_exit_code_is_recorded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        log = tmp_path / "ログ.txt"
        monkeypatch.setattr(label, "LOG_PATH", log)

        label.record_server_death(3, ["最後の行"])

        text = log.read_text(encoding="utf-8")
        assert "3" in text

    def test_the_last_error_lines_are_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """死因の手がかり。これまで取れていなかった。"""
        log = tmp_path / "ログ.txt"
        monkeypatch.setattr(label, "LOG_PATH", log)

        label.record_server_death(1, ["Traceback (most recent call last):", "MemoryError"])

        text = log.read_text(encoding="utf-8")
        assert "MemoryError" in text

    def test_a_signal_death_says_it_was_killed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """終了コードが負なら、外から強制終了されたということ。"""
        log = tmp_path / "ログ.txt"
        monkeypatch.setattr(label, "LOG_PATH", log)

        label.record_server_death(-9, [])

        text = log.read_text(encoding="utf-8")
        assert "強制終了" in text
        assert "シグナル 9" in text


class TestNotRestartingForever:
    """立ち上げ直しても即死する状態で、無限に繰り返さないこと。"""

    def test_it_gives_up_after_repeated_quick_deaths(self):
        assert not label.keep_going(deaths=label.MAX_RESTARTS + 1, ran_seconds=1.0)

    def test_a_server_that_ran_a_while_resets_the_count(self):
        """しばらく動いてから落ちたなら、数え直す。別の原因のため。"""
        assert label.keep_going(deaths=label.MAX_RESTARTS + 1, ran_seconds=600.0)

    def test_the_first_few_deaths_are_retried(self):
        assert label.keep_going(deaths=1, ran_seconds=1.0)

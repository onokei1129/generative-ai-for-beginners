"""下書き中の表示（poc/label.py）。

以前は「OCRで下書きしています…（3秒）」という文を出していた。実テストでは
1枚ごとに必ず出るため、文として読むものではなくなる。止まっているのか
動いているのかが一目で分かればよい。

そこで、動いているバーで示し、**文字は秒数だけ**にする。どこまで進んだかは
分からない（OCRは途中経過を返さない）ので、割合ではなく往復するバーにする。

20秒を超えたときの案内だけは残す。実テストで、返ってこない1枚に当たった
ときに先へ進めることが分からず手が止まったため。ただしバーの中には入れず、
下に添える（中を秒数だけにしておくため）。

画面はサーバーを起動しないと動かせないので、ここでは中身を読んで確かめる。
"""

from __future__ import annotations

from pathlib import Path

import pytest

LABEL = Path(__file__).resolve().parents[1] / "poc" / "label.py"


def source() -> str:
    return LABEL.read_text(encoding="utf-8")


class TestTheBarIsThere:
    def test_the_bar_and_its_seconds_have_a_place(self):
        text = source()

        assert 'id="ocrbar"' in text
        assert 'id="ocrsec"' in text

    def test_the_bar_moves_on_its_own(self):
        """割合を出せないので、動き続けるバーで「作業中」を示す。"""
        text = source()

        assert "@keyframes ocrslide" in text
        assert "animation: ocrslide" in text

    def test_it_is_hidden_until_there_is_something_to_show(self):
        assert 'id="ocrbar" hidden' in source()


class TestOnlyTheSecondsGoInside:
    def test_the_bar_shows_the_seconds(self):
        assert "textContent = seconds + '秒'" in source()

    @pytest.mark.parametrize("gone", ["OCRで下書きしています…", "OCRで下書きしています"])
    def test_the_old_sentence_is_gone(self, gone: str):
        """文はバーに置き換えた。戻ると、また読み飛ばされる。"""
        assert gone not in source()

    def test_the_slow_notice_sits_outside_the_bar(self):
        """20秒超えの案内はバーの外（中は秒数だけにするため）。"""
        text = source()

        assert 'id="ocrslow"' in text
        assert "「スキップ」で次へ進めます。" in text


class TestTheBarGoesAwayAgain:
    """出しっぱなしにしないこと。作業中でないのに動いていると誤解を招く。"""

    def test_showbar_can_be_turned_off(self):
        text = source()

        assert "function showBar(seconds)" in text
        assert "if (seconds === null)" in text
        assert "bar.hidden = true;" in text

    def test_it_is_turned_off_when_the_draft_arrives(self):
        assert source().count("showBar(null);") >= 2  # 成功時と失敗時

    def test_the_empty_notice_does_not_leave_a_gap(self):
        """下書き中は説明文が空になる。空の帯が残らないこと。"""
        assert ".source:empty { display: none; }" in source()

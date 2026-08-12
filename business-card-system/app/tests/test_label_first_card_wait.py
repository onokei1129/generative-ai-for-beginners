"""その回の1枚目だけ、待ち時間の理由を画面に出す。

OCRの読み取り機（EasyOCR）は最初の1枚でモデルを読み込む。実測:

    開発機          モデル読み込み込み 16.2秒 / 温まった状態 3.5秒
    利用者の環境    1枚目 45秒 / 2枚目以降ほぼゼロ

2枚目からは先読みが効いて待ち時間はほぼ無い。**問題は1枚目だけ**で、
そのあいだ画面は空欄とバーだけになる。何が起きているか分からないため、
実テストでは「立ち上げ時に既にサーバが落ちている」と受け取られた。

読み込み時間そのものは減らせない（言語は ja,en の最小構成で、削る余地が
ない）。減らせない待ち時間は、**理由と見通しを出す**。

「20秒を超えたらスキップできる」という既存の案内とは分けて出す。1枚目は
飛ばしても次で同じだけ待つので、スキップを勧めるのは誤った案内になる。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from poc import label  # noqa: E402


def show_bar_body() -> str:
    page = label.PAGE
    start = page.index("function showBar(seconds)")
    return page[start : page.index("\n}", start)]


class TestTheFirstCardExplainsItself:
    def test_it_says_the_first_card_is_the_slow_one(self):
        body = show_bar_body()

        assert "1枚目" in body, "1枚目だけの話だと伝えていない"
        assert "45秒" in body, "どれくらい待つのかを出していない"

    def test_it_says_the_rest_are_fast(self):
        """見通しが無いと、この先ずっとこの調子だと受け取られる。"""
        body = show_bar_body()

        assert "2枚目" in body

    def test_it_does_not_tell_them_to_skip(self):
        """1枚目は飛ばしても次で同じだけ待つ。スキップを勧めるのは誤り。"""
        body = show_bar_body()
        first_card_branch = body[body.index("state.ocrReady") :]
        # 分岐は return で閉じ、スキップの案内へ落ちない。
        assert "return;" in first_card_branch.split("スキップ")[0]


class TestItSwitchesBackAfterTheFirstDraft:
    def test_the_flag_starts_false(self):
        assert re.search(r"ocrReady:\s*false", label.PAGE), "初期値が偽になっていない"

    def test_the_flag_is_set_when_a_draft_arrives(self):
        assert "state.ocrReady = true" in label.PAGE, "下書きが返っても切り替えていない"

    def test_the_usual_message_comes_back(self):
        """2枚目以降は、これまでどおり20秒でスキップを案内する。"""
        body = show_bar_body()

        assert "「スキップ」で次へ進めます" in body

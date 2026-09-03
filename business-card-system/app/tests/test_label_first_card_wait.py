"""その回の最初のうちは、待ち時間の理由を画面に出す。

OCRの読み取り機（EasyOCR）は一度モデルを読み込む必要があり、そこだけ桁違いに
時間がかかる。実測:

    開発機          モデル読み込み込み 16.2秒 / 温まった状態 3.5秒
    利用者の環境    1枚目 45秒 / 2枚目以降ほぼゼロ

1枚目は軽い読み取り機で下書きするので数秒で返るが、**モデルの読み込みは
2枚目の先読みに移るだけ**で、無くなるわけではない。利用者が1枚目を早く
終えると、2枚目でその待ちに行き当たる。だから1枚目だけでなく、最初の2枚ぶんの
下書きが返るまでこの文を出す。

読み込み時間そのものは減らせない（言語は ja,en の最小構成で、削る余地が
ない）。減らせない待ち時間は、**理由と見通しを出す**。何が起きているか
分からないと「サーバーが落ちている」と受け取られる。実テストでは、実際に
この待ちの最中に黒い画面を閉じられていた（記録の終了コード 3221225786）。

「20秒を超えたらスキップできる」という既存の案内とは分けて出す。最初の1枚は
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
    def test_it_says_it_is_only_at_the_start(self):
        body = show_bar_body()

        assert "この回の最初だけ" in body, "最初だけの話だと伝えていない"
        assert "40秒" in body, "どれくらい待つのかを出していない"

    def test_it_says_the_rest_are_fast(self):
        """見通しが無いと、この先ずっとこの調子だと受け取られる。"""
        body = show_bar_body()

        assert "そのあとは待ち時間はほぼありません" in body

    def test_it_does_not_tell_them_to_skip(self):
        """1枚目は飛ばしても次で同じだけ待つ。スキップを勧めるのは誤り。"""
        body = show_bar_body()
        first_card_branch = body[body.index("state.drafts") :]
        # 分岐は return で閉じ、スキップの案内へ落ちない。
        assert "return;" in first_card_branch.split("スキップ")[0]


class TestItSwitchesBackAfterTheFirstDrafts:
    def test_the_count_starts_at_zero(self):
        assert re.search(r"drafts:\s*0", label.PAGE), "初期値が0になっていない"

    def test_the_count_goes_up_when_a_draft_arrives(self):
        assert "state.drafts += 1" in label.PAGE, "下書きが返っても数えていない"

    def test_it_covers_the_second_card_too(self):
        """1枚目を軽い読み取り機にすると、モデルの読み込みは2枚目に移る。"""
        assert "state.drafts < 2" in label.PAGE, "2枚目を含めていない"

    def test_the_usual_message_comes_back(self):
        """そのあとは、これまでどおり20秒でスキップを案内する。"""
        body = show_bar_body()

        assert "「スキップ」で次へ進めます" in body

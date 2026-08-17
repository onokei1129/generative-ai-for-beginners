"""下書きが繋がらなかったときは、一度だけ掛け直す。

実テスト（版 0f9608c、7枚目）で、**画像は出ているのに下書きだけが**
`TypeError: Failed to fetch` になった。これは応答の中身の話ではなく、
繋ぐこと自体に失敗している。画像が出ている以上サーバーは生きているので、
一時的に応答しなかったことになる——見張り役がサーバーを立ち上げ直した
直後なら、立ち上がるまでの数秒がこれにあたる。

そのまま「取得できませんでした」と出すと、利用者は空欄から手入力する
しかない。掛け直せば済む場面なので、一度だけ待って試す。

**理由の出し分けも足す。** 画像の側は前から「サーバーが落ちている」と
「この1枚だけの問題」を分けていたが、下書きの側は一文だけで、何が起きた
のか分からなかった。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from poc import label  # noqa: E402


def ask_body() -> str:
    page = label.PAGE
    start = page.index("async function askForLabel(url)")
    return page[start : page.index("\n}", start)]


class TestItTriesAgain:
    def test_the_draft_goes_through_the_retry(self):
        """`show` が素の fetch ではなく掛け直しつきを使っている。"""
        assert "data = await askForLabel(url)" in label.PAGE

    def test_it_waits_before_trying_again(self):
        """立ち上げ直しの最中に即座に掛け直しても、また繋がらない。"""
        body = ask_body()

        assert "setTimeout" in body, "待たずに掛け直している"
        assert "2000" in body, "待ち時間が入っていない"

    def test_it_gives_up_after_one_more_try(self):
        """何度も掛け直すと、本当に落ちているとき画面が固まる。"""
        body = ask_body()

        assert body.count("fetch(") == 2, "掛け直しは一度だけにする"


class TestItSaysWhichKindOfFailure:
    def test_it_checks_whether_the_server_is_alive(self):
        assert "async function serverIsAlive()" in label.PAGE
        assert "await serverIsAlive()" in label.PAGE, "下書きの失敗で確かめていない"

    def test_it_tells_them_the_server_is_down(self):
        """落ちているときの案内を出す。

        文言は1か所（`serverDiedNotice`）にまとめてある——画像・下書き・
        書き出しの3か所で書き分けると、直しが片方に残る。文の並びではなく
        **その案内を使っているか**を見る。
        """
        assert "function serverDiedNotice(" in label.PAGE
        assert "サーバーが応答していません" in label.PAGE
        assert label.PAGE.count("serverDiedNotice") >= 2, "案内を使っていない"

    def test_it_tells_them_it_is_just_this_card(self):
        assert "この1枚だけの問題です）。空欄から入力してください。" in label.PAGE

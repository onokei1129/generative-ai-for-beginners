"""名刺を切り替えたら、前の名刺の書き出しメッセージを消す（poc/label.py）。

「この1枚を調べる」を押すと、読み取りをファイルに書き出して案内を出す。

    書き出しました: …¥read-cards¥読み取り-(会社名)_迎 亮一.pdf.txt
    このファイルを送ってください。

この案内が**次の名刺に移っても残る**。実テストの画面では、24枚目
（Donuts / 木村 央志）を見ているのに、19枚目（迎 亮一）のファイルを
送るよう案内されていた。

見た目の粗ではない。**間違ったファイルを送らせる**案内で、こちらは
別の名刺の読み取りを見ながら原因を探すことになる。項目のずれを調べる
やり取りそのものが狂う。

`show` は画像・OCRの文字・保存済みの表示を消しているが、この欄だけ
消していなかった。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402


def body_of_show() -> str:
    """`show` の中身（次の関数の手前まで）。"""
    start = label.PAGE.index("async function show(i)")
    rest = label.PAGE[start:]
    end = rest.index("\nfunction ", 1)
    return rest[:end]


class TestTheExportNoteDoesNotFollowTheNextCard:
    def test_show_clears_it(self):
        assert "'inspected'" in body_of_show(), (
            "名刺を切り替えても書き出しメッセージが残る"
        )

    def test_it_is_cleared_not_rewritten(self):
        """空にする。前の名刺の文言を残したまま書き換えない。"""
        for line in body_of_show().splitlines():
            if "'inspected'" in line:
                assert "= ''" in line, f"空にしていない: {line.strip()}"
                return
        raise AssertionError("書き出しメッセージを消していない")

    def test_the_other_notices_are_still_cleared(self):
        """一緒に消しているものを、直したはずみで落とさない。"""
        shown = body_of_show()
        for element in ("'imgerror'", "'ocrtext'", "'saved'"):
            assert element in shown, f"{element} を消していない"

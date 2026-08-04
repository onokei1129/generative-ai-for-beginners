"""ロゴに埋もれた氏名を拾う（実テスト 29枚目・高橋 佳広）。

読み取りはこうなっていた。

    easyocr    絵師
               回山山口   高橋 佳広      ← 本来の氏名。左はロゴの読み崩れ
    tesseract  だ こう                   ← 絵柄の読み崩れ
               GOUKAIDO 高橋   マン
               YOSHIHIRO TAKAHASHI

出ていた項目は 姓『TAKAHASHI』名『YOSHIHIRO』、ふりがな『だ』『こう』。

3つの取り違えが重なっている。

1. `絵師` を氏名の行にしていた。**区切りが無い**ので姓と名に割れず、姓だけ
   が埋まる。同じ読み取りの中に区切りのある `高橋 佳広` があるのだから、
   そちらを先に見るべき。

2. `回山山口   高橋 佳広` を切らずに 姓『回山山口』名『高橋佳広』にして
   いた。氏名の姓と名は大きく空けて印字されるため、段組みと同じ形になる
   ——という理由で切らずにいる（`オロブスキー    スタニスラフ`）。しかし
   **右側だけで姓と名が揃っている**なら、大きい空白のほうは段の切れ目。

3. `だ こう` をふりがなにしていた。姓の読みが1文字の氏名は無い。

3は空欄になるだけだが、1と2は誤った氏名が登録される。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields, split_columns  # noqa: E402

EASYOCR = [
    "絵師",
    "回山山口   高橋 佳広",
    "yOSHIHIIRO TAKAHASHI",
    "PN 貴橋由宏",
    "テ181-0002 東京都三鷹市牟礼5-10-18",
    "CIP 090-6795-1305",
    "E-mail yoshiring@outlookjp",
]

TESSERACT = [
    "GAM,",
    "だ こう",
    "国",
    "GOUKAIDO 高橋   マン",
    "YOSHIHIRO TAKAHASHI",
    "F 181-0002 東京 都 三 鷹 市 牟礼 5-10-18",
    "C/P : 090-6795-1305",
]


class TestTheNameIsFound:
    def test_the_name_beside_the_logo_is_taken(self):
        got = parse_fields(EASYOCR)["fields"]

        assert (got["last_name"], got["first_name"]) == ("高橋", "佳広")

    def test_the_logo_word_is_not_the_surname(self):
        got = parse_fields(EASYOCR)["fields"]

        assert got["last_name"] != "絵師"


class TestSplittingTheLine:
    def test_a_whole_name_on_one_side_means_a_column_break(self):
        assert split_columns("回山山口   高橋 佳広") == ["回山山口", "高橋 佳広"]

    @pytest.mark.parametrize(
        "line",
        [
            "オロブスキー    スタニスラフ",
            "迎　　　亮一",
            "山田　　太郎",
        ],
    )
    def test_a_widely_spaced_name_is_still_kept_whole(self, line: str):
        """氏名の姓と名のあいだの空白は、段の切れ目ではない。"""
        assert split_columns(line) == [line.strip()]


class TestTheFurigana:
    def test_a_one_character_surname_reading_is_not_furigana(self):
        got = parse_fields(TESSERACT)["fields"]

        assert got["last_name_kana"] != "だ"
        assert got["first_name_kana"] != "こう"

    def test_a_real_reading_is_still_taken(self):
        got = parse_fields(["株式会社サンプル", "やまだ たろう", "山田 太郎"])["fields"]

        assert (got["last_name_kana"], got["first_name_kana"]) == ("やまだ", "たろう")

"""字が1文字ずつ離れて読まれた氏名（実テスト 21枚目・高岡 徹）。

読み取りはこうなっていた。

    高 岡   徹          ← 姓の中も空いている。名は漢字1文字
    TEL 070-9338-4365   ← 印字は「TEL」

出ていた項目は 姓『高』名『岡』、電話は空で携帯に入っていた。

## 姓が1文字ずつに割れる

名刺は姓と名を大きく空けて印字する。字づめが広いと**姓の中の字と字も
空いて読まれる**ため、空白が2種類できる。

    高 岡   徹
      ↑ 字の間   ↑ 姓と名の間

これまでは「右端が1文字なら段の切れ目」として切っていた。`藤   し`
（`伊藤 しの` の読み崩れ）を氏名にしないための規則だが、**漢字1文字の名**
（徹・修・誠）まで巻き込んでいた。かなと漢字で分ける——かな1文字は名では
ないが、漢字1文字は名として実在する。

## 印字された種別を数字より先に見る

`070` は携帯の番号だが、この名刺は `TEL` と印字している。**印字が種別を
示しているなら、番号の形より印字を先に見る**。名刺のとおりに登録できないと、
入力する人が毎回入れ替える手間になる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields, split_columns  # noqa: E402

CARD = [
    "高岡徹税理士事務所",
    "公認会計士 税理士",
    "たかおか   とおる",
    "高 岡   徹",
    "テ102-0071",
    "東京都千代田区富士見]丁目3-I]",
    "TEL 070-9338-4365",
    "メールアドレス torucpa@gmailcom",
]


class TestTheSpreadOutName:
    def test_the_surname_is_joined_back(self):
        got = parse_fields(CARD)["fields"]

        assert (got["last_name"], got["first_name"]) == ("高岡", "徹")

    def test_the_line_is_not_cut_at_the_wide_gap(self):
        assert split_columns("高 岡   徹") == ["高 岡   徹"]

    @pytest.mark.parametrize(
        ("line", "last", "first"),
        [
            ("高 岡   徹", "高岡", "徹"),
            ("冨田   修", "冨田", "修"),
            ("山 田   誠", "山田", "誠"),
        ],
    )
    def test_a_one_kanji_given_name_is_taken(self, line: str, last: str, first: str):
        got = parse_fields(["株式会社サンプル", line])["fields"]

        assert (got["last_name"], got["first_name"]) == (last, first)

    def test_a_one_kana_tail_is_still_a_column_break(self):
        """`藤   し` は `伊藤 しの` の読み崩れ。`し` は名ではない。"""
        assert split_columns("藤   し") == ["藤", "し"]

    def test_a_whole_name_beside_a_logo_is_still_cut(self):
        """実テスト 29枚目。右側だけで姓と名が揃っているなら段の切れ目。"""
        assert split_columns("回山山口   高橋 佳広") == ["回山山口", "高橋 佳広"]


class TestThePrintedLabelWins:
    def test_tel_keeps_a_mobile_looking_number(self):
        got = parse_fields(CARD)["fields"]

        assert got["tel"] == "070-9338-4365"
        assert got["mobile"] == ""

    def test_a_mobile_label_still_means_mobile(self):
        got = parse_fields(["株式会社サンプル", "携帯 070-1234-5678"])["fields"]

        assert got["mobile"] == "070-1234-5678"
        assert got["tel"] == ""

    def test_an_unlabelled_mobile_number_is_still_a_mobile(self):
        """印字が無ければ、これまでどおり番号の形で見分ける。"""
        got = parse_fields(["株式会社サンプル", "090-1234-5678"])["fields"]

        assert got["mobile"] == "090-1234-5678"

"""韓国名の姓と名の並び（実テスト 21・23枚目・Smilegate）。

英字の氏名は「名 姓」の順として扱っている（`German Kurnikov` → 姓
`Kurnikov`）。韓国の名刺はどちらの並びもあり、形だけでは決められない。

    21枚目  Yeo Seunghwan    姓 Yeo    ← 姓が先
    8枚目   Sangeon Lee      姓 Lee    ← 姓が後ろ

21枚目は 姓『Seunghwan』名『Yeo』と**逆**になっていた。

## どう見分けるか

2つの手がかりを使う。

1. **読点で区切られている**（23枚目 `Jeong, Sun Ho`）。読点の前が姓という
   書き方は言語を問わない。いちばん確かな手がかり。
2. **韓国の姓の語**が前にあるとき。韓国の姓は数が限られている。

2つ目は語彙に頼るので、**西洋の名と紛れやすい語は入れない**。`Kim`・
`Lee`・`Park`・`Han`・`Song`・`Oh` は英語圏の人名にもあるため、入れると
`Kim Anderson` の姓が `Kim` になってしまう。姓が後ろにある書き方
（`Sangeon Lee`）は今までどおりの規則で正しく取れるので、語彙に入れる
必要もない。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


def name_of(*lines: str) -> tuple[str, str]:
    got = parse_fields(["Smilegate Holdings, Inc.", *lines])["fields"]
    return got["last_name"], got["first_name"]


class TestACommaMarksTheSurname:
    """実テスト 23枚目。`Jeong, Sun Ho` は 姓 Jeong ／ 名 Sun Ho。"""

    def test_the_smilegate_card(self):
        assert name_of("Jeong, Sun Ho", "Team Manager") == ("Jeong", "Sun Ho")

    @pytest.mark.parametrize(
        ("printed", "last", "first"),
        [
            ("Jeong, Sun Ho", "Jeong", "Sun Ho"),
            ("Lee, Sangeon", "Lee", "Sangeon"),
            ("Smith, John", "Smith", "John"),
            ("Kurnikov, German", "Kurnikov", "German"),
        ],
    )
    def test_the_part_before_the_comma_is_the_surname(self, printed: str, last: str, first: str):
        assert name_of(printed) == (last, first)


class TestAKoreanSurnameInFrontComesFirst:
    """実テスト 21枚目。`Yeo Seunghwan` は 姓 Yeo ／ 名 Seunghwan。"""

    def test_the_smilegate_card(self):
        assert name_of("Yeo Seunghwan", "Vice President") == ("Yeo", "Seunghwan")

    @pytest.mark.parametrize(
        ("printed", "last", "first"),
        [
            ("Yeo Seunghwan", "Yeo", "Seunghwan"),
            ("Choi Minjun", "Choi", "Minjun"),
            ("Hwang Jiwoo", "Hwang", "Jiwoo"),
            ("Kwon Seoyeon", "Kwon", "Seoyeon"),
        ],
    )
    def test_it_is_taken_as_the_surname(self, printed: str, last: str, first: str):
        assert name_of(printed) == (last, first)


class TestTheUsualOrderIsUnchanged:
    @pytest.mark.parametrize(
        ("printed", "last", "first"),
        [
            ("Sangeon Lee", "Lee", "Sangeon"),          # 実テスト 8枚目
            ("German Kurnikov", "Kurnikov", "German"),   # 実テスト 10枚目
            ("Shunsuke Katsumata", "Katsumata", "Shunsuke"),
            ("John Smith", "Smith", "John"),
        ],
    )
    def test_the_last_word_is_the_surname(self, printed: str, last: str, first: str):
        assert name_of(printed) == (last, first)

    @pytest.mark.parametrize("printed", ["Kim Anderson", "Lee Harvey", "Park Johnson"])
    def test_words_that_clash_with_western_names_are_not_used(self, printed: str):
        """`Kim`・`Lee`・`Park` は英語圏の人名にもある。語彙に入れない。"""
        last, _ = name_of(printed)

        assert last == printed.split()[1]

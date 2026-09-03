"""国・地域の語を氏名にしない（実テスト 20枚目・LUNATE games）。

名刺には `Representative in Japan` と印字されている。tesseract はそのとおりに
読んで役職に入れたが、easyocr は `Represenialivein Japan` と読み崩し、これが
**氏名**として登録されていた。

    姓  Japan
    名  Represenialivein

`Representative` は既に「氏名ではない語」に入れてあるが、読み崩れた
`Represenialivein` は一致しない。読み崩れる語をすべて数え上げることはできない。

そこで**国・地域の語**を見る。役職や部署では担当範囲としてよく出るが
（`Head of Japan | APAC`・`日本支社`）、人名にはまず現れない。

空欄になるだけなら入力する人が気づく。誤った氏名は気づかれずに登録される。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheLunateCard:
    """実テスト 20枚目。"""

    LINES = [
        "LUAATE",
        "オロブスキー    スタニスラフ",
        "ORLOvsKIysTANISLAV",
        "日本支社",
        "Represenialivein Japan",
        "PHONE 捕帯 070 4100 5747",
    ]

    def test_the_misread_title_is_not_a_name(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["last_name"] != "Japan"
        assert "Represenialivein" not in f"{got['last_name']}{got['first_name']}"

    def test_the_title_is_still_found(self):
        got = parse_fields(self.LINES + ["Representative in Japan"])["fields"]

        assert got["title"] == "Representative in Japan"


class TestRegionWordsAreNotNames:
    @pytest.mark.parametrize(
        "line",
        [
            "Represenialivein Japan",
            "Manager Japan",
            "Sales Asia",
            "Head APAC",
            "Director EMEA",
            "Lead Europe",
        ],
    )
    def test_the_line_is_rejected(self, line: str):
        got = parse_fields(["Acme Inc.", line])["fields"]

        assert not got["last_name"] and not got["first_name"]


class TestRealNamesStillWork:
    @pytest.mark.parametrize(
        ("line", "last", "first"),
        [
            ("German Kurnikov", "Kurnikov", "German"),
            ("Sangeon Lee", "Lee", "Sangeon"),
            ("Shunsuke Katsumata", "Katsumata", "Shunsuke"),
        ],
    )
    def test_the_name_is_taken(self, line: str, last: str, first: str):
        got = parse_fields(["Acme Inc.", line])["fields"]

        assert (got["last_name"], got["first_name"]) == (last, first)

    def test_a_name_that_merely_contains_the_letters_is_fine(self):
        """語の一部としての一致で弾かないこと（`Regina` に `region` は無い）。"""
        got = parse_fields(["Acme Inc.", "Regina Asiado"])["fields"]

        assert got["last_name"] and got["first_name"]

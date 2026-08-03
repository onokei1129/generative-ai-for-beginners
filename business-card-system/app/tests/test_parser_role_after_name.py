"""氏名のあとに役職を並べた行（実テスト 14枚目）。

    印字  Alex Kudishov ▪ Executive Producer
    読み  Alex Kudishov Executive Producer     ← 区切りが落ちた

姓『Kudishov Executive Producer』／ 名『Alex』になっていた。

役職が**先**にある行（`代表取締役 ユン ソクン`）はすでに分けている。
これはその裏返しで、役職が**後ろ**にある形。英語の名刺ではこちらが普通。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import merge_fields, parse_fields  # noqa: E402


class TestARoleAfterTheName:
    def test_the_role_is_split_off(self):
        got = parse_fields(["Alex Kudishov Executive Producer"])["fields"]

        assert got["last_name"] == "Kudishov"
        assert got["first_name"] == "Alex"
        assert got["title"] == "Executive Producer"

    def test_a_separator_between_them_is_handled(self):
        got = parse_fields(["Alex Kudishov ・ Executive Producer"])["fields"]

        assert got["last_name"] == "Kudishov"
        assert got["title"] == "Executive Producer"

    def test_a_role_before_the_name_still_works(self):
        """先にある場合（既存の動き）を壊さないこと。"""
        got = parse_fields(["代表取締役 ユン ソクン"])["fields"]

        assert got["title"] == "代表取締役"
        assert got["last_name"] == "ユン"

    def test_a_line_that_is_only_a_role_is_not_split(self):
        got = parse_fields(["Executive Producer"])["fields"]

        assert got["title"]
        assert not got["last_name"]

    def test_a_name_without_a_role_is_untouched(self):
        got = parse_fields(["Alex Kudishov"])["fields"]

        assert got["last_name"] == "Kudishov"
        assert got["first_name"] == "Alex"
        assert not got["title"]

    def test_a_japanese_compound_role_is_not_split(self):
        """日本語の役職は修飾語を前に付けて1語で書く。同じ規則を当てると
        `シニア` を氏名にしてしまう（この修正の途中で実際に切った）。"""
        got = parse_fields(["シニアエンジニア"])["fields"]

        assert got["title"] == "シニアエンジニア"
        assert not got["last_name"]

    def test_a_role_written_as_one_word_is_not_split(self):
        got = parse_fields(["担当部長"])["fields"]

        assert got["title"] == "担当部長"
        assert not got["last_name"]


class TestTheEsDigitalCard:
    """実テスト 14枚目。姓『Kudishov Executive Producer』になっていた。"""

    EASYOCR = """Espigital
「M「
Alex Kudishov Executive Producer
akudishov@esdigitaldev wwwesdigitalgames"""
    TESSERACT = """ESDigital
[GAMES|
Alex Kudishov ・ Executive Producer
akudishov@esdigital.dev » www.esdigital.games"""

    def fields(self) -> dict:
        parsed = [parse_fields(t.splitlines()) for t in (self.EASYOCR, self.TESSERACT)]
        return merge_fields(parsed)["fields"]

    def test_the_name_no_longer_holds_the_role(self):
        got = self.fields()

        assert got["last_name"] == "Kudishov"
        assert got["first_name"] == "Alex"

    def test_the_role_lands_in_the_title(self):
        assert self.fields()["title"] == "Executive Producer"

    def test_the_other_fields_are_still_taken(self):
        got = self.fields()

        assert got["company_name"] == "ESDigital"
        assert got["email"] == "akudishov@esdigital.dev"

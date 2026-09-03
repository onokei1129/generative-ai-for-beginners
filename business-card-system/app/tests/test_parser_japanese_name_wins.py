"""漢字の氏名があれば、英字より優先する（実テスト 24枚目・ぴっくる）。

名刺には和英が併記されている。

    代表取締役　星 山 孝 明
    Hoshiyama Takaaki

これが 姓『Takaaki』名『Hoshiyama』と**逆**になっていた。英字の氏名は
「名 姓」の順として扱うが、日本の名刺のローマ字は「姓 名」の順で書くこと
が多く、形だけでは決められない。

**漢字が読めているなら、そちらを使えばよい。** 英字は補助の表記で、
姓と名のどちらが先かも決まっていない。

漢字の氏名が役職と同じ行に印字されていると（`代表取締役　星 山 孝 明`）、
その行は役職の語を含むため氏名として見つからない。別の行に英字の氏名が
あるとそちらが先に採られ、漢字が使われないままになっていた。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestThePickleCard:
    """実テスト 24枚目。"""

    LINES = [
        "代表取締役 星 山 孝 明",
        "Hoshiyama Takaaki",
        "有限会社ぴっくる",
        "〒180-0022 東京都武蔵野市境1-3-4",
        "TEL・FAX 0422-53-4170",
    ]

    def test_the_kanji_name_is_used(self):
        got = parse_fields(self.LINES)["fields"]

        assert (got["last_name"], got["first_name"]) == ("星山", "孝明")

    def test_the_title_is_still_taken(self):
        assert parse_fields(self.LINES)["fields"]["title"] == "代表取締役"

    def test_the_other_fields_are_unaffected(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["company_name"] == "有限会社ぴっくる"
        assert got["postal_code"] == "180-0022"


class TestJapaneseWinsOverLatin:
    @pytest.mark.parametrize(
        ("japanese", "latin", "last", "first"),
        [
            ("代表取締役 星 山 孝 明", "Hoshiyama Takaaki", "星山", "孝明"),
            ("部長 山田 太郎", "Taro Yamada", "山田", "太郎"),
            ("取締役 鈴木 一郎", "Ichiro Suzuki", "鈴木", "一郎"),
        ],
    )
    def test_the_kanji_line_wins(self, japanese: str, latin: str, last: str, first: str):
        got = parse_fields(["株式会社サンプル", japanese, latin])["fields"]

        assert (got["last_name"], got["first_name"]) == (last, first)


class TestLatinOnlyCardsAreUnchanged:
    @pytest.mark.parametrize(
        ("line", "last", "first"),
        [
            ("Sangeon Lee", "Lee", "Sangeon"),          # 実テスト 8枚目
            ("German Kurnikov", "Kurnikov", "German"),   # 実テスト 10枚目
            ("Yeo Seunghwan", "Yeo", "Seunghwan"),       # 実テスト 21枚目
        ],
    )
    def test_the_latin_name_is_still_taken(self, line: str, last: str, first: str):
        """漢字が無ければ、これまでどおり英字を使う。"""
        got = parse_fields(["Acme Inc.", "Vice President", line])["fields"]

        assert (got["last_name"], got["first_name"]) == (last, first)

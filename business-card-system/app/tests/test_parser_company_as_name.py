"""会社名の切れ端を氏名にしない（実テスト 8枚目・Causal Foundry）。

    印字   ジョンソン 裕子
           Causal Foundry G.K.

    出力   姓『Foundry GK』  名『Causal』

姓と名がそろって**会社名の語**でできている。人の名前ではない。

英字の氏名は姓と名が空白で分かれているため、社名の並び（`Causal Foundry
G.K.`）と同じ形になる。どちらも「英字の語が2つ以上」で、形だけでは
見分けられない。**社名と突き合わせる**しかない。

語がすべて社名に含まれるときだけ落とす。社名が創業者の名字である場合
（`John Smith` と `Smith & Co`）は `john` が社名に無いので残る。

日本語の氏名には掛けない。`高岡 徹` と `高岡徹税理士事務所` のように、
社名が氏名を丸ごと含むのが普通のため。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheCausalFoundryCard:
    """社名が2行に分かれて読まれ、氏名が2行にまたがる規則に当たっていた。"""

    LINES = ["Causal", "Foundry GK", "Chief Business Officer", "yuko@causalfoundry.ai"]

    def test_the_company_words_are_not_a_name(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["last_name"] == ""
        assert got["first_name"] == ""

    @pytest.mark.parametrize("suffix", ["GK", "G.K.", "KK", "K.K."])
    def test_a_japanese_company_suffix_is_not_a_surname(self, suffix: str):
        got = parse_fields(["Causal", f"Foundry {suffix}", "yuko@causalfoundry.ai"])["fields"]

        assert got["last_name"] == ""

    def test_the_company_itself_is_still_kept(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["company_name"]


class TestRealNamesAreKept:
    def test_a_founder_named_company_keeps_the_person(self):
        """`Smith & Co` の `John Smith`。`john` は社名に無い。"""
        got = parse_fields(["Smith & Co", "John Smith", "john@smith.example"])["fields"]

        assert (got["last_name"], got["first_name"]) == ("Smith", "John")

    def test_a_japanese_name_is_untouched(self):
        """`高岡徹税理士事務所` の `高岡 徹`（実テスト 21枚目）。"""
        got = parse_fields([
            "高岡徹税理士事務所",
            "高 岡   徹",
            "TEL 070-9338-4365",
        ])["fields"]

        assert (got["last_name"], got["first_name"]) == ("高岡", "徹")

    @pytest.mark.parametrize(
        ("line", "last", "first"),
        [
            ("Sangeon Lee", "Lee", "Sangeon"),
            ("German Kurnikov", "Kurnikov", "German"),
        ],
    )
    def test_an_unrelated_english_name_is_kept(self, line: str, last: str, first: str):
        got = parse_fields(["NEXON GAMES", line])["fields"]

        assert (got["last_name"], got["first_name"]) == (last, first)

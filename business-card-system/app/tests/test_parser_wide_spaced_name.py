"""姓と名を大きく空けて印字した氏名（実テスト 20枚目・LUNATE games）。

名刺は姓と名のあいだを大きく空けて印字することが多い。

    オロブスキー    スタニスラフ
    迎　　　亮一

ところが、その空白は**左右2段組み**の見分けにも使っている。段組みとして
切ると氏名が半分になり、残った `オロブスキー` をさらに姓と名に分けて

    姓 オロ  ／  名 ブスキー

となっていた。行全体が氏名として読めるなら、それは1つの項目であって
2つの段ではない。切らずに渡す。

2段組みの行はこの判定に当たらない。右段に連絡先や社名が来るため、行全体が
氏名の形（英字の語だけ、または日本語の氏名）にならない。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields, split_columns  # noqa: E402


class TestTheLunateCard:
    def test_the_name_is_not_cut_in_half(self):
        got = parse_fields([
            "LUAATE",
            "オロブスキー    スタニスラフ",
            "日本支社",
            "PHONE 捕帯 070 4100 5747",
        ])["fields"]

        assert (got["last_name"], got["first_name"]) == ("オロブスキー", "スタニスラフ")


class TestAWideSpacedNameStaysWhole:
    @pytest.mark.parametrize(
        "line",
        [
            "オロブスキー    スタニスラフ",
            "迎　　　亮一",
            "山田　　　太郎",
            "German        Kurnikov",
        ],
    )
    def test_it_is_not_split(self, line: str):
        assert split_columns(line) == [line.strip()]


class TestRealTwoColumnLinesStillSplit:
    @pytest.mark.parametrize(
        "line",
        [
            "Sangeon Lee            T +82.2.6421.7777",
            "時NEXロN                  NEXON GAMES",
            "Team Member                        E eonlee@nexongames.co.kr",
            "Planning & Coordination Dept         F +82.2.569.6448",
        ],
    )
    def test_it_is_still_split(self, line: str):
        assert len(split_columns(line)) == 2

    def test_the_nexon_card_is_unchanged(self):
        """実テスト 8枚目。2段組みの読み取りが崩れていないこと。"""
        got = parse_fields([
            "時NEXロN                  NEXON GAMES",
            "GAMES                  2621, Nambusunhwan-ro,",
            "Gangnam-gu, Seoul, Korea,",
            "06267",
            "Sangeon Lee            T +82.2.6421.7777",
            "Team Member                        E eonlee@nexongames.co.kr",
        ])["fields"]

        assert (got["last_name"], got["first_name"]) == ("Lee", "Sangeon")
        assert got["company_name"] == "NEXON GAMES"
        assert got["postal_code"] == "06267"

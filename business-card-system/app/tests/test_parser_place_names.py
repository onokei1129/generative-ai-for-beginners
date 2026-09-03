"""住所の行を氏名にしない（実テスト 20枚目・Smilegate）。

    姓  Gyeonggi-do
    名  Republic ofKorea

どちらも住所の一部。**これは直前の修正で持ち込んだ不具合**で、23枚目の
`Jeong, Sun Ho` を氏名として拾うために「最初の語の直後の読点」を許した
ところ、住所の行まで同じ形に当てはまってしまった。

    Jeong, Sun Ho            ← 拾いたい
    Gyeonggi-do, Republic…   ← 拾ってはいけない

そのときのコメントに「2つ目以降にも読点がある行は住所なので通さない」と
書いたが、**読点が1つだけの住所の行**を見落としていた。

見分けは行政区画の接尾辞で行う。`-do`（道）・`-ku`（区）・`-gu`（区）・
`-si`（市）・`-ro`（路）などは住所にしか出てこない。

`Republic` も氏名ではない語に加える。`Republic of Korea` の `Korea` は
既に入れてあるが、OCRが空白を落として `ofKorea` になると語として一致
しないため、`Republic` のほうでも止める。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import _looks_like_person_name, parse_fields  # noqa: E402


class TestTheSmilegateCard:
    """実テスト 20枚目。"""

    LINES = [
        "Smilegate Holdings, Inc.",
        "8F, First Tower 55, Bundang-ro,",
        "Bundang-gu, Seongnam-si,",
        "Gyeonggi-do, Republic ofKorea",
        "Vice President",
    ]

    def test_the_address_line_is_not_a_name(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["last_name"] != "Gyeonggi-do"
        assert got["first_name"] != "Republic ofKorea"

    def test_the_name_is_still_taken_when_it_is_there(self):
        got = parse_fields([*self.LINES, "Yeo Seunghwan"])["fields"]

        assert (got["last_name"], got["first_name"]) == ("Yeo", "Seunghwan")


class TestAddressLinesAreNeverNames:
    @pytest.mark.parametrize(
        "line",
        [
            "Gyeonggi-do, Republic ofKorea",
            "Chiyoda-ku, Tokyo",
            "Bundang-gu, Seongnam-si",
            "Gangnam-gu, Seoul",
            "Sotokanda, Chiyoda-ku",
            "Republic of Korea",
        ],
    )
    def test_it_is_rejected(self, line: str):
        assert not _looks_like_person_name(line)


class TestRealNamesStillWork:
    @pytest.mark.parametrize(
        ("line", "last", "first"),
        [
            ("Jeong, Sun Ho", "Jeong", "Sun Ho"),      # 実テスト 23枚目
            ("Yeo Seunghwan", "Yeo", "Seunghwan"),     # 実テスト 21枚目
            ("Sangeon Lee", "Lee", "Sangeon"),         # 実テスト 8枚目
            ("German Kurnikov", "Kurnikov", "German"), # 実テスト 10枚目
        ],
    )
    def test_the_name_is_taken(self, line: str, last: str, first: str):
        got = parse_fields(["Acme Inc.", line])["fields"]

        assert (got["last_name"], got["first_name"]) == (last, first)

    def test_a_hyphenated_surname_is_kept(self):
        """`-do` などの接尾辞に当たらないハイフンは、氏名にもある。"""
        assert _looks_like_person_name("Anne Smith-Jones")

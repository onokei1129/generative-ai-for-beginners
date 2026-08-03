"""090・080・070 で始まる番号は携帯（実テスト 20枚目）。

    印字   PHONE 携帯 070 4100 5747
    読み   PHONE 捕帯 070 4100 5747      ← `携帯` が `捕帯` に化けた

`携帯` がラベルとして拾えず、残った `PHONE` を信じて電話の欄に入れていた。

日本の 090・080・070 は携帯にしか割り当てられない。固定電話がこの番号
で始まることはないので、ラベルが何であれ携帯として扱ってよい。
`050`（IP電話）は固定側にもあるため、ラベルを信じたままにする。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import merge_fields, parse_fields  # noqa: E402


@pytest.mark.parametrize("prefix", ["090", "080", "070"])
def test_a_mobile_prefix_wins_over_the_label(prefix: str):
    got = parse_fields([f"TEL {prefix}-1234-5678"])["fields"]

    assert got["mobile"] == f"{prefix}-1234-5678"
    assert not got["tel"]


def test_an_ip_phone_still_follows_the_label():
    """`050` は固定側にもある。ラベルを信じる。"""
    got = parse_fields(["Tel 050-3110-2873"])["fields"]

    assert got["tel"] == "050-3110-2873"
    assert not got["mobile"]


def test_a_landline_is_untouched():
    got = parse_fields(["TEL 03-1234-5678"])["fields"]

    assert got["tel"] == "03-1234-5678"


def test_a_fax_label_is_untouched():
    """FAX は番号の頭では決められない。ラベルが唯一の手がかり。"""
    got = parse_fields(["FAX 03-1234-5679"])["fields"]

    assert got["fax"] == "03-1234-5679"


class TestTheLunateCard:
    """実テスト 20枚目。携帯が電話の欄に入っていた。"""

    EASYOCR = """LUAATE
９９ｍｅ
オロブスキー　スタニスラフ
ORLOvsKIysTANISLAV
日本支社
Represenialivein Japan
PHONE 捕帯 070 4100 5747
EMAIL  slanislav: orlovskiy@lunategames
lunalegames"""
    TESSERACT = """a Qe ie ae
7  : 5]  moe  |
Ys  オロ プス キー / ス タニ スラ リフ
Yi.   THOT
ん い Representative in Japan
laced  X  ¥ PHONE 4190 5747
¥ eee いい お   EMAIL メール stanisfay.orlovskiy@lunate.games
ne し A   ERE"""

    def fields(self) -> dict:
        parsed = [parse_fields(t.splitlines()) for t in (self.EASYOCR, self.TESSERACT)]
        return merge_fields(parsed)["fields"]

    def test_the_number_lands_in_mobile(self):
        got = self.fields()

        assert got["mobile"] == "070 4100 5747"
        assert not got["tel"]

    def test_the_role_is_taken(self):
        assert self.fields()["title"] == "Representative in Japan"

    def test_the_name_and_department_are_unchanged(self):
        got = self.fields()

        assert got["last_name"] == "オロブスキー"
        assert got["first_name"] == "スタニスラフ"
        assert got["department_name"] == "日本支社"

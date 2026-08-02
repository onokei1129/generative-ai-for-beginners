"""かなの氏名が読み崩れた名刺（services/ocr/parser.py）。

実テスト（227枚）の3枚目 `(会社名)_ユンソめ ン.pdf` で、氏名が
姓『ソク』名『ン』になっていた。名刺にはこう印字されている。

    代表取締役
    ユン　ソクン
    SEOKHOON YOON

OCRは `ユン` を `dy` と読み落とし、残ったのが `ソクン` だけになる。ここには
姓と名の区切りが無いので、どこで割っても当たらない。にもかかわらず、かなの
氏名を英字より先に採る決まりのために `ソクン` が選ばれ、機械的に割られていた。

同じ名前がラテン文字でも刷られている（`SEOKHOON YOON`）。こちらは空白で
区切られているぶん確実に割れるが、2つの理由で使われていなかった。

1. 全部大文字の行は、メールの左側に同じ語があるときだけ氏名とみなしていた。
   このメールは `ceo@omorobot.com` で役職名のため、照合できない。
2. かなの候補があると、そこで打ち切って英字を見ていなかった。

1 はドメインを見て判ける。社名はドメインの綴りになっていることが多いので、
行の語がすべてドメインに現れるなら社名、現れないなら人名とみなす。
2 は「区切りが無いかなの行」だけ後回しにする。区切りが残っていれば
（`ユン ソクン` `パトリシオ　バスケス`）、従来どおりかなを優先する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402

# poc/explain-one が実際に出した読み取り文字（作り直しではない）
REAL_OCR = [
    "の",
    "HP",
    "070-9385-4004",
    "Tel",
    "代表取締役             050-3110-2873",
    "dy  ソクン          E-mail",
    "SEOKHOON YOON          ceo@omorobot.com",
    "Add",
    "580-0021",
    "大阪府松原市高見の里六丁目7-18",
]


def fields(lines: list[str]) -> dict:
    return parse_fields(lines)["fields"]


class TestTheRealOcrTextOfTheKoreanCard:
    def test_the_romanised_name_is_used(self):
        """かな側が崩れているので、ラテン文字のほうを採る。"""
        got = fields(REAL_OCR)

        assert (got["last_name"], got["first_name"]) == ("YOON", "SEOKHOON")

    def test_the_kana_is_not_split_at_a_made_up_place(self):
        """姓『ソク』名『ン』のような割り方をしないこと。"""
        got = fields(REAL_OCR)

        assert got["last_name"] != "ソク"
        assert got["first_name"] != "ン"

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("title", "代表取締役"),
            ("mobile", "070-9385-4004"),
            ("tel", "050-3110-2873"),
            ("email", "ceo@omorobot.com"),
            ("postal_code", "580-0021"),
            ("address", "大阪府松原市高見の里六丁目7-18"),
        ],
    )
    def test_the_other_printed_items_still_come_out(self, key: str, value: str):
        assert fields(REAL_OCR)[key] == value

    def test_nothing_is_invented(self):
        """社名はロゴで、OCRに出ていない。埋めないこと。"""
        got = fields(REAL_OCR)

        assert got["company_name"] == ""
        assert got["fax"] == ""


class TestKanaWinsWhenItIsReadable:
    """かなが読めているときは、そちらのほうが名刺の印字に近い。"""

    def test_a_separated_kana_name_is_preferred(self):
        got = fields(["ユン ソクン", "SEOKHOON YOON", "ceo@omorobot.com"])

        assert (got["last_name"], got["first_name"]) == ("ユン", "ソクン")

    def test_a_kana_name_with_no_separator_gives_way(self):
        got = fields(["ソクン", "SEOKHOON YOON", "ceo@omorobot.com"])

        assert (got["last_name"], got["first_name"]) == ("YOON", "SEOKHOON")

    def test_the_kana_is_still_used_when_there_is_no_latin_name(self):
        """英字が無ければ、区切りが無くてもかなを使う（空にはしない）。"""
        got = fields(["ソクン", "ceo@omorobot.com"])

        assert got["last_name"] or got["first_name"]


class TestAllCapsIsJudgedByTheDomain:
    """全部大文字の行が社名か人名かは、メールのドメインで判ける。"""

    def test_a_name_unlike_the_domain_is_a_name(self):
        """`SEOKHOON YOON` は `omorobot` と綴りが違う → 人名。"""
        got = fields(["SEOKHOON YOON", "ceo@omorobot.com"])

        assert (got["last_name"], got["first_name"]) == ("YOON", "SEOKHOON")

    def test_a_logo_spelling_the_domain_is_a_company(self):
        """`AONE GAMES` は `aonegames` そのもの → 社名のまま。"""
        got = fields(["AONE GAMES", "patricio@aonegames.com"])

        assert (got["last_name"], got["first_name"]) == ("", "")
        assert got["company_name"] == "AONE GAMES"

    def test_without_an_email_all_caps_still_stays_out(self):
        """裏づけが無ければ従来どおり。推測で氏名にしない。"""
        got = fields(["AONE GAMES", "03-1234-5678"])

        assert (got["last_name"], got["first_name"]) == ("", "")

"""役職と氏名の取り違え（services/ocr/parser.py）。

実データ（韓国の方の名刺）で、役職と氏名が1行に読まれていた。

    OCRの読み  代表取締役 ユン ソクン
    修正前     役職『代表取締役ユンソクン』・姓名は空
    修正後     役職『代表取締役』・姓『ユン』・名『ソクン』

追ううちに、氏名の判定そのものに2つの取りこぼしが見つかった。

    佐々木健   `々` が文字クラスに無く、氏名として認識されなかった
    中村健     住所の語（`村`）を1つ含むだけで住所とみなして弾いていた

どちらも珍しい姓ではない。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import (  # noqa: E402
    _looks_like_person_name,
    parse_fields,
    split_department_and_title,
)


def fields(*lines: str) -> dict:
    return parse_fields(list(lines))["fields"]


class TestTitleAndNameOnOneLine:
    @pytest.mark.parametrize(
        ("line", "title", "last", "first"),
        [
            ("代表取締役 ユン ソクン", "代表取締役", "ユン", "ソクン"),
            ("部長 山田 太郎", "部長", "山田", "太郎"),
            ("CEO John Smith", "CEO", "John", "Smith"),
            ("主任 佐々木 健", "主任", "佐々木", "健"),
        ],
    )
    def test_both_are_extracted(self, line: str, title: str, last: str, first: str):
        got = fields(line)

        assert got["title"] == title
        assert got["last_name"] == last
        assert got["first_name"] == first

    @pytest.mark.parametrize("line", ["主任研究員", "課長補佐", "部長代理", "担当部長", "本部長"])
    def test_a_compound_title_is_not_split(self, line: str):
        """役職の続き（`主任研究員`）を氏名にしないこと。"""
        got = fields(line)

        assert got["title"] == line
        assert got["last_name"] == ""
        assert got["first_name"] == ""

    def test_a_separate_name_line_still_wins(self):
        """氏名が別の行にあるときは、そちらを使うこと。"""
        got = fields("代表取締役", "ユン ソクン")

        assert got["title"] == "代表取締役"
        assert got["last_name"] == "ユン"


class TestTitleIsNotADepartment:
    def test_a_compound_title_is_not_a_department(self):
        """`課長補佐` を部署にしないこと（`課` を部署の語として拾っていた）。"""
        got = fields("課長補佐")

        assert got["department_name"] == ""
        assert got["title"] == "課長補佐"

    def test_a_department_starting_with_a_title_word_is_still_a_department(self):
        """`Sales Department` の `Sales` を役職にしないこと。"""
        assert split_department_and_title("SalesDepartment") == ("SalesDepartment", "")

    def test_a_department_and_a_title_on_one_line_are_still_split(self):
        got = fields("営業本部 第一営業部 部長", "山田 太郎")

        assert got["department_name"].replace(" ", "") == "営業本部第一営業部"
        assert got["title"] == "部長"


class TestNamesThatWereRejected:
    @pytest.mark.parametrize(
        "name",
        ["佐々木健", "野々村真", "中村健", "木村拓也", "村上春樹", "市川団十郎", "町田花子"],
    )
    def test_common_surnames_are_recognised(self, name: str):
        """踊り字（々）や住所の語を含む姓を氏名として扱うこと。"""
        assert _looks_like_person_name(name)

    @pytest.mark.parametrize("line", ["東京都千代田区", "大阪市北区", "愛知県名古屋市中区"])
    def test_addresses_are_still_rejected(self, line: str):
        """住所の語を2つ以上含む行は氏名にしないこと。"""
        assert not _looks_like_person_name(line)

    def test_a_card_with_such_a_name_is_extracted(self):
        got = fields(
            "株式会社サンプル商事",
            "営業部",
            "中村 健",
            "〒100-0001 東京都千代田区千代田1-1-1",
        )

        assert got["last_name"] == "中村"
        assert got["first_name"] == "健"
        assert got["address"].replace(" ", "") == "東京都千代田区千代田1-1-1"

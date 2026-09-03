"""海外の法人格と、文字体系ごとの空白の扱い（services/ocr/parser.py）。

報告 5.1 の計測で、言語データを足してOCRが文字を読めるようになっても
**社名が埋まらない**ことが分かっていた。法人格の辞書が `株式会社` と `Inc.`
しか持たず、`주식회사`・`有限公司`・`ООО` を知らなかったため。

あわせて空白の扱いを直す。日本語・中国語は語を空白で区切らないので、OCRが
入れた空白は消してよい。ハングルとキリル文字は語を空白で区切るため、消すと
`주식회사 오모로봇` が `주식회사오모로봇` になってしまう。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import (  # noqa: E402
    normalize_company,
    parse_fields,
    strip_inner_spaces,
)


def company(*lines: str) -> str:
    return parse_fields(list(lines))["fields"]["company_name"]


class TestForeignLegalForms:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("주식회사 오모로봇", "주식회사 오모로봇"),
            ("(주)오모로봇", "(주)오모로봇"),
            ("欧姆机器人有限公司", "欧姆机器人有限公司"),
            ("ООО «Ромашка»", "ООО «Ромашка»"),
            ("Omorobot GmbH", "Omorobot GmbH"),
            ("Sample Sdn Bhd", "Sample Sdn Bhd"),
            ("Sample S.A.", "Sample S.A."),
        ],
    )
    def test_company_is_found(self, line: str, expected: str):
        assert company(line) == expected

    def test_japanese_company_still_wins(self):
        assert company("株式会社サンプル商事", "営業部") == "株式会社サンプル商事"

    def test_a_person_is_not_a_company(self):
        """人名や役職の行を社名にしないこと（短い略号を辞書に入れていない）。"""
        assert company("John Smith", "Sales Manager") == ""

    @pytest.mark.parametrize(
        "line",
        [
            "123 Main St, Chicago, U.S.A.",
            "1-1-1 Chiyoda, Tokyo, JAPAN",
        ],
    )
    def test_an_address_is_not_a_company(self, line: str):
        """住所の行を社名にしないこと。

        `U.S.A.` の中の `S.A.` を法人格として数え、住所が社名になっていた。
        英字の略号は、直前が英字またはドットなら別の語の一部と見なす。
        """
        assert company("John Smith", line, "john@example.com") == ""

    def test_the_abbreviation_still_counts_on_its_own(self):
        """語として置かれた略号は従来どおり数えること。"""
        assert company("Acme S.A.") == "Acme S.A."
        assert company("Example PLC") == "Example PLC"

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("주식회사 오모로봇", "오모로봇"),
            ("欧姆机器人有限公司", "欧姆机器人"),
            ("Omorobot GmbH", "Omorobot"),
        ],
    )
    def test_legal_form_is_ignored_when_matching(self, left: str, right: str):
        """法人格の有無で同じ会社が別物にならないこと（照合に使う値）。"""
        assert normalize_company(left) == normalize_company(right)


class TestInnerSpacesPerScript:
    @pytest.mark.parametrize(
        ("printed", "expected"),
        [
            ("株式会社 サンプル 商事", "株式会社サンプル商事"),
            ("冨田 修", "冨田修"),
            ("欧姆机器人 有限公司", "欧姆机器人有限公司"),
        ],
    )
    def test_cjk_inner_spaces_are_removed(self, printed: str, expected: str):
        assert strip_inner_spaces(printed) == expected

    @pytest.mark.parametrize(
        "printed",
        [
            "주식회사 오모로봇",
            "ООО «Ромашка»",
            "윤 석훈",
        ],
    )
    def test_hangul_and_cyrillic_spaces_are_kept(self, printed: str):
        """語の区切りの空白を消さないこと。"""
        assert strip_inner_spaces(printed) == printed

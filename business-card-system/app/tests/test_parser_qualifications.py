"""資格を役職として取る（実テスト 22枚目・高岡徹税理士事務所）。

名刺には氏名の上に `公認会計士　税理士` と印字されている。士業の名刺では
これが役職の位置に来るが、役職の語彙に無いため空欄になっていた。

`士` は「役職の語のあとに続く語尾」としては入っていた（`主任研究員` を
役職『主任』＋氏名『研究員』に分けないため）。役職を**始める**語としては
入っていなかったので、`税理士` だけの行は役職にならない。

会社名と取り違えないこと。22枚目の会社名は `高岡徹税理士事務所` で、
`税理士` を含むが `事務所` があるので会社名として扱われる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheTaxAccountantCard:
    """実テスト 22枚目。"""

    LINES = [
        "高岡徹税理士事務所",
        "公認会計士 税理士",
        "たかおか　　とおる",
        "高 岡　徹",
        "〒102-0071",
        "東京都千代田区富士見1丁目3-11",
    ]

    def test_the_qualification_is_the_title(self):
        """語の間の空白は詰まる。精度の測定でも同じ値として扱われる
        （`poc.runner.normalize_value` が空白を落とす）。"""
        assert parse_fields(self.LINES)["fields"]["title"] == "公認会計士税理士"

    def test_the_company_is_still_the_company(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["company_name"] == "高岡徹税理士事務所"

    def test_the_name_is_still_the_name(self):
        got = parse_fields(self.LINES)["fields"]

        assert (got["last_name"], got["first_name"]) == ("高岡", "徹")


class TestCommonQualifications:
    @pytest.mark.parametrize(
        "qualification",
        [
            "税理士",
            "公認会計士",
            "弁護士",
            "司法書士",
            "行政書士",
            "社会保険労務士",
            "中小企業診断士",
            "弁理士",
            "一級建築士",
            "不動産鑑定士",
        ],
    )
    def test_it_is_taken_as_the_title(self, qualification: str):
        got = parse_fields(["株式会社サンプル", qualification, "山田 太郎"])["fields"]

        assert got["title"] == qualification


class TestAnOfficeNameIsNotATitle:
    @pytest.mark.parametrize(
        "company",
        ["高岡徹税理士事務所", "サンプル弁護士法人", "山田司法書士事務所"],
    )
    def test_the_company_line_stays_the_company(self, company: str):
        got = parse_fields([company, "山田 太郎", "TEL 03-1234-5678"])["fields"]

        assert got["company_name"] == company
        assert got["title"] != company

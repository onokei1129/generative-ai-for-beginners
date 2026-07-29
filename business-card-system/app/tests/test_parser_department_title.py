"""部署と役職の切り分け（services/ocr/parser.py）。

名刺は「開発部 主任」のように部署と役職を1行に印字することが多い。
実測（合成サンプル16枚）では部署がその行を丸ごと取り、役職を巻き込んでいた。

    `開発部 主任`            → 部署 `開発部主任`（正解は `開発部`）
    `営業本部 第一営業部 部長` → 部署 `営業本部第一営業部部長`

1行で2項目を落とすので、直す価値が大きい。ただし切りすぎると
「Sales Department」を役職と誤るなど別の壊れ方をするため、対にして固定する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


def fields(*lines: str) -> dict:
    return parse_fields(list(lines))["fields"]


class TestSplitsOneLine:
    @pytest.mark.parametrize(
        ("line", "department", "title"),
        [
            ("開発部 主任", "開発部", "主任"),
            ("営業本部 第一営業部 部長", "営業本部第一営業部", "部長"),
            ("情報システム部 部長", "情報システム部", "部長"),
            ("調査研究センター 所長", "調査研究センター", "所長"),
        ],
    )
    def test_department_and_title_are_separated(self, line: str, department: str, title: str):
        got = fields(line)

        assert got["department_name"].replace(" ", "") == department
        assert got["title"] == title


class TestDoesNotOverSplit:
    def test_title_only_line_is_not_a_department(self):
        """「本部長」は `本部` を含むが部署ではない。"""
        got = fields("本部長")

        assert got["department_name"] == ""
        assert got["title"] == "本部長"

    def test_department_starting_with_a_title_word_is_kept_whole(self):
        """「Sales Department」の `Sales` を役職にしないこと。

        役職の語が行頭にある場合は、行全体がその語と一致するときだけ役職とみなす。
        """
        got = fields("Sales Department")

        assert got["department_name"] == "Sales Department"
        assert got["title"] == ""

    def test_compound_title_is_not_truncated(self):
        """部署の手がかりが無い行は切らないこと。`シニア` は部署ではない。"""
        got = fields("シニアエンジニア")

        assert got["title"] == "シニアエンジニア"
        assert got["department_name"] == ""

    def test_department_without_a_title_is_untouched(self):
        got = fields("調査研究センター")

        assert got["department_name"] == "調査研究センター"
        assert got["title"] == ""


class TestSeparateLinesStillWork:
    def test_department_and_title_on_their_own_lines(self):
        """行が分かれている従来の形を壊さないこと。"""
        got = fields(
            "株式会社サンプル商事",
            "営業本部 第一営業部",
            "部長",
            "山田 太郎",
        )

        assert got["company_name"] == "株式会社サンプル商事"
        assert got["department_name"].replace(" ", "") == "営業本部第一営業部"
        assert got["title"] == "部長"

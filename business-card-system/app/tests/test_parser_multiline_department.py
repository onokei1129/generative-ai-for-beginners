"""複数行に分かれた部署をつなぐ（実テスト 22枚目・Smilegate）。

印字は4行。

    Team Manager                                ← 役職
    Store Business Management Team              ← 部署
    Publishing&Platform ESD Business Division   ← 部署
    Megaport Division Group                     ← 部署

出ていた部署は最後の1行だけだった。組織の階層を上から順に刷る名刺は多く、
1行しか取らないと**どの部署に属するのか分からなくなる**。

続いている部署の行はつなぐ。判断は「部署の語を含む行が隣り合っているか」。
役職の行（`Team Manager`）は部署の語を含まないので混ざらない。

日本語の名刺でも同じ。18枚目は

    沖縄労働局 職業安定部
    需給調整事業室

で、これまでは `職業安定部` だけだった。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheSmilegateCard:
    LINES = [
        "Smilegate Holdings, Inc.",
        "Jeong, Sun Ho",
        "Team Manager",
        "Store Business Management Team",
        "Publishing&Platform ESD Business Division",
        "Megaport Division Group",
        "shojeong@smilegate.com",
    ]

    def test_all_the_department_lines_are_kept(self):
        got = parse_fields(self.LINES)["fields"]["department_name"]

        assert "Store Business Management Team" in got
        assert "Publishing&Platform ESD Business Division" in got
        assert "Megaport Division Group" in got

    def test_the_title_is_not_mixed_in(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["title"] == "Team Manager"
        assert "Team Manager" not in got["department_name"]


class TestTheLabourBureauCard:
    """実テスト 18枚目。組織名・部署・その下の室が3行に分かれている。"""

    LINES = [
        "沖縄労働局 職業安定部",
        "需給調整事業室",
        "需給調整事業専門相談員",
        "迎 亮一",
    ]

    def test_the_room_is_appended_to_the_department(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["company_name"] == "沖縄労働局"
        assert "職業安定部" in got["department_name"]
        assert "需給調整事業室" in got["department_name"]


class TestNothingElseChanges:
    def test_a_single_line_department_is_unchanged(self):
        got = parse_fields(["株式会社サンプル", "営業本部 第一営業部", "山田 太郎"])["fields"]

        assert got["department_name"] == "営業本部第一営業部"

    def test_a_department_and_title_on_one_line_are_still_split(self):
        got = parse_fields(["株式会社サンプル", "開発部 主任", "山田 太郎"])["fields"]

        assert got["department_name"] == "開発部"
        assert got["title"] == "主任"

    def test_an_unrelated_line_is_not_joined(self):
        """部署の語を含まない行は続きではない。"""
        got = parse_fields([
            "株式会社サンプル",
            "営業本部",
            "山田 太郎",
            "〒100-0001 東京都千代田区1-1-1",
        ])["fields"]

        assert got["department_name"] == "営業本部"
        assert (got["last_name"], got["first_name"]) == ("山田", "太郎")

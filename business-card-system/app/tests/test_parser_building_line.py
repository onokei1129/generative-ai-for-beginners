"""建物名が次の行に回った住所（実テスト 9枚目・Causal Foundry）。

日本の名刺では、住所が次のように2行で印字されることが多い。

    〒150-0022
    東京都渋谷区恵比寿南1-1-1
    ヒューマックス恵比寿ビル8F

これまで、番地までしか住所に入っていなかった。日本語の住所は行末に読点が
無いので「次へ続く」印が無く、英字の住所用のつなぎ（`_continues_into_next_line`）
も、番地だけの行のつなぎ（`is_house_number_only`）も当たらない。

**建物らしい語があるときだけ**つなぐ。会社名を巻き込むと、住所も会社名も
壊れる（住所に社名が入り、会社名の判定からその行が消える）ため、
会社を示す語がある行はつながない。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


def address(lines: list[str]) -> str:
    return parse_fields(lines)["fields"]["address"]


class TestTheCausalFoundryCard:
    def test_the_building_is_joined(self):
        got = address([
            "〒150-0022",
            "東京都渋谷区恵比寿南1-1-1",
            "ヒューマックス恵比寿ビル8F",
        ])

        assert got == "東京都渋谷区恵比寿南1-1-1 ヒューマックス恵比寿ビル8F"


class TestWhatCountsAsABuildingLine:
    @pytest.mark.parametrize(
        "building",
        [
            "ヒューマックス恵比寿ビル8F",
            "サンプルビル",
            "サンプルビルディング 3階",
            "○○タワー 12F",
            "第一生命館 5階",
            "恵比寿ガーデンプレイスタワー 8F",
            "2階",
            "サンプルマンション101",
        ],
    )
    def test_it_is_joined(self, building: str):
        got = address(["〒150-0022", "東京都渋谷区恵比寿南1-1-1", building])

        assert got == f"東京都渋谷区恵比寿南1-1-1 {building}"


class TestWhatMustNotBeJoined:
    @pytest.mark.parametrize(
        "line",
        [
            "株式会社サンプル",
            "サンプル株式会社",
            "有限会社ビル管理サービス",
            "山田 太郎",
            "TEL 03-1234-5678",
            "yamada@example.com",
            "https://www.example.co.jp",
            "営業本部 第一営業部",
        ],
    )
    def test_it_stands_alone(self, line: str):
        got = address(["〒150-0022", "東京都渋谷区恵比寿南1-1-1", line])

        assert got == "東京都渋谷区恵比寿南1-1-1"

    def test_the_company_is_still_found(self):
        """住所に巻き込むと、会社名の判定からもその行が消える。"""
        got = parse_fields([
            "〒150-0022",
            "東京都渋谷区恵比寿南1-1-1",
            "株式会社サンプル",
        ])["fields"]

        assert got["company_name"] == "株式会社サンプル"
        assert "サンプル" not in got["address"]


class TestTheAddressIsNotJoinedTwice:
    def test_only_the_line_right_after_is_taken(self):
        got = address([
            "〒150-0022",
            "東京都渋谷区恵比寿南1-1-1",
            "ヒューマックス恵比寿ビル8F",
            "サンプル第2ビル",
        ])

        assert got == "東京都渋谷区恵比寿南1-1-1 ヒューマックス恵比寿ビル8F"

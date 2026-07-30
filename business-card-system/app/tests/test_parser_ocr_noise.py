"""ロゴやQRコードが文字として読まれる名刺（services/ocr/parser.py）。

実データ（沖縄県 東京事務所の名刺）のOCR結果をそのまま流して分かったもの。

    ©   沖縄県 東京事務所                → 会社名に `©` が残る
    企業請致チーム        _s             → 部署に `_s` が残る
    de Fh SHB eA        宮田 修         → 氏名として判定できず、使われない
    へ特設サイトノ                       → 姓『へ特』名『設サイトノ』
    Ob eC F 102-0093 東京都…Ai AP APE LOBE → 住所の前後にノイズ

OCRの誤読（`冨田`→`宮田`、`企業誘致`→`企業請致`）は抽出では直せない。
ここで直すのは「読めているのに、こちらが落としている・混ぜている」分だけ。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import (  # noqa: E402
    _looks_like_person_name,
    japanese_segment,
    parse_fields,
    trim_ocr_noise,
)

# 実データのOCR結果そのもの
OKINAWA_CARD = [
    "=            − −         =,",
    "©   沖縄県 東京事務所",
    "'Okinawa",
    "A                    とみた      おさむ",
    "企業請致チーム        _s",
    "de Fh SHB eA        宮田 修",
    "へ特設サイトノ",
    "Ob eC F 102-0093 東京都千代田区平河町2-6-3 Ai AP APE LOBE",
    "EN        T E L:03-5212-9087",
    "mytics       F A X:03-5212-9086",
    "沖縄県企業立地おガイド   E-mail:ab002011@prcfokinawalg.jp",
]


def fields(lines: list[str]) -> dict:
    return parse_fields(lines)["fields"]


class TestTrimOcrNoise:
    @pytest.mark.parametrize(
        ("printed", "expected"),
        [
            ("©   沖縄県東京事務所", "沖縄県東京事務所"),
            ("企業請致チーム        _s", "企業請致チーム"),
            ("Ob eC F 東京都千代田区平河町2-6-3 Ai AP APE LOBE", "東京都千代田区平河町2-6-3"),
        ],
    )
    def test_short_noise_is_removed(self, printed: str, expected: str):
        assert trim_ocr_noise(printed) == expected

    @pytest.mark.parametrize("text", ["AONE GAMES", "Santa Beatriz 111 of 1008", "ABC Inc."])
    def test_latin_lines_are_untouched(self, text: str):
        """日本語を含まない行は触らないこと（英字の社名・住所）。"""
        assert trim_ocr_noise(text) == text

    @pytest.mark.parametrize("text", ["Acme株式会社", "日本ABCD商事"])
    def test_words_of_five_letters_are_kept(self, text: str):
        """4文字を超える語は落とさないこと（社名の一部でありうる）。"""
        assert trim_ocr_noise(text) == text


class TestJapaneseSegment:
    def test_the_japanese_part_is_taken(self):
        assert japanese_segment("de Fh SHB eA        宮田 修") == "宮田 修"

    def test_a_line_without_japanese_gives_nothing(self):
        assert japanese_segment("de Fh SHB eA") == ""


class TestWordsThatAreNotNames:
    @pytest.mark.parametrize(
        "line", ["へ特設サイトノ", "特設サイト", "沖縄県企業立地おガイド", "ご案内", "地図はこちら"]
    )
    def test_notices_are_not_names(self, line: str):
        assert not _looks_like_person_name(line)

    @pytest.mark.parametrize("name", ["山田太郎", "宮田修", "中村健"])
    def test_names_are_still_names(self, name: str):
        assert _looks_like_person_name(name)


class TestTheRealCard:
    def test_eight_fields_are_extracted(self):
        got = fields(OKINAWA_CARD)

        assert got["last_name"] == "宮田"  # OCRの誤読（正しくは冨田）。抽出は正しい
        assert got["first_name"] == "修"
        assert got["company_name"] == "沖縄県東京事務所"
        assert got["department_name"] == "企業請致チーム"
        assert got["postal_code"] == "102-0093"
        assert got["address"] == "東京都千代田区平河町2-6-3"
        assert got["tel"] == "03-5212-9087"
        assert got["fax"] == "03-5212-9086"
        assert got["email"] == "ab002011@prcfokinawalg.jp"

    def test_the_notice_line_is_not_the_name(self):
        assert fields(OKINAWA_CARD)["last_name"] != "へ特"

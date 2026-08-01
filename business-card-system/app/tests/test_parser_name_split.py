"""ふりがなの分割と、氏名に見える英字の行（services/ocr/parser.py）。

合成サンプル16枚の計測で、ふりがな（せい・めい）の正答率が 0% / 6% だった。
原因は認識ではなく分割で、OCRは読めていた。

    印字 `やまだ たろう`  → OCR `や まだ た ろう`  → せい `や`   めい `まだ た ろう`
    印字 `すずき いちろう` → OCR `すず き いち ろう` → せい `すず` めい `き いち ろう`

先頭の空白で切っていたため。どこが語の切れ目かは字面では決まらないので、
長さの釣り合いで分ける（16枚中9枚が該当）。

あわせて、和英併記の名刺で `Head Office` を氏名として登録していた
（姓 `Head` / 名 `Office`）。本来の氏名が空になる（16枚中4枚）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import parse_fields, split_person_name  # noqa: E402


def fields(*lines: str) -> dict:
    return parse_fields(list(lines))["fields"]


class TestReadingIsSplitByBalance:
    @pytest.mark.parametrize(
        ("printed", "expected"),
        [
            ("や まだ た ろう", ("やまだ", "たろう")),
            ("すず き いち ろう", ("すずき", "いちろう")),
            ("さと う は な こ", ("さとう", "はなこ")),
            ("いと う な お き", ("いとう", "なおき")),
            ("たか はし み さき", ("たかはし", "みさき")),
        ],
    )
    def test_spaces_inside_a_reading_are_ignored(self, printed: str, expected: tuple[str, str]):
        assert split_person_name(printed) == expected

    @pytest.mark.parametrize(
        ("printed", "expected"),
        [
            ("やまだ たろう", ("やまだ", "たろう")),
            ("さとう はなこ", ("さとう", "はなこ")),
        ],
    )
    def test_a_clean_reading_is_unchanged(self, printed: str, expected: tuple[str, str]):
        assert split_person_name(printed) == expected

    def test_katakana_is_still_split_by_balance(self):
        """カタカナ（外国名の氏名）の分け方を変えていないこと。"""
        assert split_person_name("パト リシオ バスケス") == ("パトリシオ", "バスケス")

    @pytest.mark.parametrize(
        ("printed", "expected"),
        [
            ("山田 太郎", ("山田", "太郎")),
            ("佐々木 健", ("佐々木", "健")),
            ("John A. Smith", ("Smith", "John A.")),
        ],
    )
    def test_kanji_and_latin_are_unchanged(self, printed: str, expected: tuple[str, str]):
        """かな以外は釣り合いで分けない（姓の長さの慣習で決まるため）。"""
        assert split_person_name(printed) == expected

    def test_a_card_gets_both_the_name_and_the_reading(self):
        got = fields("株式会社サンプル商事", "や まだ た ろう", "山田 太郎", "部長")

        assert (got["last_name"], got["first_name"]) == ("山田", "太郎")
        assert (got["last_name_kana"], got["first_name_kana"]) == ("やまだ", "たろう")


class TestOfficeIsNotAPerson:
    @pytest.mark.parametrize(
        "line",
        [
            "Head Office",
            "Tokyo Office",
            "Sakura Building",
            "Osaka Branch",
        ],
    )
    def test_place_words_are_not_names(self, line: str):
        got = fields(line, "すずき いちろう", "鈴木 一郎")

        assert (got["last_name"], got["first_name"]) == ("鈴木", "一郎")

    def test_a_latin_person_name_is_still_a_name(self):
        """ラテン文字は「名 姓」の順。姓は後ろの語。"""
        got = fields("John Smith", "Sales Manager")

        assert (got["last_name"], got["first_name"]) == ("Smith", "John")

    def test_the_place_line_is_kept_in_the_note(self):
        """氏名にしないだけで、読み取った文字は捨てないこと。"""
        got = fields("Head Office", "鈴木 一郎")

        assert "Head Office" in got["note"]

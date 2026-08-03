"""海外名刺の電話番号（services/ocr/parser.py）。

国番号つきの番号を `+81` だけ見ていたため、海外名刺の電話を1件も拾えていなかった。
実測では英語の名刺で `TEL +1 212-555-0100` が空になっていた。

同じ番号が表記の違いで別物にならないことも見る。ここが揃わないと、
同じ人が2枚の名刺で別人として登録される（重複人物の判定に使う値のため）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import normalize_phone, parse_fields  # noqa: E402


def fields(*lines: str) -> dict:
    return parse_fields(list(lines))["fields"]


class TestPicksUpInternationalNumbers:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("TEL +1 212-555-0100", "+1 212-555-0100"),
            ("TEL +7 495 123-45-67", "+7 495 123-45-67"),
            ("Tel: +44 (0)20 7123 4567", "+44 (0)20 7123 4567"),
            ("TEL +86 21-5888-1234", "+86 21-5888-1234"),
            ("TEL +82 2-1234-5678", "+82 2-1234-5678"),
        ],
    )
    def test_country_code_numbers_are_extracted(self, line: str, expected: str):
        assert fields(line)["tel"] == expected

    def test_tel_and_fax_on_one_line(self):
        """`+81` は国内表記へ直す（tests/test_parser_japanese_international_phone.py）。"""
        got = fields("TEL +81 3-1234-5678  FAX +81 3-1234-5679")

        assert got["tel"] == "03-1234-5678"
        assert got["fax"] == "03-1234-5679"

    def test_japanese_mobile_with_country_code_is_a_mobile(self):
        """`+81 90-…` は日本の携帯。ラベルが無くても固定電話に入れないこと。"""
        assert fields("+81 90-1234-5678")["mobile"] == "090-1234-5678"

    def test_number_is_kept_as_printed(self):
        """他国の番号は名刺の記載どおり。整形した値で上書きしないこと。

        以前ここに「要件§8」と書いていたが、§8（OCR外部クラウドサービス）に
        記載どおりに保存せよという定めは無い。あるのは「OCR結果は自動確定せず、
        利用者が確認・修正した後に登録する」という確認の手順のほう。

        日本の番号を国際表記のままにしていたのはその読み違いで、実テスト
        9枚目で利用者が正解として入力したのは `070-1508-9897` だった。
        国番号の扱いが国ごとに違う他国の番号だけ、記載どおりに残す。
        """
        assert fields("TEL +7 495 123-45-67")["tel"] == "+7 495 123-45-67"


class TestDoesNotPickUpNonPhones:
    @pytest.mark.parametrize(
        "line",
        [
            "〒100-0001 東京都千代田区千代田1-1-1",
            "金額 12,345円",
            "2025 年 8 月 4 日",
        ],
    )
    def test_other_number_strings_are_not_phones(self, line: str):
        got = fields(line)

        assert not got["tel"]
        assert not got["mobile"]
        assert not got["fax"]

    def test_domestic_numbers_still_work(self):
        got = fields("TEL 03-1234-5678  FAX 03-1234-5679", "Mobile 090-1234-5678")

        assert got["tel"] == "03-1234-5678"
        assert got["fax"] == "03-1234-5679"
        assert got["mobile"] == "090-1234-5678"


class TestSameNumberNormalizesAlike:
    """表記が違っても同じ値になること（重複人物の判定に使う）。"""

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("+81 90-1234-5678", "090-1234-5678"),
            ("+81 (0)90-1234-5678", "090-1234-5678"),
            ("+81 3-1234-5678", "03-1234-5678"),
            ("+44 (0)20 7123 4567", "+44 20 7123 4567"),
        ],
    )
    def test_notations_agree(self, left: str, right: str):
        assert normalize_phone(left) == normalize_phone(right)

    def test_different_numbers_stay_different(self):
        assert normalize_phone("090-1234-5678") != normalize_phone("090-1234-5679")

    def test_foreign_number_keeps_its_country_code(self):
        """国番号を落として国内番号と衝突させないこと。"""
        assert normalize_phone("+1 212-555-0100") == "12125550100"

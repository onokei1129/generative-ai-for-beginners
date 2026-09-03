"""メール・URL・住所の取り出し（services/ocr/parser.py）。

いずれも「OCRは読めているのに、こちらの取り出し方が悪くて落としている」
種類の不具合を固定する。合成サンプル16枚の実測から見つけた。

    URL   16枚中4枚が `https://www.` で切れていた
          （OCRは `https://www. example. co. jp` と読んでいた）
    メール ローカル部が丸ごと落ちていた
          （OCRは `taro, yamada@example.co.jp` と読んでいた）
    住所   先頭に `7` が残っていた
          （OCRが 〒 を `7` と読み、郵便番号を抜いた残りに付いてきていた）

直しすぎると別のものを壊すため、壊さないことの確認を対にして置く。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


def fields(*lines: str) -> dict:
    return parse_fields(list(lines))["fields"]


class TestUrl:
    def test_dots_split_by_spaces_are_joined(self):
        got = fields("https://www. example. co. jp")
        assert got["url"] == "https://www.example.co.jp"

    def test_trailing_dot_is_dropped(self):
        """行末の句点をURLに含めないこと。"""
        got = fields("https://www.example.co.jp.")
        assert got["url"] == "https://www.example.co.jp"

    def test_following_word_is_not_absorbed(self):
        """ドットで終わっていない語は繋がないこと。

        `.jp Mobile 090-…` を繋いでしまうと、URLに電話番号が混ざる。
        """
        got = fields("https://tech.example.jp Mobile 090-1234-5678")
        assert got["url"] == "https://tech.example.jp"
        assert got["mobile"] == "090-1234-5678"


class TestEmail:
    def test_comma_in_local_part_is_recovered(self):
        got = fields("taro, yamada@example.co.jp")
        assert got["email"] == "taro.yamada@example.co.jp"

    def test_two_addresses_on_one_line_are_not_merged(self):
        """カンマ区切りで2つ並べた行で、前のアドレスを巻き込まないこと。"""
        got = fields("info@example.co.jp, sales@example.co.jp")
        assert got["email"] == "info@example.co.jp"

    def test_normal_address_is_untouched(self):
        got = fields("hanako.sato@example.jp")
        assert got["email"] == "hanako.sato@example.jp"


class TestAddress:
    def test_misread_postal_mark_is_dropped(self):
        """〒 が `7` と読まれても、住所の先頭に持ち込まないこと。"""
        got = fields("7100-0001 東京都千代田区千代田1-1-1")

        assert got["postal_code"] == "100-0001"
        assert got["address"].replace(" ", "") == "東京都千代田区千代田1-1-1"

    @pytest.mark.parametrize("mark", ["〒", "T", "亍", "干"])
    def test_other_misreadings_are_dropped(self, mark: str):
        got = fields(f"{mark}530-0001 大阪府大阪市北区梅田2-2-2")

        assert got["postal_code"] == "530-0001"
        assert got["address"].replace(" ", "") == "大阪府大阪市北区梅田2-2-2"

    def test_english_address_keeps_its_leading_number(self):
        """英字表記の番地を郵便記号と間違えて削らないこと。

        郵便番号に接している1文字だけを対象にしているので、
        離れた位置の `7-1-1` は残る。
        """
        got = fields("7-1-1 Chiyoda, Chiyoda-ku, Tokyo 100-0001")

        assert got["postal_code"] == "100-0001"
        assert got["address"].startswith("7-1-1")

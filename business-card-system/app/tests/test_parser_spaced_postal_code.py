"""ハイフンの代わりに空白で読まれた郵便番号（services/ocr/parser.py）。

実テスト24枚目（Donuts）は `〒151-0053` と刷られているのに、読み取りでは
区切りが空白になっていた。

    tesseract   151 0053

郵便番号は `3桁-4桁` の形しか見ていなかったため、**読めているのに空欄**の
まま入力の手間になっていた。

ゆるめて拾うと、以前に踏んだ誤りに戻る——`TEL 03-7161-2135` の一部を
郵便番号 `161-2135` として登録していた（`POSTAL_RE` の上の説明）。空欄なら
人が気づくが、もっともらしい誤りは気づかれずに残る。

そこで**行全体がその形のときだけ**採る。電話番号は塊が3つ以上あるので、
この条件で外れる。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestItIsPickedUp:
    def test_the_donuts_card(self):
        """実テスト24枚目。"""
        got = parse_fields([
            "株式会社Donuts",
            "木村 央志",
            "151 0053",
            "東京都渋谷区代々木2-2-1",
        ])["fields"]

        assert got["postal_code"] == "151-0053"

    def test_it_is_less_certain_than_a_hyphenated_one(self):
        """区切りが読めていない。印字どおりのものより弱い根拠。"""
        spaced = parse_fields(["山田 太郎", "151 0053", "東京都渋谷区"])
        hyphen = parse_fields(["山田 太郎", "〒151-0053", "東京都渋谷区"])

        assert spaced["confidence"]["postal_code"] < hyphen["confidence"]["postal_code"]


class TestItDoesNotEatPhoneNumbers:
    """空欄なら人が気づく。もっともらしい誤りは気づかれずに登録される。"""

    def test_a_mobile_number_is_left_alone(self):
        got = parse_fields(["山田 太郎", "090 8587 7873", "株式会社サンプル"])["fields"]

        assert got["postal_code"] == ""
        assert "8587" in got["mobile"]

    def test_a_number_with_something_else_on_the_line_is_ignored(self):
        """行全体がその形のときだけ。`TEL 03-7161-2135` の類を拾わない。"""
        got = parse_fields(["山田 太郎", "TEL 161 2135", "株式会社サンプル"])["fields"]

        assert got["postal_code"] == ""

    def test_a_hyphenated_one_still_wins(self):
        got = parse_fields([
            "山田 太郎",
            "151 0053",
            "〒106-0047",
            "東京都港区南麻布3-20-1",
        ])["fields"]

        assert got["postal_code"] == "106-0047"

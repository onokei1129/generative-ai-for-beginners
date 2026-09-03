"""英字の住所が2行に折り返された場合（実テスト 17枚目）。

    印字  VORT Suehiro-cho II 2F, 6-14-3, Sotokanda,
          Chiyoda-ku, Tokyo 101-0021, JAPAN

郵便番号のある行だけを住所にしていたため、`Chiyoda-ku, Tokyo, JAPAN` に
なり、番地とビル名が落ちていた。

英字の住所は折り返しに**読点が残る**。日本語の住所は読点で終わらないため、
この見分けは英字の住所にだけ効く（日本語の折り返しは番地の行を別に
つないでいる）。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import parse_fields  # noqa: E402


class TestALineEndingInACommaContinues:
    def test_the_line_before_the_postal_code_is_joined(self):
        got = parse_fields(
            [
                "VORT Suehiro-cho II 2F, 6-14-3, Sotokanda,",
                "Chiyoda-ku, Tokyo 101-0021, JAPAN",
            ]
        )["fields"]

        assert got["postal_code"] == "101-0021"
        assert got["address"].startswith("VORT Suehiro-cho II 2F")
        assert "Sotokanda" in got["address"]
        assert "Chiyoda-ku" in got["address"]

    def test_three_lines_are_joined(self):
        got = parse_fields(
            [
                "2621, Nambusunhwan-ro,",
                "Gangnam-gu, Seoul, Korea,",
                "06267 Seoul",
            ]
        )["fields"]

        assert "Nambusunhwan-ro" in got["address"]
        assert "Gangnam-gu" in got["address"]

    def test_a_line_without_a_comma_is_not_joined(self):
        """読点が無ければ折り返しではない。社名まで巻き込まないこと。"""
        got = parse_fields(["Meteorise Inc.", "Chiyoda-ku, Tokyo 101-0021, JAPAN"])["fields"]

        assert "Meteorise" not in got["address"]

    def test_a_japanese_address_is_untouched(self):
        got = parse_fields(["株式会社サンプル", "〒100-0001 東京都千代田区千代田1-1-1"])["fields"]

        assert got["address"] == "東京都千代田区千代田1-1-1"


class TestTheMeteoriseAddress:
    """実テスト 17枚目。tesseract 側の読みで確かめる。"""

    TESSERACT = """Shunsuke Katsumata
Producer
Meteorise Inc.
VORT Suehiro-cho II 2F, 6-14-3, Sotokanda,
Chiyoda-ku, Tokyo 101-0021, JAPAN
TEL 03-5817-4645    FAX 03-5817-4644
k2matter@meteorise.co.jp
https://www.meteorise.co.jp/"""

    def fields(self) -> dict:
        return parse_fields(self.TESSERACT.splitlines())["fields"]

    def test_the_whole_address_is_taken(self):
        address = self.fields()["address"]

        assert "VORT Suehiro-cho" in address
        assert "6-14-3" in address
        assert "Chiyoda-ku" in address

    def test_the_company_is_not_swallowed(self):
        got = self.fields()

        assert got["company_name"] == "Meteorise Inc."
        assert "Meteorise" not in got["address"]

    def test_the_other_fields_are_unchanged(self):
        got = self.fields()

        assert got["postal_code"] == "101-0021"
        assert got["tel"] == "03-5817-4645"
        assert got["last_name"] == "Katsumata"

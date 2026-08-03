"""電話番号の一部を郵便番号にしない（実テスト 23枚目・Smilegate）。

    印字      Cell +82-10-7161-2135
    郵便番号  161-2135     ← 電話番号の途中

`〒` は読み違えられやすいので、`7` や `T` を 〒 の読み崩れとして扱っている
（`7102-0071` → `102-0071`）。ところがその `7` が**数字の途中**でも成立して
いた。`…-7161-2135` の `7` を 〒 と見て、続く `161-2135` を郵便番号にする。

日本の名刺でも起きる。`TEL 03-7161-2135` で郵便番号 `161-2135` が入る。
空欄なら人が気づくが、**もっともらしい誤りは気づかれずに登録される**。

〒 の読み崩れとして扱うのは、その1文字の前が数字や区切りでないときだけに
する（行頭・空白のあとなど）。

あわせて、住所の末尾に置かれた海外の郵便番号も取る。

    8F, First Tower, 55, Bundang-ro, …, Republic of Korea, 13591
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestAPhoneNumberIsNotAPostalCode:
    @pytest.mark.parametrize(
        "line",
        [
            "Cell +82-10-7161-2135",
            "TEL 03-7161-2135",
            "TEL 03-7102-0071",
            "+81-90-7161-2135",
        ],
    )
    def test_no_postal_code_is_invented(self, line: str):
        assert not parse_fields(["Acme Inc.", line])["fields"]["postal_code"]

    def test_the_phone_number_is_still_taken(self):
        got = parse_fields(["Acme Inc.", "TEL 03-7161-2135"])["fields"]

        assert got["tel"] == "03-7161-2135"


class TestTheMisreadPostalMarkStillWorks:
    @pytest.mark.parametrize("mark", ["〒", "テ", "T", "7", "亍", "干"])
    def test_a_mark_at_the_head_is_read_as_a_postal_mark(self, mark: str):
        got = parse_fields([f"{mark}102-0071 東京都千代田区富士見1-3-11"])["fields"]

        assert got["postal_code"] == "102-0071"

    def test_a_mark_after_a_space_still_works(self):
        got = parse_fields(["住所 7102-0071 東京都千代田区富士見1-3-11"])["fields"]

        assert got["postal_code"] == "102-0071"


class TestThePostalCodeAtTheTailOfTheAddress:
    """実テスト 23枚目。韓国の名刺は住所の末尾に郵便番号を置く。"""

    LINES = [
        "Smilegate Holdings, Inc.",
        "8F, First Tower,",
        "55, Bundang-ro, Bundang-gu,",
        "Seongnam-si, Gyeonggi-do,",
        "Republic of Korea, 13591",
        "Email shojeong@smilegate.com",
    ]

    def test_the_postal_code_is_taken(self):
        assert parse_fields(self.LINES)["fields"]["postal_code"] == "13591"

    def test_the_address_does_not_keep_it(self):
        address = parse_fields(self.LINES)["fields"]["address"]

        assert "13591" not in address
        assert address.endswith("Republic of Korea")

    def test_a_japanese_address_is_untouched(self):
        got = parse_fields(["〒102-0071", "東京都千代田区富士見1丁目3-11"])["fields"]

        assert got["postal_code"] == "102-0071"
        assert got["address"] == "東京都千代田区富士見1丁目3-11"

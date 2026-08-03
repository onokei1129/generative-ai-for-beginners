"""海外の郵便番号を取る（実テスト 8枚目・NEXON GAMES）。

韓国の名刺で、郵便番号が空になり、住所の末尾に紛れ込んでいた。

    印字      2621, Nambusunhwan-ro,
              Gangnam-gu, Seoul, Korea,
              06267

    郵便番号  （空）
    住所      2621, Nambusunhwan-ro, Gangnam-gu, Seoul, Korea, 06267

原因は2つが重なっている。

1. 郵便番号の判定が日本の形（3桁-4桁）だけだった。`06267` は当たらない
2. 英字の住所は行末の読点で「次へ続く」と判断してつなぐ（`wrapped_blocks`）。
   `Korea,` で終わるので、次の `06267` まで住所に入っていた

数字だけの行に限って、5〜6桁を郵便番号として採る。**4桁を見ないのは**、
年号・部屋番号・読み崩れた番号と見分けが付かないため。豪州（4桁）などは
取れないが、誤って別の数字を郵便番号にするより空欄のほうがよい
（空欄なら入力する人が気づく）。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheNexonCard:
    """実テスト 8枚目。"""

    LINES = [
        "NEXON GAMES",
        "2621, Nambusunhwan-ro,",
        "Gangnam-gu, Seoul, Korea,",
        "06267",
        "Sangeon Lee",
        "T +82.2.6421.7777",
        "Planning & Coordination Dept",
    ]

    def fields(self) -> dict:
        return parse_fields(self.LINES)["fields"]

    def test_the_postal_code_is_taken(self):
        assert self.fields()["postal_code"] == "06267"

    def test_the_address_does_not_keep_it(self):
        assert "06267" not in self.fields()["address"]

    def test_the_rest_of_the_address_is_still_joined(self):
        address = self.fields()["address"]

        assert "2621, Nambusunhwan-ro" in address
        assert "Gangnam-gu, Seoul, Korea" in address

    def test_the_other_fields_are_untouched(self):
        got = self.fields()

        assert got["department_name"] == "Planning & Coordination Dept"
        assert got["last_name"] and got["first_name"]


class TestTheJapaneseFormStillWins:
    def test_a_japanese_postal_code_is_unchanged(self):
        got = parse_fields(["〒100-0001 東京都千代田区千代田1-1"])["fields"]

        assert got["postal_code"] == "100-0001"

    def test_a_stray_number_does_not_replace_it(self):
        """日本の形が取れているなら、数字だけの行は見ない。"""
        got = parse_fields(["〒100-0001 東京都千代田区千代田1-1", "12345"])["fields"]

        assert got["postal_code"] == "100-0001"


class TestNumbersThatAreNotPostalCodes:
    def test_four_digits_are_not_taken(self):
        """年号・部屋番号と見分けが付かない。空欄のほうがよい。"""
        assert not parse_fields(["Acme Inc.", "2024"])["fields"]["postal_code"]

    def test_seven_digits_are_not_taken(self):
        """日本の郵便番号をハイフン無しで書いた形は、別の話として扱わない。"""
        assert not parse_fields(["Acme Inc.", "1000001"])["fields"]["postal_code"]

    def test_a_line_with_letters_is_not_taken(self):
        assert not parse_fields(["Acme Inc.", "Room 06267"])["fields"]["postal_code"]

    def test_a_phone_number_is_not_taken(self):
        got = parse_fields(["Acme Inc.", "TEL 03-1234-5678"])["fields"]

        assert not got["postal_code"]
        assert got["tel"] == "03-1234-5678"

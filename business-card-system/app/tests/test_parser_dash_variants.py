"""ハイフンに見える別の文字（実テスト 9枚目・Causal Foundry）。

名刺の `〒150-0022` の横棒は、印刷では ASCII のハイフンとは限らない。
OCRもそれに応じて別の符号を返す。ところが郵便番号・電話番号の判定は
ASCII の `-` と全角の `－`・`ー`・`ｰ` しか見ていなかった。

    テ150‐0022  （U+2010 HYPHEN）  → 郵便番号 空
    TEL 03–1234–5678（U+2013 EN DASH）→ 電話 空

**空になるので気づけるが、原因は見えない。** 画面には「読めた文字」として
`テ150‐0022` と出るため、読めているのに項目にならない理由が分からない。

`normalize` で ASCII のハイフンへ寄せる。NFKC は全角（`－`）は直すが、
これらの横棒は直さない。

**`ー`（U+30FC 長音記号）は寄せてはいけない。** 「ヒューマックス」のように
日本語の語の一部として現れるため。郵便番号・電話番号の判定側で個別に
見ている今のやり方を変えない。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import normalize, parse_fields  # noqa: E402

# 横棒に見えて、日本語の語の中には出てこない文字。
DASHES = [
    pytest.param("‐", id="U+2010-HYPHEN"),
    pytest.param("‑", id="U+2011-NON-BREAKING-HYPHEN"),
    pytest.param("‒", id="U+2012-FIGURE-DASH"),
    pytest.param("–", id="U+2013-EN-DASH"),
    pytest.param("—", id="U+2014-EM-DASH"),
    pytest.param("―", id="U+2015-HORIZONTAL-BAR"),
    pytest.param("−", id="U+2212-MINUS-SIGN"),
]


class TestThePostalCodeIsStillFound:
    @pytest.mark.parametrize("dash", DASHES)
    def test_each_dash_works(self, dash: str):
        got = parse_fields([f"〒150{dash}0022 東京都渋谷区恵比寿南1-1-1"])["fields"]

        assert got["postal_code"] == "150-0022"

    @pytest.mark.parametrize("dash", DASHES)
    def test_it_is_not_left_in_the_address(self, dash: str):
        got = parse_fields([f"〒150{dash}0022 東京都渋谷区恵比寿南1-1-1"])["fields"]

        assert got["address"] == "東京都渋谷区恵比寿南1-1-1"


class TestThePhoneNumberIsStillFound:
    @pytest.mark.parametrize("dash", DASHES)
    def test_each_dash_works(self, dash: str):
        got = parse_fields([f"TEL 03{dash}1234{dash}5678"])["fields"]

        assert got["tel"] == "03-1234-5678"


class TestJapaneseTextIsNotDamaged:
    def test_the_prolonged_sound_mark_survives(self):
        """`ー` を寄せると「ヒューマックス」が「ヒュ-マックス」になる。"""
        assert normalize("ヒューマックス恵比寿ビル8F") == "ヒューマックス恵比寿ビル8F"

    def test_a_building_name_keeps_its_reading(self):
        got = parse_fields(["〒150-0022", "東京都渋谷区恵比寿南1-1-1 ヒューマックス恵比寿ビル8F"])

        assert "ヒューマックス" in got["fields"]["address"]

    def test_a_word_with_a_long_vowel_is_unchanged(self):
        assert normalize("コーヒー") == "コーヒー"

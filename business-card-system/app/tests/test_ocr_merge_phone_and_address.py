"""電話番号の重複と、住所の選び方（実テスト 21・17枚目）。

21枚目（Smilegate）で、同じ番号が電話と携帯の両方に入っていた。

    印字      Cell +82-10-8933-1438
    EasyOCR   携帯 +82-10-8933-1438   （`Cell` を見て携帯）
    tesseract 電話 +82-10-8933-1438   （ラベルを拾えず電話）
    併合      両方に同じ番号          ← 項目ごとに採るため

17枚目（Meteorise）では、短いほうの住所が採られていた。

    EasyOCR   Chiyoda-Ku TokyoJnPAN                              （断片）
    tesseract VORT Suehiro-cho II 2F, 6-14-3, Sotokanda, …       （全体）

住所は「読めた分だけ入る」項目で、失敗のしかたは**欠落**。読み崩れは
`looks_like_address` が先に落としているので、残ったものの中では長いほうが
情報が多い。合成サンプル20枚では、長いほうを採っても正答率は変わらない
（どちらも65%）ため、実データで得をするぶんだけ良い。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import merge_fields, parse_fields  # noqa: E402


class TestTheSameNumberIsNotStoredTwice:
    def test_a_number_in_two_phone_fields_is_kept_once(self):
        merged = merge_fields(
            [
                {"fields": {"mobile": "+82-10-8933-1438"}, "confidence": {"mobile": 0.85}},
                {"fields": {"tel": "+82-10-8933-1438"}, "confidence": {"tel": 0.6}},
            ]
        )

        assert merged["fields"]["mobile"] == "+82-10-8933-1438"
        assert not merged["fields"].get("tel")

    def test_the_field_with_the_stronger_evidence_keeps_it(self):
        """ラベルを見て決めたほう（確信度が高い）を残す。"""
        merged = merge_fields(
            [
                {"fields": {"tel": "03-1234-5678"}, "confidence": {"tel": 0.6}},
                {"fields": {"mobile": "03-1234-5678"}, "confidence": {"mobile": 0.85}},
            ]
        )

        assert merged["fields"]["mobile"] == "03-1234-5678"
        assert not merged["fields"].get("tel")

    def test_different_numbers_are_both_kept(self):
        merged = merge_fields(
            [
                {"fields": {"tel": "03-1234-5678", "mobile": "090-1111-2222"}},
                {"fields": {}},
            ]
        )

        assert merged["fields"]["tel"] == "03-1234-5678"
        assert merged["fields"]["mobile"] == "090-1111-2222"

    def test_the_same_digits_written_differently_still_count_as_one(self):
        merged = merge_fields(
            [
                {"fields": {"mobile": "090 1234 5678"}, "confidence": {"mobile": 0.85}},
                {"fields": {"tel": "090-1234-5678"}, "confidence": {"tel": 0.6}},
            ]
        )

        assert not merged["fields"].get("tel")

    def test_a_fax_that_repeats_the_tel_is_dropped(self):
        merged = merge_fields(
            [
                {"fields": {"tel": "03-1234-5678"}, "confidence": {"tel": 0.85}},
                {"fields": {"fax": "03-1234-5678"}, "confidence": {"fax": 0.6}},
            ]
        )

        assert not merged["fields"].get("fax")


class TestTheLongerAddressWins:
    def test_the_fuller_address_is_taken(self):
        merged = merge_fields(
            [
                {"fields": {"address": "Chiyoda-Ku TokyoJnPAN"}},
                {"fields": {"address": "VORT Suehiro-cho II 2F, 6-14-3, Sotokanda, Chiyoda-ku"}},
            ]
        )

        assert merged["fields"]["address"].startswith("VORT Suehiro-cho")

    def test_an_empty_address_never_wins(self):
        merged = merge_fields([{"fields": {"address": ""}}, {"fields": {"address": "東京都港区1-1"}}])

        assert merged["fields"]["address"] == "東京都港区1-1"

    def test_only_the_address_is_chosen_by_length(self):
        """ほかの項目は先のエンジンを優先したまま。"""
        merged = merge_fields(
            [
                {"fields": {"company_name": "kimusubi"}},
                {"fields": {"company_name": "kimusubi tokyo branch"}},
            ]
        )

        assert merged["fields"]["company_name"] == "kimusubi"


class TestTheSmilegateCard:
    """実テスト 21枚目。"""

    EASYOCR = """Yeo Seunghwan
Vice President
Indie/VRBusiness Division
Megaport Division Group
Cell +82-10-8933-1438
Email beastlov@smilegatecom
へ兵旦?り な,刃足 8り
forcreators stoveindiecom"""
    TESSERACT = """Smilegate
Holdings
Smilegate Holdings, Inc.
8F, First Tower 55, Bundang-ro,
Bundang-gu, Seongnam-si,
Gyeonggi-do, Republic of Korea
Yeo Seunghwan
Vice President
Indie/VR Business Division
Megaport Division Group
Cell  +82-10-8933-1438
Email beastlov@smilegate.com"""

    def fields(self) -> dict:
        parsed = [parse_fields(t.splitlines()) for t in (self.EASYOCR, self.TESSERACT)]
        return merge_fields(parsed)["fields"]

    def test_the_number_appears_once(self):
        got = self.fields()

        assert got["mobile"] == "+82-10-8933-1438"
        assert not got.get("tel")

    def test_the_whole_address_is_kept(self):
        assert "Republic of Korea" in self.fields()["address"]


class TestTheMeteoriseCard:
    """実テスト 17枚目。短いほうの住所が採られていた。"""

    EASYOCR = """Shunsuke Katsumata
Producer
Meteorise Inc:
VORTSuehiro-choIIZF6-14-3, Sotokanda
Chiyoda-Ku Tokyo 101-0021JnPAN
TEL 03-5817-4645 FAX03-5817-4644"""
    TESSERACT = """Shunsuke Katsumata
Producer
Meteorise Inc.
VORT Suehiro-cho II 2F, 6-14-3, Sotokanda,
Chiyoda-ku, Tokyo 101-0021, JAPAN
TEL 03-5817-4645    FAX 03-5817-4644"""

    def test_the_full_address_is_taken(self):
        parsed = [parse_fields(t.splitlines()) for t in (self.EASYOCR, self.TESSERACT)]
        address = merge_fields(parsed)["fields"]["address"]

        assert "VORT Suehiro-cho" in address
        assert "Sotokanda" in address

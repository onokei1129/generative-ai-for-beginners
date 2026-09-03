"""姓と名を、別々のエンジンから寄せ集めないこと（実テスト 13枚目）。

併用構成は項目ごとに取れたほうを採る。ところが姓と名は**1行を分けた
結果**なので、別々に採ると1人の名前にならない。

    印字      HIDEYA KOBAYASHI
    EasyOCR   町こ（飾りの読み崩れ）          → 姓 町こ  ／ 名 （空）
    tesseract HIDEYA KOBAYASHI              → 姓 KOBAYASHI ／ 名 HIDEYA
    併合の結果 姓『町こ』／ 名『HIDEYA』       ← 両方から1つずつ拾った

同じ行から分かれた項目は、まとめて片方のエンジンから採る。どちらを採るかは
**埋まった数の多いほう**で決める。片方しか読めていないエンジンより、
姓も名も読めているエンジンのほうが確からしい。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import merge_fields  # noqa: E402
from bcards.services.ocr import parse_fields  # noqa: E402


class TestNameFieldsAreTakenTogether:
    def test_the_engine_that_read_both_wins(self):
        merged = merge_fields(
            [
                {"fields": {"last_name": "町こ", "first_name": ""}},
                {"fields": {"last_name": "KOBAYASHI", "first_name": "HIDEYA"}},
            ]
        )

        assert merged["fields"]["last_name"] == "KOBAYASHI"
        assert merged["fields"]["first_name"] == "HIDEYA"

    def test_a_half_read_name_is_not_mixed_with_the_other_engine(self):
        """これが 13枚目で出た症状。姓と名が別人になる。"""
        merged = merge_fields(
            [
                {"fields": {"last_name": "町こ", "first_name": ""}},
                {"fields": {"last_name": "KOBAYASHI", "first_name": "HIDEYA"}},
            ]
        )

        assert merged["fields"]["first_name"] != "HIDEYA" or merged["fields"]["last_name"] != "町こ"

    def test_the_first_engine_still_wins_a_tie(self):
        merged = merge_fields(
            [
                {"fields": {"last_name": "ユン", "first_name": "ソクン"}},
                {"fields": {"last_name": "YOON", "first_name": "SEOKHOON"}},
            ]
        )

        assert merged["fields"]["last_name"] == "ユン"

    def test_the_second_engine_fills_a_group_the_first_missed(self):
        merged = merge_fields(
            [
                {"fields": {"last_name": "", "first_name": ""}},
                {"fields": {"last_name": "山田", "first_name": "太郎"}},
            ]
        )

        assert merged["fields"]["last_name"] == "山田"

    def test_the_reading_is_grouped_too(self):
        """せい・めい も1行を分けた結果。姓名と同じ扱いにする。"""
        merged = merge_fields(
            [
                {"fields": {"last_name_kana": "やまだ", "first_name_kana": ""}},
                {"fields": {"last_name_kana": "さとう", "first_name_kana": "はなこ"}},
            ]
        )

        assert merged["fields"]["last_name_kana"] == "さとう"
        assert merged["fields"]["first_name_kana"] == "はなこ"

    def test_fields_outside_a_group_are_still_taken_one_by_one(self):
        """まとめるのは同じ行から分かれたものだけ。"""
        merged = merge_fields(
            [
                {"fields": {"company_name": "株式会社サンプル", "email": ""}},
                {"fields": {"company_name": "", "email": "taro@example.co.jp"}},
            ]
        )

        assert merged["fields"]["company_name"] == "株式会社サンプル"
        assert merged["fields"]["email"] == "taro@example.co.jp"


class TestTheHideyaKobayashiCard:
    """実テスト 13枚目。姓『町こ』名『HIDEYA』になっていた。"""

    EASYOCR = """Co-「punder親方
HIDEYAKoBAYASHI
Discond; mcwyakaln わ心
ronniie: IK $9
上muil: hide U3UりU3lり+ huy @ざnailcwm
町こ
ロ?"""
    TESSERACT = """Co-Fpunder 親 方
HIDEYA KOBAYASHI
Discord: metaoyakata_bug
Fortnite: HK_-_39
E-mail: hide,03090309+bug@gmail.com
ハジ"""

    def fields(self) -> dict:
        parsed = [parse_fields(t.splitlines()) for t in (self.EASYOCR, self.TESSERACT)]
        return merge_fields(parsed)["fields"]

    def test_the_name_comes_from_the_engine_that_read_it(self):
        got = self.fields()

        assert got["last_name"] == "KOBAYASHI"
        assert got["first_name"] == "HIDEYA"

    def test_the_email_is_still_taken(self):
        assert self.fields()["email"] == "hide.03090309+bug@gmail.com"

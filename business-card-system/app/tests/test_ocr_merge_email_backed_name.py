"""併合のときも、メールが裏づける氏名を採る（実テスト 7枚目・NEXON）。

    印字       Sangeon Lee
    easyocr    SangeonLee        ← 空白が落ちて1語になり、氏名の形にならない
               巨   メロ          ← 汚れの読み崩れ。これが氏名になっていた
    tesseract  Sangeon Lee       ← 正しく読めている

読み取り機ごとの取り出しでは、easyocr の側に氏名の候補が `巨 メロ` しか
無い。tesseract は `Lee`／`Sangeon` を取れている。併合は「姓と名の埋まった
数」で選ぶので、どちらも2つ埋まっていて**先に挙げた easyocr が勝つ**。

メールは併合したあとなら揃っている（`eonlee@nexongames.co.kr`。easyocr は
点を落として `eonlee@nexongamescokr` と読み、形が合わないので捨てられる）。
これを裏づけに使う。`lee` は `eonlee` に含まれる。

## 日本語の氏名を捨てないための歯止め

日本語の名刺では、メールがローマ字の氏名を裏づけることが多い
（`sachiko.hasegawa@gree.net`）。裏づけだけで選ぶと、正しい漢字の氏名を
押しのける。**3文字以下の候補だけを降ろす**——読み崩れは短く、本物の
氏名はそれより長い。

    巨メロ        3文字  → 降ろす
    長谷川幸子    5文字  → 残す
    竹廣乃葉      4文字  → 残す（実テスト 16枚目）
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import merge_fields  # noqa: E402
from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheNexonCard:
    EASYOCR = [
        "NEXON GAMES",
        "2621, Nambusunhwan-ro,",
        "Gangnam-gu, Seoul, Korea",
        "06267",
        "巨   メロ",
        "SangeonLee   T +82.2.6421.7777",
        "Planning G Coordination Dept F +82.2,569.6448",
        "Team Member   eonlee@nexongamescokr",
    ]

    TESSERACT = [
        "NEXON GAMES",
        "2621, Nambusunhwan-ro,",
        "Gangnam-gu, Seoul, Korea,",
        "06267",
        "Sangeon Lee",
        "Planning & Coordination Dept",
        "Team Member",
        "E eonlee@nexongames.co.kr",
    ]

    def merged(self) -> dict:
        return merge_fields([
            parse_fields(self.EASYOCR),
            parse_fields(self.TESSERACT),
        ])["fields"]

    def test_the_name_the_email_backs_is_taken(self):
        got = self.merged()

        assert got["last_name"] == "Lee"
        assert got["first_name"] == "Sangeon"

    def test_the_broken_reading_is_not_used(self):
        got = self.merged()

        assert got["last_name"] != "巨"
        assert got["first_name"] != "メロ"

    def test_the_other_fields_are_untouched(self):
        got = self.merged()

        assert got["company_name"] == "NEXON GAMES"
        assert got["email"] == "eonlee@nexongames.co.kr"


class TestJapaneseNamesAreKept:
    def test_a_kanji_name_longer_than_three_is_kept(self):
        """`sachiko.hasegawa@gree.net` はローマ字を裏づけるが、漢字を残す。"""
        merged = merge_fields([
            parse_fields(["グリー株式会社", "長谷川 幸子", "sachiko.hasegawa@gree.net"]),
            parse_fields(["グリー株式会社", "Sachiko Hasegawa", "sachiko.hasegawa@gree.net"]),
        ])["fields"]

        assert (merged["last_name"], merged["first_name"]) == ("長谷川", "幸子")

    def test_the_scenario_writer_card_is_kept(self):
        """実テスト 16枚目。`竹廣 乃葉` は4文字なので降ろさない。"""
        merged = merge_fields([
            parse_fields(["竹廣　乃葉", "Noba Takehiro", "noba.takehiro@gmail.com"]),
            parse_fields(["Ve 乃 葉", "Noba Takehiro", "noba.takehiro@gmail.com"]),
        ])["fields"]

        assert (merged["last_name"], merged["first_name"]) == ("竹廣", "乃葉")


class TestNothingHappensWithoutBacking:
    def test_the_first_engine_still_wins_when_neither_is_backed(self):
        merged = merge_fields([
            parse_fields(["株式会社サンプル", "山田 太郎", "info@example.co.jp"]),
            parse_fields(["株式会社サンプル", "Taro Yamada", "info@example.co.jp"]),
        ])["fields"]

        assert (merged["last_name"], merged["first_name"]) == ("山田", "太郎")

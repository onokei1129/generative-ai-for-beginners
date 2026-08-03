"""ふりがなは、読む漢字より短くならない（実テスト 19枚目）。

沖縄労働局の名刺で、ロゴの標語がふりがなとして採られていた。

    印字   ひと、くらし、みらいのために      ← ロゴの標語
           需給調整事業専門相談員            ← 役職
           迎　亮一                        ← 氏名

    結果   せい『みら』／ めい『いのために』
           姓『霧給』／ 名『調整事業専門相談員』

ひらがなの行の次が氏名らしければ、その組を氏名とふりがなに採る作りだった。
標語も「ひらがなの行」なので当たってしまう。

漢字はどれも1文字につき1つ以上のかなで読むので、**ふりがなは漢字の氏名
より短くならない**。`みらいのために`（7文字）で `霧給調整事業専門相談員`
（11文字）は読めない。字数で見分ける。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import merge_fields, parse_fields  # noqa: E402


class TestAReadingIsNotShorterThanTheName:
    def test_a_slogan_is_not_taken_as_a_reading(self):
        """見分けているのは**前の行**。標語は読点付きのひらがなの行から
        続く。ふりがなには読点が入らない。"""
        got = parse_fields(
            ["ひと、くらし、", "みらいのために", "霧給調整事業専門相談員", "迎 亮一"]
        )["fields"]

        assert got["last_name_kana"] != "みら"
        assert got["first_name_kana"] != "いのために"

    def test_a_reading_far_from_the_name_is_still_taken(self):
        """OCRの行の順番は印字の順番と違う。近さを条件にしてはいけない
        （実際に条件にして、ふりがなの正答率が 65%→50% に落ちた）。"""
        got = parse_fields(
            [
                "株式会社みらい商事",
                "鈴木一郎",
                "TEL 052-111-2222",
                "ichiro@mirai.example",
                "すず き いち ろう",
            ]
        )["fields"]

        assert got["last_name_kana"] == "すずき"
        assert got["first_name_kana"] == "いちろう"

    def test_a_real_reading_is_still_taken(self):
        got = parse_fields(["やまだ たろう", "山田 太郎"])["fields"]

        assert got["last_name_kana"] == "やまだ"
        assert got["first_name_kana"] == "たろう"
        assert got["last_name"] == "山田"

    def test_a_one_character_given_name_still_works(self):
        """`おさむ`（3文字）で `冨田 修`（3文字）。同数は通す。"""
        got = parse_fields(["とみた おさむ", "冨田 修"])["fields"]

        assert got["last_name"] == "冨田"
        assert got["first_name"] == "修"

    def test_a_reading_longer_than_the_name_is_fine(self):
        got = parse_fields(["いとう なおき", "伊藤 直樹"])["fields"]

        assert got["last_name_kana"] == "いとう"
        assert got["last_name"] == "伊藤"


class TestTheLabourBureauCard:
    """実テスト 19枚目。"""

    EASYOCR = """沖縄労働局 職業安定部
霧給調整事業室
ひと; くらし,
みらいのために
霧給調整事業専門相談員
迎 亮一
〒900-0006 沖縄県那覇市おもろまち2丁目1番1号
那爾第2地方合同庁舎1号館3階
電 話(098)868-1637
E-mail mukai-ryouichipm3@mhlygojp"""
    TESSERACT = """沖縄 労働 局 職業 安定 部
需給 調整 事業 室
迎 亮一
900-0006 沖縄 県 那覇 市 おもろ まち 2丁目 1番 1号
那覇 第 2 地方 合同 庁舎 1号 館 3階
電 話(098)868-1637
E-mail : mukai-ryouichi.pm3@mhlw.go.jp"""

    def fields(self) -> dict:
        parsed = [parse_fields(t.splitlines()) for t in (self.EASYOCR, self.TESSERACT)]
        return merge_fields(parsed)["fields"]

    def test_the_name_is_the_person_not_the_role(self):
        got = self.fields()

        assert got["last_name"] == "迎"
        assert got["first_name"] == "亮一"

    def test_the_slogan_does_not_become_the_reading(self):
        got = self.fields()

        assert not got["last_name_kana"]
        assert not got["first_name_kana"]

    def test_the_role_lands_in_the_title(self):
        assert "相談員" in self.fields()["title"]

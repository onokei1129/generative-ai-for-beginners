"""ロゴの標語をふりがなにしない（実テスト 18枚目）。

読み取りの実物で原因が確かめられた。

    ひと 、 くら し 、   電 給 調 EE     ← 2段組みの行
    みらい の だ め に

「前の行がひらがなの文なら、この行はその続き」という規則は入れてあるが、
**段組みを切ったせいで前の行が入れ替わっている**。切ったあとの並びは

    ひと、くらし、
    電給調EE          ← これが「前の行」になる
    みらいのだめに

`、` で終わるひらがなの行は、そこで終わっていない文である。**その次に来る
ひらがなの行は、間に何行挟まっていても続き**とみなす。

## 3枚目については、直せないと判断した

    印字       ユン　ソクン ／ SEOKHOON YOON
    easyocr    コン ゾクソ        ← 読み崩れ。これが氏名になっていた
    tesseract  ID ツク ル /       ← 別の読み崩れ
    両方        SEOKHOON YOON

「もう一方の読み取り機も同じ文字列を読んでいるか」を裏づけにして英字を
採る、という直しを試した。**やめた**。理由は2つ。

1. 合成サンプルで正答率が下がった（H 77.2% → 76.4%。姓 70→65％、
   名 75→70％）。ラテン文字はどちらの読み取り機も同じに読むので、
   裏づけは英字ばかりに付き、正しい日本語の氏名を押しのける
2. そもそも**正解にならない**。この名刺の正解は印字どおりの
   『ユン』『ソクン』で、`YOON`『SEOKHOON』ではない

`ユン ソクン` が `コン ゾクソ` と読まれたのは読み取りの失敗であって、
項目の取り出し側では直せない。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheSlogan:
    TESSERACT = [
        "6 う   Ry EIR HA",
        "ひと 、 くら し 、   電 給 調 EE",
        "みらい の だ め に",
        "需給 調整 事業 専門 相談",
        "〒900-0006 沖縄 市 お も ろ ま ち 2 丁 目 1 番 1 号",
        "E-mail : mukai-ryouichipm3@mhlw.go.jp",
    ]

    EASYOCR = [
        "沖縄労働局 職業安定部",
        "霧給調整事業室",
        "ひと; くらし,",
        "みらいのたのに",
        "霧給調整事業専門相談員",
        "迎 亮一",
        "テ900-0006 沖縄県那爾市おもろまち2丁目1番1号",
    ]

    def test_the_slogan_is_not_a_reading(self):
        got = parse_fields(self.TESSERACT)["fields"]

        assert got["last_name_kana"] == ""
        assert got["first_name_kana"] == ""

    def test_the_same_slogan_read_by_the_other_engine(self):
        got = parse_fields(self.EASYOCR)["fields"]

        assert got["last_name_kana"] == ""
        assert got["first_name_kana"] == ""

    def test_the_name_is_still_taken(self):
        got = parse_fields(self.EASYOCR)["fields"]

        assert (got["last_name"], got["first_name"]) == ("迎", "亮一")

    def test_a_real_reading_is_still_taken(self):
        """`、` で終わらないひらがなの行は、これまでどおりふりがな。"""
        got = parse_fields(["株式会社サンプル", "やまだ たろう", "山田 太郎"])["fields"]

        assert (got["last_name_kana"], got["first_name_kana"]) == ("やまだ", "たろう")

    def test_a_hiragana_line_without_a_comma_is_not_a_sentence(self):
        """読点で終わらないひらがなの行は、続きを持たない。

        `とみた` / `おさむ` のように、姓と名のふりがなが別の行として読まれる
        名刺がある。読点が無ければそちらとして扱う（既存の規則）。
        """
        got = parse_fields(["株式会社サンプル", "とみた", "おさむ", "冨田 修"])["fields"]

        assert (got["last_name_kana"], got["first_name_kana"]) == ("とみた", "おさむ")


class TestTheSloganCanComeInEitherOrder:
    """標語の2行は、順番が入れ替わって読まれることがある。

    実テスト19枚目（沖縄労働局）のロゴの標語で、tesseract が逆順に読んでいた:

        印字        ひと、くらし、
                    みらいのために

        tesseract   みらい の た め に      ← こちらが先
                    ひと 、 く らし 、       ← 読点で終わる行が後ろ

    歯止めは手前しか見ていなかったため、この向きでは効かず、
    せい『みらいの』／めい『ために』としてふりがなに入っていた。
    """

    TESSERACT = [
        "沖縄 労働 局 HRA EB",
        "う",
        "給 調整 事業 室",
        "みらい の た め に",
        "ひと 、 く らし 、",
        "給 調 整 事業 専門 相談 買",
        "〒900-0006",
        "E-mail : mukai-ryouichipm3@mhlw.go.jp",
    ]

    def test_the_slogan_does_not_become_a_reading(self):
        got = parse_fields(self.TESSERACT)["fields"]

        assert got["last_name_kana"] == ""
        assert got["first_name_kana"] == ""

    def test_the_same_holds_when_the_order_is_printed(self):
        """印字どおりの順番でも、これまでどおり除外する。"""
        printed = list(self.TESSERACT)
        printed[3], printed[4] = printed[4], printed[3]

        got = parse_fields(printed)["fields"]

        assert got["last_name_kana"] == ""
        assert got["first_name_kana"] == ""

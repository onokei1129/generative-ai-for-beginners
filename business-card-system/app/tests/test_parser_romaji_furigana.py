"""氏名の脇のローマ字を、ふりがなにする（services/ocr/romaji・parser）。

日本の名刺は、ふりがなの位置にローマ字を刷ることが多い。

    木村 央志
    Nakaji Kimura          ← ふりがなの位置

これまでふりがなは「ひらがなだけの行」からしか取っておらず、この形の名刺は
ふりがなが空欄のままだった。実テスト（223枚）ではこの形が多く、そのぶんが
すべて手入力になっていた。

## 直せない部分がある

名刺のローマ字はパスポート式ヘボンで刷られ、**長音が落ちる**。

    佐藤  さとう  →  Sato
    裕子  ゆうこ  →  Yuko

落ちた長音は戻せない。「語尾の o は必ず おう」という規則にもできない
——`Nakao`（なかお）・`Matsuo`（まつお）・`Ono`（おの）が壊れる。
`Ono`（おの）と `Kano`（かのう）は字面が同じ形で、手がかりが無い。

実測（実在の姓50・名20）は 姓82% / 名55% / 合計74%。

**推測で長音を足さない。** 名刺が長音を書いているとき（`ō` `Itoh` `Ohno`
`ou` `oo`）だけ長音にする。外れるのは 佐藤・太郎 のような漢字を見れば読みが
分かる名前で、当たるのは 央志＝なかじ のような珍しい読み。画面では未確認
（黄色）で出るので、誤りは気づける側に寄る。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402
from bcards.services.ocr.romaji import name_to_hiragana, to_hiragana  # noqa: E402


class TestTheSyllables:
    @pytest.mark.parametrize(
        "roma,kana",
        [
            ("Kimura", "きむら"),
            ("Nakaji", "なかじ"),
            ("Yamada", "やまだ"),
            ("Hasegawa", "はせがわ"),
            ("Shimizu", "しみず"),
            ("Matsumoto", "まつもと"),
            ("Chiba", "ちば"),
            ("Fujii", "ふじい"),
        ],
    )
    def test_plain_words(self, roma: str, kana: str):
        assert to_hiragana(roma) == kana


class TestTheSmallTsu:
    """`tt` `pp` `ss` は促音。**母音・`m`・`h` は促音にしない。**"""

    @pytest.mark.parametrize(
        "roma,kana",
        [
            ("Hattori", "はっとり"),
            ("Sapporo", "さっぽろ"),
            ("Issei", "いっせい"),
            ("Ishii", "いしい"),      # 母音の重なり。促音ではない
            ("Gumma", "ぐんま"),      # `mm` は撥音
            ("Ohhashi", "おおはし"),  # 長音＋は
        ],
    )
    def test_doubles(self, roma: str, kana: str):
        assert to_hiragana(roma) == kana


class TestTheN:
    """母音と `y` の前以外の `n` は「ん」。"""

    @pytest.mark.parametrize(
        "roma,kana",
        [
            ("Ken", "けん"),          # 語末
            ("Honda", "ほんだ"),
            ("Kanno", "かんの"),
            ("Namba", "なんば"),
            ("Shimbashi", "しんばし"),  # b の前の `m`
            ("Jun'ichi", "じゅんいち"),  # 区切りの `'`
            ("Kaneko", "かねこ"),      # 母音の前は「な行」
        ],
    )
    def test_syllabic_n(self, roma: str, kana: str):
        assert to_hiragana(roma) == kana

    def test_a_trailing_n_is_not_treated_as_a_vowel(self):
        """語末を「母音が続く」と見ないこと。

        Python では空文字がどんな文字列にも含まれるため、
        `following not in "aiueoy"` と書くと語末が母音扱いになる。
        `Ken` の `n` が「ん」にならず、行ごと断られていた。
        """
        assert to_hiragana("Ken") is not None


class TestTheLongVowels:
    """名刺が書いている長音だけ伸ばす。"""

    @pytest.mark.parametrize(
        "roma,kana",
        [
            ("Satō", "さとう"),
            ("Tarō", "たろう"),
            ("Yōko", "ようこ"),
            ("Ryūnosuke", "りゅうのすけ"),
            ("Itoh", "いとう"),
            ("Kohno", "こうの"),
            ("Ohno", "おおの"),      # 語頭の長い「オー」はほぼ「大」
            ("Ōno", "おおの"),
            ("Ohtsuka", "おおつか"),
            ("Kohei", "こへい"),     # 母音が続く `h` は「へ」の h。伸ばさない
        ],
    )
    def test_marked_long_vowels(self, roma: str, kana: str):
        assert to_hiragana(roma) == kana

    @pytest.mark.parametrize(
        "roma,short",
        [
            ("Sato", "さと"),     # 佐藤 さとう
            ("Ito", "いと"),      # 伊藤 いとう
            ("Yuko", "ゆこ"),     # 裕子 ゆうこ
            ("Taro", "たろ"),     # 太郎 たろう
            ("Ryota", "りょた"),  # 亮太 りょうた
        ],
    )
    def test_dropped_long_vowels_are_left_short(self, roma: str, short: str):
        """落ちた長音は**足さない**。

        足す規則にすると `Nakao`（なかお）`Matsuo`（まつお）`Ono`（おの）が
        壊れる。`Ono`（おの）と `Kano`（かのう）は字面が同じ形で、どちらか
        を決める手がかりが無い。短いまま出して、画面で直してもらう。
        """
        assert to_hiragana(roma) == short

    @pytest.mark.parametrize("roma,kana", [("Nakao", "なかお"), ("Matsuo", "まつお"), ("Ono", "おの")])
    def test_short_o_endings_survive(self, roma: str, kana: str):
        assert to_hiragana(roma) == kana


class TestItRefusesWhatItCannotBuild:
    """作れない綴りが1つでもあれば None。**部分的な結果を返さない。**"""

    @pytest.mark.parametrize(
        "word",
        ["Patricio", "Vasquez", "Jeong", "German", "Kurnikov", "Seunghwan", "Smith", "EIR", "Ry", ""],
    )
    def test_not_japanese_romaji(self, word: str):
        assert to_hiragana(word) is None

    def test_one_bad_word_drops_the_whole_name(self):
        """片方だけ入れない。姓と名がずれたふりがなは、空欄より悪い。"""
        assert name_to_hiragana("Kenji Vasquez") is None


class TestTheDonutsCard:
    """実テスト24枚目。ふりがなの位置に `Nakaji Kimura` が刷られている。"""

    LINES = [
        "株 式 会 社 Donuts",
        "木村 央志",
        "Nakaji Kimura",
        "ゲー ム 統 括 部",
        "東京都渋谷区代々木2-2-1",
    ]

    def test_the_furigana_is_filled(self):
        got = parse_fields(self.LINES)["fields"]

        assert (got["last_name"], got["first_name"]) == ("木村", "央志")
        assert (got["last_name_kana"], got["first_name_kana"]) == ("きむら", "なかじ")

    def test_the_order_follows_the_latin_one(self):
        """`Nakaji Kimura` は 名 姓。漢字の 木村 央志 と並びが逆になる。"""
        got = parse_fields(self.LINES)["fields"]

        assert got["last_name_kana"] == "きむら", "姓のふりがなに名が入っている"

    def test_it_is_weaker_than_printed_furigana(self):
        """読み取った文字ではなく、そこから導いたもの。"""
        assert parse_fields(self.LINES)["confidence"]["last_name_kana"] == 0.5


class TestItOnlyAppliesToJapaneseCards:
    def test_a_foreign_card_is_left_alone(self):
        """`Mike`（みけ）のような英語名も綴りだけなら通る。同じ名刺に漢字
        かなの氏名があることが、日本語の音写である証拠になる。"""
        got = parse_fields([
            "AONE GAMES",
            "Patricio Vasquez",
            "Chief Executive Officer",
            "patricio@aonegames.com",
        ])["fields"]

        assert got["last_name_kana"] == ""
        assert got["first_name_kana"] == ""

    def test_an_english_name_without_a_japanese_name_is_left_alone(self):
        got = parse_fields(["ACME Inc", "Mike Kate", "Sales"])["fields"]

        assert got["last_name_kana"] == ""


class TestItPicksTheLineNearestTheName:
    """地名は綴りでは弾けないので、位置で分ける。

    `Shibuya Tokyo` も日本語のローマ字なのできれいに変換でき、しぶや／ときょ
    がふりがなに入っていた。語彙で弾く手は使えない——千葉・足立・太田・
    中野・目黒・荒川・品川は、どれも区名であると同時に実在の姓で、落とせば
    本物の氏名を巻き添えにする。

    ローマ字の氏名は氏名の脇に刷られ、住所の断片は住所の塊の中にある。
    """

    def test_the_name_beats_a_later_place(self):
        got = parse_fields([
            "株式会社サンプル",
            "木村 央志",
            "Nakaji Kimura",
            "東京都渋谷区代々木2-2-1",
            "Shibuya Tokyo",
        ])["fields"]

        assert (got["last_name_kana"], got["first_name_kana"]) == ("きむら", "なかじ")

    def test_the_name_beats_an_earlier_place(self):
        """行の順番ではなく、氏名からの近さで選ぶ。"""
        got = parse_fields([
            "Shibuya Tokyo",
            "株式会社サンプル",
            "木村 央志",
            "Nakaji Kimura",
        ])["fields"]

        assert (got["last_name_kana"], got["first_name_kana"]) == ("きむら", "なかじ")

    def test_it_reaches_past_a_few_lines(self):
        """読み取りの行の順番は印字の順番と違う。隣とは限らない。

        実テスト24枚目では、氏名の4行あとにローマ字が来ていた。
        """
        got = parse_fields([
            "Donuts",
            "T",
            "株 式 会 社 Donuts",
            "木村 央志",
            "c",
            "151 0053",
            "Nakaji Kimura",
            "ゲー ム 統 括 部",
        ])["fields"]

        assert (got["last_name_kana"], got["first_name_kana"]) == ("きむら", "なかじ")


class TestPrintedFuriganaStillWins:
    def test_the_hiragana_line_beats_the_romaji(self):
        """印字されたふりがながあれば、そちらを使う（導いたものより確か）。"""
        got = parse_fields([
            "やまだ たろう",
            "山田 太郎",
            "Taro Yamada",
            "株式会社サンプル",
        ])["fields"]

        assert (got["last_name_kana"], got["first_name_kana"]) == ("やまだ", "たろう")

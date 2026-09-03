"""左右2段組みの名刺（services/ocr/parser.py）。

名刺は左に社名・ロゴ、右に連絡先を置く体裁が多い。OCRは同じ高さにある文字を
1行にまとめて返すため、左段の飾り・ロゴと右段の本文が1行に混ざる。

実テスト（225枚）の3枚で、これが原因で項目が総崩れになっていた。

    読み  `Sangeon Lee        T +82.2.6421.7777`
          `Team Member        E eonlee@example.co.kr`

    修正前  氏名・社名・部署・役職がすべて空。FAXと携帯も空
            （ラベルが読めず、電話に押し出された）
    修正後  姓『Sangeon』名『Lee』／社名『NEXON GAMES』／
            部署『Planning & Coordination Dept』／電話・FAX・携帯すべて

段の間は必ず広く空くので、空白2つ以上を段の区切りとする。語の間の空白1つ
（`沖縄県 東京事務所` `T E L:03-…` `佐々木 健`）は区切りにしない。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import parse_fields, split_columns  # noqa: E402

# 実データ（6枚目）のOCR結果。左段はロゴとQRコードの読み崩れ。
# `冨田`→`宮田`、`企業誘致`→`企業請致` はOCRの誤読で、ここでは直せない。
TOMITA = [
    "=                 - -             =,",
    "©    沖縄県 東京事務所",
    "'Okinawa",
    "A                      とみた      おさむ",
    "企業請致チーム            _s",
    "de Fh SHB eA           宮田  修",
    "へ特設サイトノ",
    "Ob eC F 102-0093 東京都千代田区平河町2-6-3 Ai AP APE LOBE",
    "EN         T E L:03-5212-9087",
    "mytics       F A X:03-5212-9086",
    "沖縄県企業立地おガイド   E-mail:ab002011@prcfokinawalg.jp",
]

# 実データ（7枚目）。海外の名刺で、連絡先のラベルが頭文字1文字。
NEXON = [
    "時NEXO N              NEXON GAMES",
    "GAMES               2621, Nambusunhwan-ro,",
    "Gangnam-gu, Seoul, Korea,",
    "06267",
    "Sangeon Lee        T +82.2.6421.7777",
    "Planning & Coordination Dept     F +82.2.569.6448",
    "Team 1               C +82.10.3661.0778",
    "Team Member          E eonlee@nexongames.co.kr",
]

# 実データ（10枚目）。`匡志` が `EBS` と読まれている（OCRの誤読）。
EDGE = [
    "x)  Edge Creators",
    "代表取締役社長",
    "坂本  EBS",
    "を",
    "ん",
    "mobile: 090-6596-0349        る 。",
    "e-mail: sakamoto@edgecre.co.jp     2",
    "ro,",
    "の",
]


def fields(lines: list[str]) -> dict:
    return parse_fields(lines)["fields"]


class TestSplitColumns:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("Sangeon Lee        T +82.2.6421.7777", ["Sangeon Lee", "T +82.2.6421.7777"]),
            ("x)  Edge Creators", ["x)", "Edge Creators"]),
            ("A     とみた     おさむ", ["A", "とみた", "おさむ"]),
        ],
    )
    def test_wide_gaps_are_column_breaks(self, line: str, expected: list[str]):
        assert split_columns(line) == expected

    @pytest.mark.parametrize(
        "line",
        [
            "沖縄県 東京事務所",  # 語の区切り
            "T E L:03-5212-9087",  # 字間を空けたラベル
            "佐々木 健",  # 姓と名
            "株式会社サンプル商事",
        ],
    )
    def test_a_single_space_is_not_a_column_break(self, line: str):
        assert split_columns(line) == [line]


class TestSingleLetterContactLabels:
    """`T` `F` `C` だけで種別を示す海外の名刺。

    修正前は3つとも電話として扱われ、先に入った1件だけが残って
    FAXと携帯が空になっていた。
    """

    def test_each_number_goes_to_its_own_field(self):
        got = fields(NEXON)

        assert got["tel"] == "+82.2.6421.7777"
        assert got["fax"] == "+82.2.569.6448"
        assert got["mobile"] == "+82.10.3661.0778"

    def test_a_letter_inside_a_word_is_not_a_label(self):
        """`Team 1` の `T` などをラベルにしないこと。"""
        from bcards.services.ocr.parser import find_labels

        assert find_labels("Fantastic 03-1234-5678") == []


class TestForeignCardFields:
    def test_the_name_and_organisation_are_found(self):
        """`Sangeon Lee` の姓は Lee。ラテン文字は「名 姓」の順で印字される。

        実テストで、この名刺の姓が Sangeon になっていた（ご本人に確認：
        Lee が姓、Sangeon が名）。
        """
        got = fields(NEXON)

        assert (got["last_name"], got["first_name"]) == ("Lee", "Sangeon")
        assert got["company_name"] == "NEXON GAMES"
        assert got["department_name"] == "Planning & Coordination Dept"

    def test_a_country_domain_still_matches_the_company(self):
        """`.kr` のような国別ドメインを外して社名と照合すること。"""
        got = fields(NEXON)

        assert got["company_name"] == "NEXON GAMES"

    def test_a_broken_fragment_does_not_win_over_the_full_name(self):
        """ロゴの読み崩れ `時NEXO` もドメインの先頭に一致するが、
        いちばん長い行（`NEXON GAMES`）を採ること。"""
        got = fields(NEXON)

        assert got["company_name"] != "時NEXO"


class TestReadingSplitAcrossColumns:
    def test_two_hiragana_lines_become_one_reading(self):
        """`とみた` `おさむ` を1行のふりがなと見て割らないこと。

        修正前は せい『とみ』めい『た』になっていた。氏名の行は
        直後ではなく、ロゴと部署を挟んだ先にある。
        """
        got = fields(TOMITA)

        assert got["last_name_kana"] == "とみた"
        assert got["first_name_kana"] == "おさむ"

    def test_the_kanji_name_and_contacts_survive(self):
        got = fields(TOMITA)

        # 宮田 は OCR の誤読（正しくは冨田）。段の分割が効いていることの確認
        assert got["first_name"] == "修"
        assert got["tel"] == "03-5212-9087"
        assert got["fax"] == "03-5212-9086"
        assert got["email"] == "ab002011@prcfokinawalg.jp"
        assert got["postal_code"] == "102-0093"


class TestJapaneseNameWinsOverAsciiLine:
    """英字だけの2語より、日本語の氏名を先に採ること。

    実データ（10枚目）では社名を氏名として登録し
    （姓『Edge』名『Creators』）、本来の『坂本』が空になっていた。
    """

    def test_the_person_is_the_japanese_line(self):
        got = fields(EDGE)

        assert got["last_name"] == "坂本"
        assert got["company_name"] == "Edge Creators"
        assert got["title"] == "代表取締役社長"

    def test_an_english_card_still_gets_its_name(self):
        """日本語の候補が無ければ英字の行を採る（英語の名刺を壊さない）。"""
        got = fields(NEXON)

        assert (got["last_name"], got["first_name"]) == ("Lee", "Sangeon")


class TestNoiseAroundTheColumns:
    def test_stray_single_characters_are_not_a_name(self):
        """段の外に落ちた1文字（`を` `ん` `の`）を氏名・ふりがなにしないこと。"""
        got = fields(EDGE)

        assert got["last_name_kana"] == ""
        assert got["first_name_kana"] == ""

    def test_a_number_beside_a_contact_line_is_dropped(self):
        got = fields(EDGE)

        assert got["mobile"] == "090-6596-0349"
        assert got["email"] == "sakamoto@edgecre.co.jp"


class TestTheRealOcrTextOfCardSeven:
    """7枚目の**実際のOCR結果**をそのまま通す。

    ここまで、この名刺の読み取り結果を組み直して確かめていたが、実物とは
    違っていた（住所も郵便番号も再現しなかった）。`この1枚を調べる` で
    出力された文字をそのまま置く。組み直しでは気づけないずれを止める。

    ロゴが `時NEXロN` `GAMES` と読み崩れて左段に入る点も、実物どおり。
    """

    RAW = [
        "時NEXロN                  NEXON GAMES",
        "GAMES                  2621, Nambusunhwan-ro,",
        "",
        "Gangnam-gu, Seoul, Korea,",
        "06267",
        "",
        "Sangeon Lee            T +82.2.6421.7777",
        "",
        "Planning & Coordination Dept         F +82.2.569.6448",
        "",
        "Team 1                             C +82.10.3661.0778",
        "",
        "Team Member                        E eonlee@nexongames.co.kr",
    ]

    def result(self) -> dict[str, str]:
        return fields(self.RAW)

    @pytest.mark.parametrize(
        ("key", "want"),
        [
            ("last_name", "Lee"),
            ("first_name", "Sangeon"),
            ("company_name", "NEXON GAMES"),
            ("department_name", "Planning & Coordination Dept"),
            ("title", "Team Member"),
            ("address", "2621, Nambusunhwan-ro, Gangnam-gu, Seoul, Korea,"),
            ("postal_code", "06267"),
            ("tel", "+82.2.6421.7777"),
            ("fax", "+82.2.569.6448"),
            ("mobile", "+82.10.3661.0778"),
            ("email", "eonlee@nexongames.co.kr"),
        ],
    )
    def test_every_printed_item_is_extracted(self, key: str, want: str):
        assert self.result()[key] == want

    def test_the_misread_logo_does_not_become_a_field(self):
        """`時NEXロN` `GAMES` はロゴの読み崩れ。項目にしないこと。"""
        got = self.result()

        for key in ("last_name", "first_name", "company_name", "department_name", "title"):
            assert "時NEX" not in got[key]

    def test_the_postal_code_goes_into_its_own_field(self):
        """`06267` は韓国の5桁。

        以前はここで「日本の3桁-4桁の欄には入れず、住所に残す」としていたが、
        実テストで**郵便番号が取れていない**という報告を受けたため改めた。
        利用者から見れば、名刺に印字された郵便番号は郵便番号の欄に入るのが
        当たり前で、日本の形かどうかは関係がない。
        """
        got = self.result()

        assert got["postal_code"] == "06267"
        assert not got["address"].endswith("06267")

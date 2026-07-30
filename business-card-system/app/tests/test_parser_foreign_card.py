"""外国名・英字表記の名刺（services/ocr/parser.py）。

実データ（チリの制作会社の名刺）で、7項目のうち3項目しか取れていなかった。
OCRは読めていて、抽出側で落としていたものが5件あった。

    姓名     ロゴの `AONE GAMES` を氏名にしていた
    ふりがな  カタカナの氏名 `パトリシオ　バスケス` をふりがな扱いにし、姓名が空になった
    会社名    `AONE GAMES` は法人格の語を含まないため取れていなかった
    役職     `エグゼクティブ・プロデューサー / Executive Producer` → `プロデューサー`
    住所     `Santa Beatriz 111 of 1008, …` は都道府県が無いため取れていなかった

日本語の名刺を壊していないことの確認を対にして置く。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import parse_fields, pick_title, split_person_name  # noqa: E402

# 実データのOCR結果に相当する行
FOREIGN_CARD = [
    "パトリシオ　バスケス",
    "Patricio Vásquez",
    "エグゼクティブ・プロデューサー / Executive Producer",
    "patricio@aonegames.com",
    "携帯： +56 9 6669 4618",
    "Santa Beatriz 111 of 1008, Providencia. Santiago de Chile",
    "AONE GAMES",
]

JAPANESE_CARD = [
    "株式会社サンプル商事",
    "営業本部 第一営業部",
    "部長",
    "やまだ たろう",
    "山田 太郎",
    "〒100-0001 東京都千代田区千代田1-1-1",
    "TEL 03-1234-5678  FAX 03-1234-5679",
    "taro.yamada@example.co.jp",
]


def fields(lines: list[str]) -> dict:
    return parse_fields(lines)["fields"]


class TestKatakanaName:
    def test_katakana_name_is_a_name_not_a_reading(self):
        """カタカナだけの行を「ふりがな」にしないこと。

        ふりがなはひらがなで印字される。カタカナ扱いにすると、外国名の名刺で
        氏名が空になり、ふりがな欄に氏名が入る。
        """
        got = fields(FOREIGN_CARD)

        assert got["last_name"] == "パトリシオ"
        assert got["first_name"] == "バスケス"
        assert got["last_name_kana"] == ""
        assert got["first_name_kana"] == ""

    def test_hiragana_reading_still_works(self):
        """ひらがなのふりがなは従来どおり拾うこと。"""
        got = fields(JAPANESE_CARD)

        assert got["last_name"] == "山田"
        assert got["first_name"] == "太郎"
        assert got["last_name_kana"] == "やまだ"
        assert got["first_name_kana"] == "たろう"


class TestKatakanaSplit:
    """OCRがカタカナ名の途中に空白を入れる場合の分け方。

    実データでは `パトリシオ　バスケス` が `パト リシオ バスケス` と読まれ、
    先頭の空白で切って `パト` / `リシオ バスケス` になっていた。
    どこが語の切れ目かは字面では決まらないため、長さの釣り合いで決める。
    """

    @pytest.mark.parametrize(
        ("printed", "expected"),
        [
            ("パト リシオ バスケス", ("パトリシオ", "バスケス")),
            ("パトリシオ バスケス", ("パトリシオ", "バスケス")),
            ("ジョ ン スミス", ("ジョン", "スミス")),
        ],
    )
    def test_katakana_name_is_split_by_balance(self, printed: str, expected: tuple[str, str]):
        assert split_person_name(printed) == expected

    @pytest.mark.parametrize(
        ("printed", "expected"),
        [
            ("山田 太郎", ("山田", "太郎")),
            ("佐々木 健", ("佐々木", "健")),
            ("やまだ たろう", ("やまだ", "たろう")),
            ("John A. Smith", ("John", "A. Smith")),
        ],
    )
    def test_other_names_are_unchanged(self, printed: str, expected: tuple[str, str]):
        """カタカナ以外の分け方を変えていないこと。"""
        assert split_person_name(printed) == expected


class TestLogoIsNotAName:
    def test_all_caps_latin_is_not_a_person(self):
        """全部大文字の英字はロゴや社名。氏名にしないこと。"""
        got = fields(["AONE GAMES", "patricio@aonegames.com"])

        assert got["last_name"] == ""
        assert got["first_name"] == ""

    def test_title_case_latin_name_is_still_a_person(self):
        """英字の人名（`John Smith`）は従来どおり氏名として拾うこと。"""
        got = fields(["John Smith", "Sales Manager", "john@example.com"])

        assert got["last_name"] == "John"
        assert got["first_name"] == "Smith"


class TestCompanyFromEmailDomain:
    def test_company_without_a_legal_form_is_found(self):
        """法人格の語が無い社名を、メールのドメインとの一致で見つけること。"""
        assert fields(FOREIGN_CARD)["company_name"] == "AONE GAMES"

    def test_legal_form_still_wins(self):
        """法人格の語がある行を優先すること（ドメイン一致は補助）。"""
        assert fields(JAPANESE_CARD)["company_name"] == "株式会社サンプル商事"

    def test_no_match_leaves_it_empty(self):
        """一致する行が無ければ空のままにすること（推測で埋めない）。"""
        got = fields(["山田 太郎", "taro@example.co.jp", "営業部"])

        assert got["company_name"] == ""


class TestTitleKeepsItsModifier:
    @pytest.mark.parametrize(
        ("line", "keyword", "expected"),
        [
            ("エグゼクティブ・プロデューサー / Executive Producer", "プロデューサー", "エグゼクティブ・プロデューサー"),
            ("シニアエンジニア", "エンジニア", "シニアエンジニア"),
            ("部長", "部長", "部長"),
        ],
    )
    def test_modifier_is_kept(self, line: str, keyword: str, expected: str):
        assert pick_title(line, keyword) == expected

    def test_department_and_title_are_still_separated(self):
        """1行に部署と役職が並ぶ場合の分割を壊していないこと。"""
        got = fields(["営業本部 第一営業部 部長", "山田 太郎"])

        assert got["department_name"].replace(" ", "") == "営業本部第一営業部"
        assert got["title"] == "部長"


class TestLatinAddress:
    def test_address_without_japanese_hints_is_found(self):
        """都道府県が無い住所を拾うこと。"""
        got = fields(FOREIGN_CARD)

        assert got["address"] == "Santa Beatriz 111 of 1008, Providencia. Santiago de Chile"

    def test_japanese_address_is_unchanged(self):
        got = fields(JAPANESE_CARD)

        assert got["postal_code"] == "100-0001"
        assert got["address"].replace(" ", "") == "東京都千代田区千代田1-1-1"

    def test_email_and_url_are_not_taken_as_an_address(self):
        """最後の手段の判定で、メールやURLを住所にしないこと。"""
        got = fields(["John Smith", "john.smith2@example.com", "https://www.example.com/a/b/2024"])

        assert got["address"] == ""
        assert got["email"] == "john.smith2@example.com"

    def test_short_lines_are_not_taken_as_an_address(self):
        """語数の少ない行（`Room 101` など）を住所にしないこと。"""
        got = fields(["John Smith", "Room 101"])

        assert got["address"] == ""

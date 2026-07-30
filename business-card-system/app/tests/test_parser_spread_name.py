"""姓と名を離して印字した名刺（services/ocr/parser.py）。

実データ（同じ組織の名刺2枚）で、氏名とふりがなが総崩れになっていた。
姓と名を大きく離して印字する体裁で、離れたぶんが別々の行として読まれる。

    印字  とみた　　おさむ      読み  とみた
          冨田　　　修                おさむ
                                      冨田
                                      修

    修正前  姓『お』 名『さむ』 せい『と』 めい『みた』（漢字の氏名は捨てられる）
    修正後  姓『冨田』名『修』  せい『とみた』めい『おさむ』

もう1枚は名がひらがなだった（`伊藤 しの`）。ふりがなと区別する必要がある。

    修正前  姓『伊』 名『藤』 せい『し』 めい『の』
    修正後  姓『伊藤』名『しの』
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402

# 実データのOCR結果に相当する行
TOMITA = [
    "沖縄県 東京事務所",
    "企業誘致チーム",
    "とみた",
    "おさむ",
    "冨田",
    "修",
    "〒102-0093 東京都千代田区平河町2-6-3 都道府県会館10階",
]

ITO = [
    "沖縄県 東京事務所",
    "企業誘致チーム",
    "主幹",
    "伊藤",
    "しの",
    "〒102-0093 東京都千代田区平河町2-6-3 都道府県会館10階",
]

JAPANESE_CARD = [
    "株式会社サンプル商事",
    "営業本部 第一営業部",
    "部長",
    "やまだ たろう",
    "山田 太郎",
]


def fields(lines: list[str]) -> dict:
    return parse_fields(lines)["fields"]


class TestFuriganaSplitOverTwoLines:
    def test_two_hiragana_lines_are_one_reading(self):
        """離れて印字されたふりがなを、氏名と取り違えないこと。"""
        got = fields(TOMITA)

        assert got["last_name_kana"] == "とみた"
        assert got["first_name_kana"] == "おさむ"

    def test_the_kanji_name_is_used(self):
        """漢字の氏名を使うこと（捨てて仮名を氏名にしない）。"""
        got = fields(TOMITA)

        assert got["last_name"] == "冨田"
        assert got["first_name"] == "修"

    def test_a_reading_on_one_line_still_works(self):
        got = fields(JAPANESE_CARD)

        assert (got["last_name"], got["first_name"]) == ("山田", "太郎")
        assert (got["last_name_kana"], got["first_name_kana"]) == ("やまだ", "たろう")


class TestKanaGivenName:
    def test_a_short_hiragana_line_is_a_name_not_a_reading(self):
        """ふりがなは漢字より必ず長い。同じか短ければ「かなの名」。"""
        got = fields(ITO)

        assert got["last_name"] == "伊藤"
        assert got["first_name"] == "しの"
        assert got["last_name_kana"] == ""

    def test_a_longer_hiragana_line_is_still_a_reading(self):
        got = fields(["山田 太郎", "やまだ たろう"])

        assert got["first_name"] == "太郎"
        assert got["last_name_kana"] == "やまだ"


class TestNameOnTwoLines:
    @pytest.mark.parametrize(
        ("lines", "last", "first"),
        [
            (["冨田", "修"], "冨田", "修"),
            (["山田", "太郎"], "山田", "太郎"),
        ],
    )
    def test_a_split_name_is_joined(self, lines: list[str], last: str, first: str):
        got = fields(lines)

        assert (got["last_name"], got["first_name"]) == (last, first)

    def test_a_full_name_on_the_next_line_is_not_a_given_name(self):
        """4文字の行（氏名がまるごと入った行）を名にしないこと。

        実測では、ロゴを氏名として拾ったあと、次の行の `伊藤直樹` を
        名として取っていた。
        """
        got = fields(["ビー", "伊藤直樹"])

        assert got["first_name"] == ""


class TestPublicOfficeIsACompany:
    @pytest.mark.parametrize(
        "line",
        ["沖縄県 東京事務所", "山田法律事務所", "○○県庁", "市役所"],
    )
    def test_offices_are_recognised_as_a_company(self, line: str):
        assert fields([line, "山田 太郎"])["company_name"].replace(" ", "") == line.replace(" ", "")

    def test_an_office_line_is_not_a_person(self):
        """組織名を氏名にしないこと。"""
        got = fields(ITO)

        assert got["last_name"] != "沖縄県"


class TestSurnameSplitIntoSingleCharacters:
    """姓だけが空白入りで読まれ、1文字ずつに割れる場合。

    実データ（5枚目）では `伊藤 しの` の `伊藤` が `伊 藤` と読まれ、
    姓『伊』名『藤』・せい『し』めい『の』になっていた。
    """

    def test_the_surname_is_joined_and_the_kana_becomes_the_name(self):
        got = fields(["沖縄県 東京事務所", "企業誘致チーム", "主幹", "伊 藤", "し の"])

        assert got["last_name"] == "伊藤"
        assert got["first_name"] == "しの"
        assert got["last_name_kana"] == ""

    def test_a_one_character_name_with_a_reading_is_untouched(self):
        """`林 修` のような1文字＋1文字の氏名を壊さないこと。

        続く行はふりがなで、漢字より長くなるため区別できる。
        """
        got = fields(["林 修", "はやし おさむ"])

        assert (got["last_name"], got["first_name"]) == ("林", "修")
        assert (got["last_name_kana"], got["first_name_kana"]) == ("はやし", "おさむ")


class TestMixedScriptName:
    """カタカナと漢字が混じる氏名（実データ8枚目 `ジョンソン 裕子`）。"""

    @pytest.mark.parametrize(
        ("printed", "expected"),
        [
            ("ジョ ンソン 裕子", ("ジョンソン", "裕子")),
            ("ジョンソン 裕子", ("ジョンソン", "裕子")),
            ("田中 マリア", ("田中", "マリア")),
        ],
    )
    def test_the_split_follows_the_script_boundary(self, printed: str, expected: tuple[str, str]):
        from bcards.services.ocr.parser import split_person_name

        assert split_person_name(printed) == expected

    @pytest.mark.parametrize(
        ("printed", "expected"),
        [
            ("パトリシオ バスケス", ("パトリシオ", "バスケス")),
            ("山田 太郎", ("山田", "太郎")),
            ("ユン ソクン", ("ユン", "ソクン")),
        ],
    )
    def test_single_script_names_are_unchanged(self, printed: str, expected: tuple[str, str]):
        from bcards.services.ocr.parser import split_person_name

        assert split_person_name(printed) == expected


class TestEnglishOnlyTitle:
    def test_the_whole_segment_is_kept(self):
        """英語だけの役職を語だけに切り詰めないこと（実データ8枚目）。"""
        from bcards.services.ocr.parser import pick_title

        line = "Chief Business Officer & Head of Japan | APAC"

        assert pick_title(line, "Chief") == "Chief Business Officer & Head of Japan"

    def test_a_japanese_title_still_wins(self):
        from bcards.services.ocr.parser import pick_title

        line = "エグゼクティブ・プロデューサー / Executive Producer"

        assert pick_title(line, "プロデューサー") == "エグゼクティブ・プロデューサー"

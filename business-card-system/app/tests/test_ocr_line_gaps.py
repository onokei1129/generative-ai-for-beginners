"""行を組み立てるときに語の間隔を保つ（services/ocr/providers.py）。

左右2段組みの名刺は、同じ高さにある左段と右段が1行として読まれる。
項目分離（`parser.split_columns`）はその**空きの広さ**を手がかりに段を分ける。

行を組み立てるときに空白1つへ潰していたため、この手がかりが消えていた。
実テストでは、`explain-one`（`image_to_string`、間隔が残る）では直る名刺が
ラベル入力の画面（`image_to_data`）では直らない、という食い違いになった。

閾値は**名刺の幅に対する割合**（合成サンプル20枚での実測）。文字の高さとの
比では測れない——tesseract は `第` のような字の高さを2pxと返すことがある。

    語の中（`第`→`一`、`う`→`は`）           0.4 〜 1.7%
    ラベルと値（`E-mail :` → アドレス）      1.0 〜 2.3%
    `テクノロジー`→`株式会社`（切ってはいけない） 4.2%
    段の区切り                              9.5 〜 36.1%
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import split_columns  # noqa: E402
from bcards.services.ocr.providers import (  # noqa: E402
    COLUMN_GAP_RATIO,
    TesseractOcrProvider,
    group_boxes_into_lines,
)

HEIGHT = 40
CARD_WIDTH = 1050  # 名刺のおおよその画素幅


def tesseract_data(words: list[tuple[int, int, str]], line: int = 1) -> dict:
    """(左端, 幅, 文字列) から image_to_data 相当の辞書を作る。"""
    return {
        "text": [w[2] for w in words],
        "conf": ["90"] * len(words),
        "left": [w[0] for w in words],
        "width": [w[1] for w in words],
        "height": [HEIGHT] * len(words),
        "block_num": [1] * len(words),
        "par_num": [1] * len(words),
        "line_num": [line] * len(words),
    }


def to_lines(words: list[tuple[int, int, str]]) -> list[str]:
    return TesseractOcrProvider._to_lines(tesseract_data(words), CARD_WIDTH)


class TestNarrowGapsStayOneSpace:
    @pytest.mark.parametrize("gap", [0, 10, 40, 83])  # 83 = 幅の 7.9%
    def test_a_gap_below_the_threshold_is_one_space(self, gap: int):
        got = to_lines([(0, 100, "伊"), (100 + gap, 100, "藤")])

        assert got == ["伊 藤"]

    def test_touching_words_are_one_space(self):
        """語が接している場合（`東京`→`事務`）も1つの語のままにすること。"""
        got = to_lines([(0, 100, "東京"), (99, 100, "事務")])

        assert got == ["東京 事務"]


class TestWideGapsBecomeAColumnBreak:
    def test_a_wide_gap_is_marked(self):
        got = to_lines([(0, 100, "藤"), (100 + int(CARD_WIDTH * 0.16), 100, "し")])

        assert got == ["藤   し"]

    def test_the_mark_is_a_column_break_for_the_parser(self):
        """印を付けるだけでなく、項目分離が段として分けられること。"""
        line = to_lines([(0, 100, "藤"), (100 + int(CARD_WIDTH * 0.16), 100, "し")])[0]

        assert split_columns(line) == ["藤", "し"]

    def test_a_narrow_gap_is_not_a_column_break(self):
        line = to_lines([(0, 100, "伊"), (110, 100, "藤")])[0]

        assert split_columns(line) == [line]

    def test_a_foreign_card_row_splits_into_name_and_phone(self):
        """実データ（7枚目）の体裁。氏名と電話が1行に読まれる。"""
        line = to_lines([
            (0, 300, "Sangeon"),
            (310, 200, "Lee"),
            (900, 30, "T"),
            (940, 400, "+82.2.6421.7777"),
        ])[0]

        assert split_columns(line) == ["Sangeon Lee", "T +82.2.6421.7777"]


class TestTheThresholdIsMeasured:
    def test_the_ratio_matches_the_measurement(self):
        """切ってはいけない最大（4.2%）と、段の区切りの最小（9.5%）の間。"""
        assert 0.042 < COLUMN_GAP_RATIO < 0.095


class TestBoxProviderKeepsGapsToo:
    """EasyOCR / PaddleOCR の経路も同じ扱いにすること。

    boxes は (中心y, 左端x, 高さ, 文字列)。領域の幅を持たないため、
    間隔は前の語のおおよその幅から見る。
    """

    def test_a_wide_gap_is_marked(self):
        got = group_boxes_into_lines([
            (100.0, 0.0, 40.0, "藤"),
            (100.0, 400.0, 40.0, "し"),
        ], CARD_WIDTH)

        assert got == ["藤   し"]

    def test_a_narrow_gap_is_one_space(self):
        got = group_boxes_into_lines([
            (100.0, 0.0, 40.0, "伊"),
            (100.0, 40.0, 40.0, "藤"),
        ], CARD_WIDTH)

        assert got == ["伊 藤"]

    def test_separate_rows_stay_separate(self):
        got = group_boxes_into_lines([
            (100.0, 0.0, 40.0, "伊藤"),
            (300.0, 0.0, 40.0, "しの"),
        ], CARD_WIDTH)

        assert got == ["伊藤", "しの"]


class TestLowConfidenceWordsAreStillDropped:
    def test_a_word_below_the_threshold_is_removed(self):
        data = tesseract_data([(0, 100, "伊"), (110, 100, "藤")])
        data["conf"] = ["90", "5"]

        assert TesseractOcrProvider._to_lines(data, CARD_WIDTH) == ["伊"]

    def test_an_unreadable_confidence_is_treated_as_low(self):
        data = tesseract_data([(0, 100, "伊"), (110, 100, "藤")])
        data["conf"] = ["90", "-"]

        assert TesseractOcrProvider._to_lines(data, CARD_WIDTH) == ["伊"]

"""OCRエンジンの差し替え（services/ocr/providers.py）。

論点Cの比較のため、tesseract 以外のローカルOCR（PaddleOCR / EasyOCR）を
選べるようにした。どちらも依存が大きく任意インストールなので、ここでは
**ライブラリを必要としない部分**を検証する。

1. 領域を行にまとめる処理
   どちらのエンジンも「文字領域ごとの文字列」を返す。項目分離は行を単位に
   判定しているため（`TEL 03-…` のラベルと番号の関係など）、y座標の近い
   領域を同じ行に寄せてから左から右へ並べる必要がある。

2. 入っていないときの振る舞い
   分かる文言で失敗すること。黙って mock（擬似OCR）に落ちると、擬似OCRの
   数字を「PaddleOCRの精度」として報告してしまう。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr import _PROVIDERS  # noqa: E402
from bcards.services.ocr.providers import (  # noqa: E402
    EasyOcrProvider,
    PaddleOcrProvider,
    group_boxes_into_lines,
)


class TestGroupBoxesIntoLines:
    def test_boxes_on_the_same_row_become_one_line(self):
        """同じ行の領域を1行にまとめ、左から右へ並べること。"""
        boxes = [
            (100.0, 300.0, "03-1234-5678"),
            (100.0, 10.0, "TEL"),
        ]

        assert group_boxes_into_lines(boxes) == ["TEL 03-1234-5678"]

    def test_rows_are_ordered_top_to_bottom(self):
        boxes = [
            (300.0, 10.0, "山田 太郎"),
            (100.0, 10.0, "株式会社サンプル商事"),
            (200.0, 10.0, "営業部 部長"),
        ]

        assert group_boxes_into_lines(boxes) == [
            "株式会社サンプル商事",
            "営業部 部長",
            "山田 太郎",
        ]

    def test_a_small_vertical_shift_stays_on_one_line(self):
        """同じ行でも領域ごとに数ピクセルずれる。分けないこと。"""
        boxes = [
            (100.0, 10.0, "TEL"),
            (103.0, 60.0, "03-1234-5678"),
            (400.0, 10.0, "山田 太郎"),
        ]

        assert group_boxes_into_lines(boxes) == ["TEL 03-1234-5678", "山田 太郎"]

    def test_empty_input(self):
        assert group_boxes_into_lines([]) == []

    def test_blank_texts_are_dropped(self):
        assert group_boxes_into_lines([(10.0, 10.0, "   ")]) == []


class TestProviderRegistry:
    @pytest.mark.parametrize("name", ["mock", "tesseract", "paddle", "easyocr", "azure"])
    def test_the_engine_can_be_chosen_by_name(self, name: str):
        assert name in _PROVIDERS


class TestMissingLibraryIsReported:
    @pytest.mark.parametrize(
        ("provider", "module", "hint"),
        [
            (PaddleOcrProvider, "paddleocr", "requirements-paddle.txt"),
            (EasyOcrProvider, "easyocr", "requirements-easyocr.txt"),
        ],
    )
    def test_the_error_says_what_to_install(self, provider, module: str, hint: str):
        if importlib.util.find_spec(module) is not None:
            pytest.skip(f"{module} が入っている環境では確認できない")

        with pytest.raises(RuntimeError) as error:
            provider()

        assert hint in str(error.value)

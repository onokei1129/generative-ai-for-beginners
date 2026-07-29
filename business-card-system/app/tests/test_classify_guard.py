"""仕分け（poc/classify.py）の安全側の作り。

実データで「明らかな領収書が名刺として通る」事故が起きたため、その原因を固定する。
原因は3つ重なっていた。

1. OCRが動かなくても例外を握りつぶして空文字を返し、形状だけの判定に落ちていた
2. 名刺の縦横比の帯(1.37〜1.93)がA4/A5の帯(1.35〜1.48)を飲み込んでいて、
   判定順の都合で書類形状でも加点されていた
3. 文字の裏づけが無くても、形状の加点だけで「名刺」と確定していた

領収書を名刺として通すのが最も実害の大きい誤りなので、そこを重点的に見る。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poc.classify import (  # noqa: E402
    OcrUnavailable,
    classify_file,
    quick_ocr,
    score_shape,
)


class TestShapeBands:
    """縦横比の帯が重ならないこと。"""

    @pytest.mark.parametrize("ratio", [1.36, 1.40, 1.47])
    def test_document_ratio_is_not_treated_as_card(self, ratio: float):
        """A4/A5に近い比は書類。ここが名刺帯に飲まれていたのが事故の一因。

        実データのJRの領収書が比1.47で、名刺として通っていた。
        """
        score, reasons = score_shape(int(1000 * ratio), 1000)
        assert score < 0, f"比{ratio}が加点されている: {reasons}"

    @pytest.mark.parametrize("ratio", [1.55, 1.65, 1.80])
    def test_card_ratio_still_scores(self, ratio: float):
        score, _ = score_shape(int(1000 * ratio), 1000)
        assert score > 0

    def test_elongated_is_receipt_shape(self):
        score, _ = score_shape(2500, 1000)
        assert score < 0


class TestShapeAloneNeverConfirmsCard:
    """文字の裏づけが無いまま名刺と確定しないこと。"""

    def test_no_ocr_gives_unknown_not_card(self, tmp_path: Path):
        """名刺そのものの比でも、文字が無ければ「不明」に落とす。

        人が見れば済むが、領収書を名刺として通すと正解ラベル付けまで汚れる。
        """
        path = tmp_path / "card.jpg"
        Image.new("RGB", (1650, 1000), "white").save(path)

        verdict = classify_file(path, use_ocr=False)

        assert verdict.label == "unknown"
        assert verdict.label != "business_card"


class TestOcrFailureIsNotSilent:
    """OCRが動かないことを、文字が無いことと混同しないこと。"""

    def test_quick_ocr_raises_when_tesseract_missing(self, monkeypatch):
        import pytesseract

        def _boom(*args, **kwargs):
            raise pytesseract.TesseractNotFoundError()

        monkeypatch.setattr(pytesseract, "image_to_string", _boom)

        with pytest.raises(OcrUnavailable):
            quick_ocr(Image.new("RGB", (400, 120), "white"))

    def test_classify_propagates_ocr_failure(self, tmp_path: Path, monkeypatch):
        """握りつぶして「文字なし」として続行しないこと。"""
        import pytesseract

        def _boom(*args, **kwargs):
            raise pytesseract.TesseractNotFoundError()

        monkeypatch.setattr(pytesseract, "image_to_string", _boom)

        path = tmp_path / "card.jpg"
        Image.new("RGB", (1650, 1000), "white").save(path)

        with pytest.raises(OcrUnavailable):
            classify_file(path, use_ocr=True)

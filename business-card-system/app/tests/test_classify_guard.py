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

import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

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


class TestSpacedCharactersStillMatch:
    """字間を空けた印字でも語を拾えること。

    実物の領収証は「領　収　証」のように均等割付で印字されることが多く、
    OCRもそのまま空白を返す。素の文字列で照合すると "領収証" が一致せず、
    最も強い手がかりを取りこぼしていた（実データで領収証が名刺として通った）。
    """

    @pytest.mark.parametrize(
        "text",
        [
            "領収 証",
            "領 収 証",
            "領　収　書",
            "領収\n書",
        ],
    )
    def test_spaced_receipt_heading_is_detected(self, text: str):
        from poc.classify import score_text

        score, reasons = score_text(text)

        assert score < 0, f"字間ありで検出できていない: {reasons}"
        assert any("領収書を示す語" in r for r in reasons)

    def test_admission_ticket_is_not_a_card(self):
        """入場券・乗車券は名刺には無い語。実データで名刺として通った。"""
        from poc.classify import score_text

        text = (
            "国立大学法人 茨城大学五浦美術文化研究所 入場券\n"
            "入場料 400円(税込み)\n"
            "http://rokkakudo.izura.ibaraki.ac.jp/\n"
            "TEL 029-228-8425"
        )
        score, _ = score_text(text)
        assert score < 0

    def test_real_card_still_scores_positive(self):
        """語を足したことで名刺側が巻き添えになっていないこと。"""
        from poc.classify import score_text

        text = (
            "株式会社サンプル商事\n営業本部 第一営業部 部長\n山田 太郎\n"
            "〒100-0001 東京都千代田区\nTEL 03-1234-5678\ntaro@example.co.jp"
        )
        score, _ = score_text(text)
        assert score > 2.0


class TestHandwrittenReceiptHeading:
    """手書きの領収証。見出しが1文字欠けても拾えること。

    実データで、地紋（薄い模様）の上に字間を空けて印字された「領　収　証」の
    「領」が読めず、OCRが `tH 収 証` を返していた。見出しは最も強い手がかりなので、
    1文字落ちただけで取りこぼすと、宛名・金額しか無い領収証が名刺として通る。
    """

    # 実データのOCR結果をそのまま使う（作文すると、実際の壊れ方から離れてしまう）
    ACTUAL_OCR = (
        "tH 収 証     小野木 圭一 様 no. szze\n"
        "¥ 9, 900-\n"
        "但          光トポグラフィー検査費として\n"
        "2025 年8月4日 上記正に領収いたしました\n"
        "ma     内 訳               品川メンタルクリニック 品川本院\n"
        "税抜金額                  〒108-0975 東京都港区港南2-16-3\n"
        "印 紙       消費税額等 ( %)"
    )

    def test_broken_heading_is_still_detected(self):
        from poc.classify import score_text

        score, reasons = score_text(self.ACTUAL_OCR)

        assert score < -2.0, f"見出しが欠けた領収証を取りこぼした: {reasons}"

    def test_broken_heading_alone_is_enough(self):
        """欠けた見出しだけで領収書と分かること。

        手書きの帳償は、印字と手書きが重なる行から先に壊れる。定型句
        （「上記正に領収」「内訳」など）が全部落ちて、宛名・金額・発行元しか
        残らないことがある。そこに残った見出しを拾えないと、
        発行元の社名・住所・電話が名刺の手がかりとして働いてしまう。
        """
        from poc.classify import score_text

        text = (
            "tH 収 証\n"
            "小野木 圭一\n"
            "品川メンタルクリニック 品川本院\n"
            "〒108-0075 東京都港区港南2-16-3 シントミビル5F\n"
            "TEL 0120-772-248"
        )
        score, reasons = score_text(text)

        assert score <= -2.0, f"欠けた見出しを拾えていない: {reasons}"

    def test_heading_lost_entirely_falls_back_to_unknown(self):
        """見出しが丸ごと消えたら、名刺と断定せず人に回すこと。"""
        from poc.classify import score_text

        text = (
            "小野木 圭一 様 no. szze\n¥ 9, 900-\n"
            "但          光トポグラフィー検査費として\n2025 年8月4日\n"
            "品川メンタルクリニック 品川本院\n"
            "〒108-0075 東京都港区港南2-16-3\nTEL 0120-772-248"
        )
        score, _ = score_text(text)

        assert score < 2.0, "名刺として確定してはいけない"

    def test_real_card_is_not_dragged_down(self):
        """語を足したことで名刺側が巻き添えになっていないこと。"""
        from poc.classify import score_text

        text = (
            "株式会社サンプル商事\n営業本部 第一営業部 部長\n山田 太郎\n"
            "〒100-0001 東京都千代田区\nTEL 03-1234-5678\nFAX 03-1234-5679\n"
            "taro@example.co.jp\nhttps://www.example.co.jp"
        )
        score, _ = score_text(text)

        assert score > 2.0


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract が無い環境ではOCRの実測を行わない")
class TestRotatedReceipt:
    """90度回った領収書も領収書と分かること。

    回った画像はほとんど文字が読めず、最も強い手がかりである「領収証」を
    取りこぼす。文字の裏づけが無いまま名刺の形をしていると人手に回ってしまい、
    そこで名刺として拾われれば、また正解ラベル付けが汚れる。
    """

    def _receipt(self, path: Path) -> None:
        from bcards import fonts

        image = Image.new("RGB", (1400, 950), "white")
        draw = ImageDraw.Draw(image)
        draw.text((450, 80), "領 収 証", font=fonts.load(70), fill="black")
        draw.text((120, 300), "金額 12,000円", font=fonts.load(44), fill="black")
        draw.text((120, 400), "上記正に領収いたしました", font=fonts.load(44), fill="black")
        draw.text((120, 500), "株式会社サンプル交通", font=fonts.load(44), fill="black")
        image.rotate(-90, expand=True).save(path)

    def test_rotated_receipt_is_still_a_receipt(self, tmp_path: Path):
        path = tmp_path / "receipt.jpg"
        self._receipt(path)

        verdict = classify_file(path, use_ocr=True)

        assert verdict.label == "receipt", f"回転した領収書を取りこぼした: {verdict.reasons}"

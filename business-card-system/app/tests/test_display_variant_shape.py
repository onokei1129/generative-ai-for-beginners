"""取り込みの「表示用」画像も、縦型の名刺を横倒しにしない。

取り込み（services/images.process_file）は1枚から2つの画像を作る。

    ocr_image  OCRへ渡す（切り出し＋90度単位の向き＋傾き補正まで）
    image      画面に出す／保存する（さらに明るさ・影の補正）

この「表示用」に、**縦長なら90度回して横長にする**という規則が入っていた
（`orient_landscape`）。名刺の形だけを見て回すため、正しい向きの縦型名刺
——日本語の縦書き名刺——が横倒しになる。

同じ規則をラベル入力の画面でも通しており、実テスト25枚目（縦型・縦書きの
名刺）が横に倒れて出た。手で入力するのに読めない。

90度単位の回転は `orientation.upright` が**字の形から**判定して直している。
形だけの判定を重ねる必要はなく、重ねると縦書き名刺を巻き添えにする。
これはOCR側で不採用にした判定と同じもの（ocr-poc-report.md 4.2）。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.images import process_file  # noqa: E402


def a_tall_card() -> bytes:
    """縦長の名刺の画像（JPEG）。輪郭の切り出しに掛からないよう余白なし。"""
    image = Image.new("RGB", (620, 880), "white")
    draw = ImageDraw.Draw(image)
    for row in range(8):
        draw.text((40, 60 + row * 90), "sample text line", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class TestTheDisplayVariantKeepsItsShape:
    def test_a_tall_card_stays_tall(self):
        cards = process_file(a_tall_card(), "tall.jpg", correct=True, page_limit=1)

        assert cards, "画像を取り出せていない"
        shown = cards[0].image
        assert shown.height > shown.width, "縦型の名刺を横倒しにしている"

    def test_the_two_variants_have_the_same_shape(self):
        """表示用とOCR用で向きが食い違うと、画像と欄を見比べられない。"""
        cards = process_file(a_tall_card(), "tall.jpg", correct=True, page_limit=1)

        card = cards[0]
        assert (card.image.width > card.image.height) == (
            card.ocr_image.width > card.ocr_image.height
        ), "表示用とOCR用で向きが違う"


class TestTheShapeRuleIsGone:
    def test_the_intake_does_not_force_landscape(self):
        source = (APP / "src" / "bcards" / "services" / "images.py").read_text(encoding="utf-8")
        body = source[source.index("def _finish_card") : source.index("return ProcessedCard")]

        assert "orient_landscape(" not in body, "形だけで回す判定が残っている"

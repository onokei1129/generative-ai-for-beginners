"""画面に出す画像も、向きを直したものにする（poc/one_card.py）。

横型の名刺を読み取り機に横向きに置くと、画像は90度回った状態で入ってくる。
取り込みの仕組みはこれを直している（`services/orientation.upright`。
tesseract の向き検出で90度単位の回転を戻す）。実測でも

    取り込んだ向き 690x1110  →  補正後 1110x690

と直っている。**ところが画面に出す画像は補正を通していなかった** ——
`write_image` が `load_pages` だけを呼んでいたため、利用者には横倒しのまま
見えていた。手で入力するときに読みづらく、画像と欄を見比べられない。

OCRが見た画像と同じものを出すほうが、見比べるという作業に合っている。
"""

from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from poc.one_card import write_image  # noqa: E402

HAS_TESSERACT = shutil.which("tesseract") is not None


def a_font(size: int, japanese: bool = False) -> ImageFont.FreeTypeFont:
    """字の形が読める書体。無い環境ではその試験を飛ばす。

    PIL の既定の書体は約11ピクセルの点字で、**向き検出（OSD）が字の形を
    読めない**（実測 `(0, 0.0)`＝判定不能）。300dpiで取り込んだ実物の名刺は
    40ピクセル前後あるので、試験の画像もそれに合わせる。
    """
    candidates = [
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/ipafont-gothic/ipag.ttf",
    ]
    if not japanese:
        candidates.insert(0, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    pytest.skip("字の形が読める書体が無い環境です")


def a_card_with_text() -> Image.Image:
    """向き検出が効くだけの文字を持つ横型の画像。"""
    image = Image.new("RGB", (1050, 640), "white")
    draw = ImageDraw.Draw(image)
    font = a_font(38)
    for row, text in enumerate([
        "Sample Trading Co., Ltd.",
        "Sales Division",
        "Taro Yamada",
        "Tokyo Chiyoda 1-1-1",
        "TEL 03-1234-5678",
        "taro.yamada@example.co.jp",
    ]):
        draw.text((60, 50 + row * 90), text, font=font, fill="black")
    return image


class TestTheShownImageIsUpright:
    @pytest.mark.skipif(not HAS_TESSERACT, reason="向き検出（OSD）に tesseract が要ります")
    def test_a_sideways_card_is_turned_back(self, tmp_path: Path):
        source = tmp_path / "sideways.png"
        a_card_with_text().rotate(90, expand=True).save(source)
        assert Image.open(source).height > Image.open(source).width

        out = tmp_path / "page.jpg"
        write_image(source, out)

        shown = Image.open(out)
        assert shown.width > shown.height, "横倒しのまま出している"

    def test_an_upright_card_is_left_alone(self, tmp_path: Path):
        source = tmp_path / "upright.png"
        a_card_with_text().save(source)

        out = tmp_path / "page.jpg"
        write_image(source, out)

        shown = Image.open(out)
        assert shown.width > shown.height


def a_vertical_japanese_card() -> Image.Image:
    """縦書きの縦型名刺。**縦長のままが正しい向き。**"""
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    font = a_font(56, japanese=True)
    columns = [
        ("株式会社サンプルエンターテインメント", 1100),
        ("コンテンツ事業本部", 980),
        ("山田 太郎", 820),
    ]
    for text, x in columns:  # 縦書きは右の列から
        y = 160
        for letter in text:
            draw.text((x, y), letter, font=font, fill="black")
            y += font.size + 8
    draw.text((90, 1500), "東京都港区芝5-37-8", font=font, fill="black")
    draw.text((90, 1590), "TEL 03-1234-5678", font=font, fill="black")
    return image


class TestAVerticalCardStaysVertical:
    """縦型の名刺を横倒しにしない。

    はじめは向きの検出のあとに `orient_landscape`（縦長なら90度回して横長に
    する）も通していた。名刺の形だけを見て回すため、**正しい向きの縦型名刺が
    横倒しになる**。実測:

        縦書きの縦型名刺 1240x1754
          → 向きの検出は 0度（正しい。回す必要なし）
          → orient_landscape が -90度回す
          → 画面には 1754x1240 の横倒しで出る

    実テスト 25枚目（縦型・縦書き）で、画面の名刺が横に倒れて出た。手で
    入力するのに読めない。日本語の縦型名刺は縦長のままが正しい。
    """

    def test_it_is_not_turned_sideways(self, tmp_path: Path):
        source = tmp_path / "vertical.png"
        a_vertical_japanese_card().save(source)

        out = tmp_path / "page.jpg"
        write_image(source, out)

        shown = Image.open(out)
        assert shown.height > shown.width, "縦型の名刺を横倒しにしている"

    def test_the_shape_rule_is_gone(self):
        source = (APP / "poc" / "one_card.py").read_text(encoding="utf-8")
        body = source[source.index("def write_image") : source.index("def emit")]
        call = body[body.index("pages = load_pages") :]

        assert "orient_landscape(" not in call, "形だけで回す判定が残っている"


class TestTheShownImageStaysCheap:
    """表示のために重い補正を通さない。

    はじめは取り込みの補正を丸ごと通した。実測で

        load_pages のみ    0.2秒 / 最大RSS  94MB
        process_file 全部  6.0秒 / 最大RSS 249MB

    となり、これがOCRの子プロセスと**同時に**動く。実テストでサーバーが
    落ちた。表示に要るのは向きだけで、輪郭の切り出し・傾き補正・明るさ補正は
    要らない。
    """

    def test_the_heavy_pipeline_is_not_used(self):
        source = (APP / "poc" / "one_card.py").read_text(encoding="utf-8")
        body = source[source.index("def write_image") : source.index("def emit")]

        # 呼び出しの形で見る。説明の中に名前が出るのは構わない。
        assert "process_file(" not in body, "表示のために重い補正を通している"

    def test_only_the_orientation_is_fixed(self):
        source = (APP / "poc" / "one_card.py").read_text(encoding="utf-8")
        body = source[source.index("def write_image") : source.index("def emit")]

        assert "detect_rotation" in body, "向きを直していない"
        for heavy in ("deskew", "enhance", "detect_card_quads"):
            assert heavy not in body, f"{heavy} は表示には要らない"


class TestItStillWorksWhenNothingCanBeRead:
    def test_a_blank_page_is_still_shown(self, tmp_path: Path):
        """補正できなくても画像は出す。出ないと手入力の手がかりが消える。"""
        source = tmp_path / "blank.png"
        Image.new("RGB", (800, 500), "white").save(source)

        out = tmp_path / "page.jpg"
        write_image(source, out)

        assert out.exists() and out.stat().st_size > 0

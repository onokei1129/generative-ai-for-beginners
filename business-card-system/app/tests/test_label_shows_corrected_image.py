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
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from poc.one_card import write_image  # noqa: E402


def a_card_with_text() -> Image.Image:
    """向き検出が効くだけの文字を持つ横型の画像。"""
    image = Image.new("RGB", (1050, 640), "white")
    draw = ImageDraw.Draw(image)
    for row, text in enumerate([
        "Sample Trading Co., Ltd.",
        "Sales Division",
        "Taro Yamada",
        "Tokyo Chiyoda 1-1-1",
        "TEL 03-1234-5678",
        "taro.yamada@example.co.jp",
    ]):
        draw.text((60, 60 + row * 80), text, fill="black")
    return image


class TestTheShownImageIsUpright:
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

        assert "upright" in body
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

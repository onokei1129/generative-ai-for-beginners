"""縦長の名刺が画面に収まる（poc/label.py）。

実テストの22枚目（縦型）で、既定の表示だと画像が大きすぎて全体が見えず、
毎回スクロールしないと下半分を読めなかった。

画像は横幅いっぱい（`width: 100%`）に広げるだけで、高さに上限が無かった。
横長の名刺なら収まるが、縦長は縦にはみ出す。

高さの上限を入れ、縦横の比は保つ（`object-fit: contain`）。細部を見たい
ときは、これまでどおり画像を押せば拡大する。

ブラウザを動かして測ることはここではできないので、見るのは指定そのもの。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402


def image_rule() -> str:
    """拡大していないときの画像の指定を取り出す。"""
    match = re.search(r"\.imgwrap img \{[^}]*\}", label.PAGE)
    assert match, "画像の指定が見つからない"
    return match.group(0)


class TestTheImageFitsTheScreen:
    def test_the_height_is_capped_to_the_window(self):
        rule = image_rule()

        assert "max-height" in rule, "高さの上限が無い"
        assert "vh" in rule, "上限が画面の高さに追随していない"

    def test_the_shape_is_kept(self):
        """上限に当たったとき、縦横の比が崩れないこと。"""
        assert "object-fit: contain" in image_rule()

    def test_pressing_the_image_still_enlarges_it(self):
        """収めるようにしても、細部を見る手段は残す。"""
        assert ".imgwrap img.zoom" in label.PAGE
        assert "cursor: zoom-in" in image_rule()

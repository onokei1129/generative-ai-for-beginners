"""向きの自動判定が外した1枚を、利用者がその場で回せる。

向きの検出（tesseract の OSD）は外すことがある。実テストでは、同じ修正で
22枚目は正立したのに25枚目は外したまま、という状態になった。判定は名刺の
汚れ・地色・縦書きで揺れる。

**外した画像は手入力にも使えない。** 画像と欄を見比べる作業なので、名刺が
横倒しや逆さのままだと、その1枚は飛ばすしかなくなる。押すごとに時計回りに
90度回せるようにして、自動の判定に足す。

回す処理も子プロセス側に置く。親（サーバー）で画像を触らない方針は、
C のライブラリが落ちてもサーバーが生き残るためのもので、崩さない。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from poc.label import build_app  # noqa: E402
from poc.one_card import write_image  # noqa: E402


def a_card(path: Path) -> None:
    Image.new("RGB", (900, 560), "white").save(path)


class TestTheChildTurnsTheImage:
    def test_ninety_degrees_swaps_the_sides(self, tmp_path: Path):
        source = tmp_path / "card.png"
        a_card(source)

        out = tmp_path / "turned.jpg"
        write_image(source, out, 90)

        turned = Image.open(out)
        assert (turned.width, turned.height) == (560, 900)

    def test_one_eighty_keeps_the_shape(self, tmp_path: Path):
        source = tmp_path / "card.png"
        a_card(source)

        out = tmp_path / "turned.jpg"
        write_image(source, out, 180)

        turned = Image.open(out)
        assert (turned.width, turned.height) == (900, 560)

    def test_no_turn_is_the_same_as_before(self, tmp_path: Path):
        source = tmp_path / "card.png"
        a_card(source)

        plain = tmp_path / "plain.jpg"
        zero = tmp_path / "zero.jpg"
        write_image(source, plain)
        write_image(source, zero, 0)

        assert plain.read_bytes() == zero.read_bytes()


class TestTheScreenAsksForATurn:
    def test_the_endpoint_takes_a_turn(self, tmp_path: Path):
        a_card(tmp_path / "card.png")
        client = TestClient(build_app(tmp_path, False))

        answer = client.get("/api/image/card.png", params={"turn": 90})

        assert answer.status_code == 200
        assert answer.headers["content-type"] == "image/jpeg"
        turned = Image.open(io.BytesIO(answer.content))
        assert (turned.width, turned.height) == (560, 900)

    def test_the_button_is_on_the_page(self, tmp_path: Path):
        client = TestClient(build_app(tmp_path, False))

        page = client.get("/").text

        assert "画像を90度回す" in page
        assert "function turnImage()" in page

    def test_the_turn_is_remembered_per_card(self):
        """名刺ごとに覚える。前へ戻ったときに元に戻ってしまうと使えない。"""
        source = (APP / "poc" / "label.py").read_text(encoding="utf-8")

        assert "state.turns[file.name]" in source, "名刺ごとに覚えていない"
        assert "img.src = imageUrl(file.name)" in source, "表示のときに反映していない"

"""名刺を切り替えたとき、前の名刺の画像を残さない（poc/label.py）。

実テストの21枚目で、こうなっていた。

    ファイル名   (会社名)_高岡 徹.pdf     ← 新しい名刺
    欄           高岡 徹 / 税理士事務所   ← 新しい名刺
    画像         Smilegate / Yeo Seunghwan ← **前の名刺のまま**

2つが重なっている。

1. 画像の要求は `img.src` を差し替えるだけで、**新しい画像が届くまで前の
   画像が表示されたまま**になる。欄は先に返るので、その間ずれて見える。

2. 画像の変換とOCRが同じ子プロセスを取り合っていた。OCR（2つの読み取り機）
   と次の2枚の先読みが先に錠を取っていると、画像はその後ろで待つ。実テスト
   では18秒かかった。

見た目の違和感で済む話ではない。**別の名刺を見ながら入力できてしまう**。

1は画像を先に消して待ちを出す。2は画像の変換を別の子プロセスに分ける
（PDFの1ページ描画は読み取り機のモデルを使わないので、分けても重くない）。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_worker():
    label.stop_worker()
    yield
    label.stop_worker()


class TestThePreviousImageIsCleared:
    """画面側。届くまでのあいだ、前の名刺の画像を出しっぱなしにしない。"""

    def test_the_source_is_removed_before_the_new_one_is_asked_for(self):
        # 名刺を切り替えるのは `show`。その中での順番を見る。
        body = label.PAGE[label.PAGE.index("async function show(i)") :]
        # 頼む場所は `img.src` への代入で見る。URLの組み立て方（回した角度を
        # 足すなど）は変わりうるが、**代入の順番**がこの試験の内容なので。
        clears = body.find("removeAttribute('src')")
        asks = body.find("img.src =")

        assert clears >= 0, "前の画像を消していない"
        assert asks >= 0, "新しい画像を頼んでいない"
        assert clears < asks, "消す前に新しい画像を頼んでいる"

    def test_there_is_something_to_show_while_waiting(self):
        assert "imgwait" in label.PAGE


class TestTheImageDoesNotWaitBehindOcr:
    """サーバー側。OCRの最中でも画像は返る。"""

    @pytest.fixture
    def cards(self, tmp_path: Path) -> Path:
        Image.new("RGB", (1050, 640), "white").save(tmp_path / "card.pdf")
        return tmp_path

    def test_the_image_answers_while_an_ocr_holds_its_turn(self, cards: Path):
        """OCRの順番待ちを掴んだまま画像を頼み、返ってくることを確かめる。

        頼みごとは1件ずつ順に渡す（同時に2枚を抱えないため）。分けていないと
        画像もその列に並び、OCRが終わるまで返らない（実テストで18秒）。
        """
        client = TestClient(label.build_app(cards, prefill=True))

        with label.lane_lock("ocr"):
            started = time.monotonic()
            response = client.get("/api/image/card.pdf")
            took = time.monotonic() - started

        assert response.status_code in (200, 415)
        assert took < 15, f"画像がOCRの後ろで待っている（{took:.1f}秒）"

    def test_the_two_children_are_separate(self, cards: Path):
        """画像とOCRは別の子プロセスに頼む。"""
        label.run_in_child(["echo", "あ"])
        ocr_pid = label.worker_pid()

        assert ocr_pid is not None
        assert label.worker_pid(lane="image") != ocr_pid

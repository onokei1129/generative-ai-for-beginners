"""この1枚の読み取りを書き出す（poc/label.py）。

実テストで、画面の写真から不具合を再現しようとして**何度も食い違った**。
8枚目・18枚目では、写真から書き写したOCR文字では正しい結果が出るのに、
実際の画面では違う値が出ていた。

OCRが読んだ文字は目で書き写すには長く、`テ`と`了`、`一`と`ー`、`9`と`９`、
`-`(ASCII) と `‐`(U+2010) のような1文字の違いがそのまま結果を変える。
**写真では区別が付かない。**

そこで、その1枚の読み取りをファイルに書き出せるようにする。利用者は
そのファイルを送るだけでよく、こちらは同じ文字で再現できる。

`poc/doctor.py` が以前から「この1枚を調べる」に掛けた結果を共有してくれと
案内していたが、その道具は作られていなかった。
"""

from __future__ import annotations

import sys
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


@pytest.fixture
def cards(tmp_path: Path) -> Path:
    Image.new("RGB", (1050, 640), "white").save(tmp_path / "名刺.png")
    return tmp_path


@pytest.fixture
def client(cards: Path) -> TestClient:
    return TestClient(label.build_app(cards, prefill=True))


class TestItWritesAFile:
    def test_the_file_is_created(self, client: TestClient, cards: Path):
        res = client.post("/api/inspect/名刺.png")

        assert res.status_code == 200
        assert (cards / "読み取り-名刺.png.txt").exists()

    def test_the_path_is_returned_so_it_can_be_shown(self, client: TestClient):
        body = client.post("/api/inspect/名刺.png").json()

        assert "読み取り-名刺.png.txt" in body["path"]


class TestWhatTheFileHolds:
    def text(self, client: TestClient, cards: Path) -> str:
        client.post("/api/inspect/名刺.png")
        return (cards / "読み取り-名刺.png.txt").read_text(encoding="utf-8")

    def test_it_names_the_card(self, client: TestClient, cards: Path):
        assert "名刺.png" in self.text(client, cards)

    def test_it_records_the_version(self, client: TestClient, cards: Path):
        """どの版で出た結果かが分からないと、直っているのか判断できない。"""
        assert "版" in self.text(client, cards)

    def test_it_holds_the_text_the_ocr_read(self, client: TestClient, cards: Path):
        assert "OCRが読んだ文字" in self.text(client, cards)

    def test_it_holds_every_field(self, client: TestClient, cards: Path):
        from poc.samples import FIELD_KEYS

        text = self.text(client, cards)

        for key in FIELD_KEYS:
            assert label.LABELS[key] in text

    def test_it_is_written_as_utf8(self, client: TestClient, cards: Path):
        """cp932 で書くと `ソ` などが壊れる。ファイルは UTF-8 で書く。"""
        path = cards / "読み取り-名刺.png.txt"
        client.post("/api/inspect/名刺.png")

        path.read_text(encoding="utf-8")  # 置き換えなし。壊れていれば例外


class TestFailuresAreExplained:
    def test_a_missing_card_is_reported(self, client: TestClient):
        res = client.post("/api/inspect/ない.png")

        assert res.status_code == 404

    def test_a_path_outside_the_folder_is_refused(self, client: TestClient):
        res = client.post("/api/inspect/..%2F..%2Fetc%2Fpasswd")

        assert res.status_code == 404

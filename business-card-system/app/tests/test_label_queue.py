"""ラベル入力の待ち行列と先読み（poc/label.py）。

実テストで2件の報告があり、どちらも作りの問題だった。

1. 同じ処理が2度走る
   先読みが終わる前に利用者がその名刺へ進むと、同じ画像を2回OCRしていた
   （実測：3枚に対してOCRが4回）。CPUが二重に要るだけでなく、待ちも伸びる。

2. 仕分けが取りこぼした領収書が、毎回いちばん最初に出てくる
   仕分けは名刺と判定したファイルを**コピー**するため、やり直しても
   前回入ったものが残る。入力する人が自分で外せる必要がある。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poc.label import build_app  # noqa: E402


@pytest.fixture
def cards(tmp_path: Path) -> Path:
    for i in range(1, 4):
        Image.new("RGB", (1650, 1000), "white").save(tmp_path / f"card{i:02d}.jpg")
    return tmp_path


def _counting_ocr(monkeypatch, seconds: float = 0.0):
    """OCRの呼ばれた回数を数える。seconds は処理に時間がかかる状況の再現。"""
    import bcards.services.ocr as ocr_service

    calls: list[str] = []
    lock = threading.Lock()

    def fake(image):
        with lock:
            calls.append("x")
        if seconds:
            time.sleep(seconds)
        return None, {"fields": {"company_name": "株式会社サンプル商事"}, "confidence": {}}

    monkeypatch.setattr(ocr_service, "recognize_card", fake)
    return calls


class TestNoDuplicateWork:
    def test_same_image_is_not_processed_twice(self, cards: Path, monkeypatch):
        """先読み中の画像へ進んでも、OCRは1回で済むこと。"""
        calls = _counting_ocr(monkeypatch, seconds=0.6)
        client = TestClient(build_app(cards, prefill=True))

        client.get("/api/label/card01.jpg")  # ここで card02/03 の先読みが始まる
        time.sleep(0.1)  # 先読みが終わる前に次へ進む
        client.get("/api/label/card02.jpg")
        time.sleep(1.5)  # 先読みが終わるのを待つ

        assert len(calls) == 3, f"3枚に対して{len(calls)}回OCRしている"

    def test_waiting_request_gets_the_result(self, cards: Path, monkeypatch):
        """待たされた側も結果を受け取れること（待って空になっては困る）。"""
        _counting_ocr(monkeypatch, seconds=0.6)
        client = TestClient(build_app(cards, prefill=True))

        client.get("/api/label/card01.jpg")
        time.sleep(0.1)
        body = client.get("/api/label/card02.jpg").json()

        assert body["kind"] == "draft"
        assert body["values"]["company_name"] == "株式会社サンプル商事"

    def test_failure_releases_the_waiters(self, cards: Path, monkeypatch):
        """失敗しても待ち手を解放すること。ここを漏らすと画面が固まる。"""
        import bcards.services.ocr as ocr_service

        monkeypatch.setattr(
            ocr_service, "recognize_card", lambda image: (_ for _ in ()).throw(RuntimeError("失敗"))
        )
        client = TestClient(build_app(cards, prefill=True))

        started = time.perf_counter()
        first = client.get("/api/label/card01.jpg").json()
        second = client.get("/api/label/card01.jpg").json()

        assert first["kind"] == "error"
        assert second["kind"] == "error"
        assert time.perf_counter() - started < 10, "待ち手が解放されていない"


class TestNotACard:
    def _receipt(self, directory: Path) -> Path:
        path = directory / "receipt.jpg"
        Image.new("RGB", (1400, 800), "white").save(path)
        return path

    def test_removed_from_the_list(self, cards: Path, monkeypatch):
        _counting_ocr(monkeypatch)
        self._receipt(cards)
        client = TestClient(build_app(cards, prefill=False))

        assert "receipt.jpg" in [f["name"] for f in client.get("/api/files").json()["files"]]

        assert client.post("/api/not-a-card/receipt.jpg").status_code == 200

        assert "receipt.jpg" not in [f["name"] for f in client.get("/api/files").json()["files"]]

    def test_file_is_moved_not_deleted(self, cards: Path, monkeypatch):
        """消さずに残すこと。仕分けの精度を測り直すときの材料になる。"""
        _counting_ocr(monkeypatch)
        self._receipt(cards)
        client = TestClient(build_app(cards, prefill=False))

        client.post("/api/not-a-card/receipt.jpg")

        assert (cards / "not-cards" / "receipt.jpg").is_file()
        assert not (cards / "receipt.jpg").exists()

    def test_sidecar_files_move_together(self, cards: Path, monkeypatch):
        """ラベルやOCRテキストを置き去りにしないこと。

        置き去りにすると、進み具合の集計が実体の無いラベルを数えてしまう。
        """
        _counting_ocr(monkeypatch)
        self._receipt(cards)
        (cards / "receipt.json").write_text("{}", encoding="utf-8")
        (cards / "receipt.txt").write_text("OCR", encoding="utf-8")
        client = TestClient(build_app(cards, prefill=False))

        client.post("/api/not-a-card/receipt.jpg")

        assert sorted(p.name for p in (cards / "not-cards").iterdir()) == [
            "receipt.jpg",
            "receipt.json",
            "receipt.txt",
        ]

    def test_button_sits_next_to_the_image(self, cards: Path, monkeypatch):
        """「名刺ではない」を入力欄より前に置くこと。

        入力欄は14項目あり、その下に置くとスクロールしないと見えない。
        実際に「ボタンが無い」という報告になった。判断は画像を見た時点で
        できるので、画像のすぐ下に置く。
        """
        _counting_ocr(monkeypatch)
        html = TestClient(build_app(cards, prefill=False)).get("/").text

        image_panel = html.index('class="panel imgwrap"')
        button = html.index('id="notcard"')
        form = html.index('id="form"')

        assert image_panel < button < form

    def test_version_is_shown(self, cards: Path, monkeypatch):
        """画面に版を出すこと。更新できているかをその場で確かめるため。"""
        _counting_ocr(monkeypatch)
        client = TestClient(build_app(cards, prefill=False))

        assert client.get("/api/files").json()["version"]

    def test_missing_file_is_reported(self, cards: Path, monkeypatch):
        _counting_ocr(monkeypatch)
        client = TestClient(build_app(cards, prefill=False))

        assert client.post("/api/not-a-card/nope.jpg").status_code == 404

    def test_moved_folder_is_not_relisted(self, cards: Path, monkeypatch):
        """not-cards の中身が一覧に戻ってこないこと。"""
        _counting_ocr(monkeypatch)
        self._receipt(cards)
        client = TestClient(build_app(cards, prefill=False))
        client.post("/api/not-a-card/receipt.jpg")

        names = [f["name"] for f in client.get("/api/files").json()["files"]]

        assert names == ["card01.jpg", "card02.jpg", "card03.jpg"]

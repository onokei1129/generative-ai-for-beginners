"""保存済みの名刺でも、OCRが読んだ文字を見られること（実テスト 8・9枚目）。

保存済みの札を開くと、OCRの欄に

    （OCRの結果はありません）

と出ていた。これは**誤った説明**で、実際には結果が無いのではなく、保存済み
なのでOCRを実行していないだけ。

見直しているとき（保存した値が誤っていると気づいたとき）こそ、読んだ文字が
要る。実テスト 9枚目では、保存済みの住所が `〒4らの - の９の` になっており、
何をどう読み違えたのかを確かめる手立てが画面に無かった。

保存済みの札すべてでOCRを走らせると、戻るたびに数秒待たされる。開いたときに
だけ取りに行く。
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


@pytest.fixture
def cards(tmp_path: Path) -> Path:
    Image.new("RGB", (1050, 640), "white").save(tmp_path / "card0.png")
    return tmp_path


@pytest.fixture(autouse=True)
def log_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "ラベル入力ログ.txt"
    monkeypatch.setattr(label, "LOG_PATH", path)
    return path


def client(cards: Path) -> TestClient:
    return TestClient(label.build_app(cards, prefill=True), raise_server_exceptions=False)


def save(api: TestClient) -> None:
    api.post("/api/label/card0.png", json={"last_name": "山田", "first_name": "太郎"})


class TestASavedCardSaysWhyThereIsNoText:
    def test_a_saved_card_still_reports_saved(self, cards: Path):
        api = client(cards)
        save(api)

        got = api.get("/api/label/card0.png").json()

        assert got["kind"] == "saved"
        assert got["values"]["last_name"] == "山田"

    def test_a_saved_card_does_not_claim_the_ocr_found_nothing(self, cards: Path):
        """走らせていないことと、読めなかったことは違う。"""
        api = client(cards)
        save(api)

        got = api.get("/api/label/card0.png").json()

        assert got["ocr_text"] == ""
        assert got["ocr_text_available"] is True


class TestTheTextCanBeFetchedOnDemand:
    def test_the_text_is_returned_for_a_saved_card(self, cards: Path):
        api = client(cards)
        save(api)

        got = api.get("/api/ocr-text/card0.png").json()

        assert got["ocr_text"]

    def test_a_failure_is_explained_instead_of_raising(
        self, cards: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(label, "run_in_child", _always_fails)
        api = client(cards)

        response = api.get("/api/ocr-text/card0.png")

        assert response.status_code == 200
        assert "わざと失敗" in response.json()["ocr_text"]

    def test_an_unknown_card_does_not_raise(self, cards: Path):
        response = client(cards).get("/api/ocr-text/ない.png")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")


class TestTheScreenFetchesItWhenOpened:
    SOURCE = (APP / "poc" / "label.py").read_text(encoding="utf-8")

    def test_the_old_wording_is_gone(self):
        assert "（OCRの結果はありません）" not in self.SOURCE

    def test_opening_the_panel_fetches_the_text(self):
        assert "ocrbox" in self.SOURCE
        assert "/api/ocr-text/" in self.SOURCE
        assert "addEventListener('toggle'" in self.SOURCE

    def test_a_draft_does_not_need_a_second_request(self):
        """下書きのときは既に本文が来ている。取り直さないこと。"""
        assert "state.ocrLoaded" in self.SOURCE


def _always_fails(args: list[str]) -> dict:
    raise RuntimeError("わざと失敗 ソ")

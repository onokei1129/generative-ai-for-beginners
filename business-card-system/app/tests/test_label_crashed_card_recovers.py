"""落ちた名刺の印が残り続けない／画像は出す（poc/label.py）。

実テストで、3枚目にこの表示が出たまま消えなくなった。

    前回この名刺の処理中にサーバーが落ちました。原因が分かるまで自動では
    読み取りません。

しかも画像まで出ないため、**サーバーが落ちているように見えていた**。
実際にはサーバーは応えている（欄も一覧も出ている）。

原因は2つ。

## 1. 印を消す仕組みを、見張り役を入れたときに壊した

印が消えるのは「正常に終了した」記録が書かれたとき。それは終了時の後始末
（atexit）で書いていた。見張り役は止めるときに `terminate()` を使うが、
これは **atexit を走らせずに終わる**ため、印が書かれない。

見張り役は生きているので、**見張り役の側で書く**。子に頼らないほうが確実。

## 2. 画像まで止めていた

落ちた工程がOCRか画像かは記録からは分からないので、両方止めていた。
しかし画像が出ないと**手で入力もできない**。画像の変換は別の子プロセスに
分かれており、落ちてもサーバーは生き残る。止める理由がない。
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
def cards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # 実テストの3枚目は PDF。PDF は絵に変換してから出すので、そこが
    # 止まっていた（png はそのまま出るため、この不具合が出ない）。
    Image.new("RGB", (1050, 640), "white").save(tmp_path / "あぶない.pdf")
    log = tmp_path / "ログ.txt"
    log.write_text("08/03 13:00:00  開始 OCR あぶない.pdf\n", encoding="utf-8")
    monkeypatch.setattr(label, "LOG_PATH", log)
    return tmp_path


class TestTheImageIsStillShown:
    def test_the_card_image_is_not_blocked(self, cards: Path):
        """画像が出ないと手で入力もできない。"""
        client = TestClient(label.build_app(cards, prefill=True))

        assert client.get("/api/image/あぶない.pdf").status_code == 200

    def test_the_draft_is_still_skipped(self, cards: Path):
        """読み取りのほうは、原因が分かるまで自動では走らせない。"""
        body = TestClient(label.build_app(cards, prefill=True)).get(
            "/api/label/あぶない.pdf?draft=1"
        ).json()

        assert body["kind"] == "error"


class TestTheMarkClears:
    def test_the_supervisor_writes_the_clean_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """止めたときは見張り役が印を書く。子の後始末に頼らない。"""
        log = tmp_path / "ログ.txt"
        log.write_text("08/03 13:00:00  開始 OCR あぶない.pdf\n", encoding="utf-8")
        monkeypatch.setattr(label, "LOG_PATH", log)

        label.note_clean_stop()

        assert label.cards_that_crashed(log) == set()

    def test_the_mark_is_gone_on_the_next_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        log = tmp_path / "ログ.txt"
        log.write_text("08/03 13:00:00  開始 OCR あぶない.pdf\n", encoding="utf-8")
        monkeypatch.setattr(label, "LOG_PATH", log)
        assert label.cards_that_crashed(log) == {"あぶない.pdf"}

        label.note_clean_stop()

        assert label.cards_that_crashed(log) == set()


class TestTheWordingDoesNotSayItIsDownNow:
    def test_it_talks_about_the_previous_run(self, cards: Path):
        """「いま落ちている」と読めると、利用者は立ち上げ直そうとする。"""
        body = TestClient(label.build_app(cards, prefill=True)).get(
            "/api/label/あぶない.pdf?draft=1"
        ).json()

        assert "前回" in body["source"]
        assert "画面は使えます" in body["source"]

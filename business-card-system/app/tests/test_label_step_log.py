"""いま何をしているかを記録に残す（poc/label.py）。

実テストで、特定の名刺を開くと**サーバー自体が応答しなくなる**。

    5・6枚目（版 796d391）  サーバーが応答していません。
    8枚目（版 e68f9f9）     同じ。画像も出ず、OCRの文字も取れない

重い処理は別プロセスに出してあるので、子が落ちても親は生き残るはずだった。
それでも親が死んでいる。子を1つ保つ形にしても直らなかった。

**落ちると Python 側には何も残らない。** 例外も traceback も出ないため、
`_log_failure` は動かない。そこで、始めた時点で1行書いておく。記録の
最後の行が「どの名刺の、どの工程で止まったか」を示す。

    08/03 12:05:10  開始 画像の表示 (会社名)_回 叫回.pdf
    ← ここで記録が途切れていれば、その工程で落ちた

終わったら「完了」を書くので、開始だけが残っている行が手がかりになる。
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
    Image.new("RGB", (1050, 640), "white").save(tmp_path / "名刺.png")
    monkeypatch.setattr(label, "LOG_PATH", tmp_path / "ログ.txt")
    return tmp_path


@pytest.fixture
def client(cards: Path) -> TestClient:
    return TestClient(label.build_app(cards, prefill=True))


def log_of(cards: Path) -> str:
    path = cards / "ログ.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


class TestTheOcrStepIsRecorded:
    def test_the_start_is_written_before_the_work(self, client: TestClient, cards: Path):
        client.get("/api/label/名刺.png?draft=1")

        assert "開始 OCR 名刺.png" in log_of(cards)

    def test_the_finish_is_written_too(self, client: TestClient, cards: Path):
        client.get("/api/label/名刺.png?draft=1")

        assert "完了 OCR 名刺.png" in log_of(cards)

    def test_the_start_comes_first(self, client: TestClient, cards: Path):
        client.get("/api/label/名刺.png?draft=1")
        text = log_of(cards)

        assert text.index("開始 OCR") < text.index("完了 OCR")


class TestTheImageStepIsRecorded:
    """画像はPDFのときだけ別プロセスで描く。そこも落ちる場所になりうる。"""

    def test_a_pdf_records_the_step(self, client: TestClient, cards: Path):
        (cards / "名刺.pdf").write_bytes("%PDF-1.4 壊れています".encode("utf-8"))

        client.get("/api/image/名刺.pdf")

        assert "開始 画像の表示 名刺.pdf" in log_of(cards)

    def test_a_plain_image_is_not_recorded(self, client: TestClient, cards: Path):
        """PNG はそのまま返すだけで、別プロセスを使わない。"""
        client.get("/api/image/名刺.png")

        assert "画像の表示" not in log_of(cards)


class TestTheRecordSurvivesAFailure:
    def test_a_failed_card_still_leaves_the_start(self, client: TestClient, cards: Path):
        """失敗しても、始めた記録は残ること。"""
        client.get("/api/label/ない.png?draft=1")

        assert "開始 OCR ない.png" in log_of(cards)

    def test_writing_the_record_never_raises(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        """記録できなくても本筋を止めない（書き込めない場所を指しても平気）。"""
        monkeypatch.setattr(label, "LOG_PATH", Path("/ない/場所/ログ.txt"))

        res = client.get("/api/label/名刺.png?draft=1")

        assert res.status_code == 200

"""ラベル入力画面のOCR下書き（poc/label.py）。

正解ラベルを入力する画面は、OCRの結果を初期値として入れておく。
ここが壊れると入力そのものが止まるため、失敗したときの振る舞いだけを見る。

見るのは2点。

1. 失敗を覚え込まないこと（直したのに失敗したまま、を避ける）
2. どの工程で落ちたかが分かること（「OCRを使えませんでした」だけでは切り分けられない）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poc.label import build_app  # noqa: E402


@pytest.fixture
def cards(tmp_path: Path) -> Path:
    Image.new("RGB", (1650, 1000), "white").save(tmp_path / "card01.jpg")
    return tmp_path


def test_failure_is_not_remembered(cards: Path, monkeypatch):
    """一度失敗しても、次に開けばやり直すこと。

    失敗をキャッシュすると、tesseract を入れ直しても画面を開き直すまで
    失敗したままになり、直ったことに気づけない。
    """
    import bcards.services.ocr as ocr_service

    calls = {"n": 0}

    def _flaky(image):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("一時的な失敗")
        return None, {"fields": {"company_name": "株式会社サンプル商事"}, "confidence": {}}

    monkeypatch.setattr(ocr_service, "recognize_card", _flaky)

    client = TestClient(build_app(cards, prefill=True))

    first = client.get("/api/label/card01.jpg").json()
    assert first["kind"] == "error"

    second = client.get("/api/label/card01.jpg").json()
    assert second["kind"] == "draft", "失敗を覚え込んでいる"
    assert second["values"]["company_name"] == "株式会社サンプル商事"


def test_success_is_remembered(cards: Path, monkeypatch):
    """成功はキャッシュすること（1枚あたり数秒かかるため）。"""
    import bcards.services.ocr as ocr_service

    calls = {"n": 0}

    def _once(image):
        calls["n"] += 1
        return None, {"fields": {"company_name": "テクノロジー株式会社"}, "confidence": {}}

    monkeypatch.setattr(ocr_service, "recognize_card", _once)

    client = TestClient(build_app(cards, prefill=True))
    client.get("/api/label/card01.jpg")
    client.get("/api/label/card01.jpg")

    assert calls["n"] == 1


def test_error_names_the_failing_step(cards: Path, monkeypatch):
    """どの工程で落ちたかを画面に出すこと。"""
    import bcards.services.images as image_service

    def _boom(*args, **kwargs):
        raise RuntimeError("画像が壊れています")

    monkeypatch.setattr(image_service, "process_file", _boom)

    client = TestClient(build_app(cards, prefill=True))
    body = client.get("/api/label/card01.jpg").json()

    assert body["kind"] == "error"
    assert "画像の読み込みと補正" in body["source"]
    assert "画像が壊れています" in body["source"]

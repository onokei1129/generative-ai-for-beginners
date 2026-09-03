"""ラベル入力画面のOCR下書き（poc/label.py）。

正解ラベルを入力する画面は、OCRの結果を初期値として入れておく。
ここが壊れると入力そのものが止まるため、失敗したときの振る舞いだけを見る。

見るのは2点。

1. 失敗を覚え込まないこと（直したのに失敗したまま、を避ける）
2. どの工程で落ちたかが分かること（「OCRを使えませんでした」だけでは切り分けられない）
"""

from __future__ import annotations

import sys
import time
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
    import poc.label as label_module

    calls = {"n": 0}

    def _flaky(args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("一時的な失敗")
        return {"fields": {"company_name": "株式会社サンプル商事"}, "text": ""}

    monkeypatch.setattr(label_module, "run_in_child", _flaky)

    client = TestClient(build_app(cards, prefill=True))

    first = client.get("/api/label/card01.jpg").json()
    assert first["kind"] == "error"

    second = client.get("/api/label/card01.jpg").json()
    assert second["kind"] == "draft", "失敗を覚え込んでいる"
    assert second["values"]["company_name"] == "株式会社サンプル商事"


def test_success_is_remembered(cards: Path, monkeypatch):
    """成功はキャッシュすること（1枚あたり数秒かかるため）。

    **その回の1枚目だけは2回読む。** 1回目は軽い読み取り機（画面をすぐ出す
    ため）、2回目は既定の読み取り機での読み直し（`_mark_provisional` を参照）。
    数えているのはそれ以上増えないこと——要求のたびに読み直してはいない。
    """
    import poc.label as label_module

    calls = {"n": 0}

    def _once(args):
        calls["n"] += 1
        return {"fields": {"company_name": "テクノロジー株式会社"}, "text": ""}

    monkeypatch.setattr(label_module, "run_in_child", _once)

    client = TestClient(build_app(cards, prefill=True))
    client.get("/api/label/card01.jpg")
    client.get("/api/label/card01.jpg")
    time.sleep(0.3)  # 裏の読み直しが走りきるのを待つ
    client.get("/api/label/card01.jpg")

    assert calls["n"] == 2, "1枚目は「軽い読み取り＋読み直し」の2回で済むはず"


def test_a_later_card_is_read_once(cards: Path, monkeypatch):
    """2枚目からは読み直しが無いので1回で済む。"""
    import poc.label as label_module

    calls = {"n": 0}

    def _once(args):
        calls["n"] += 1
        return {"fields": {"company_name": "テクノロジー株式会社"}, "text": ""}

    monkeypatch.setattr(label_module, "run_in_child", _once)

    client = TestClient(build_app(cards, prefill=True))
    client.get("/api/label/card01.jpg")   # 1枚目（軽い読み取り＋読み直し）
    time.sleep(0.3)
    before = calls["n"]
    client.get("/api/label/card02.jpg")
    client.get("/api/label/card02.jpg")

    assert calls["n"] - before == 1


def test_error_names_the_failing_step(cards: Path, monkeypatch):
    """どの工程で落ちたかを画面に出すこと。

    重い処理は別プロセスで動く。子が落ちたときは、終了コードと標準エラーの
    最後の行を添えて返す（`run_in_child` の説明を参照）。
    """
    import poc.label as label_module

    def _boom(args):
        raise label_module.ChildFailed("画像が壊れています（終了コード -1073741819）")

    monkeypatch.setattr(label_module, "run_in_child", _boom)

    client = TestClient(build_app(cards, prefill=True))
    body = client.get("/api/label/card01.jpg").json()

    assert body["kind"] == "error"
    assert "OCR（別プロセス）" in body["source"]
    assert "画像が壊れています" in body["source"]
    assert "終了コード" in body["source"]

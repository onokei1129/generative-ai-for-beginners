"""その回の1枚目を、裏で読み直して差し替える（poc/label.py）。

## なぜ要るのか

既定は2つの読み取り機の併用だが、**その回の1枚目だけ軽いほうに落とす**
（`hint_for_now`）。EasyOCR のモデル読み込みに45秒かかり、それが「落ちて
いる」と受け取られたため。代償はその1枚の精度（78.2% → 64.8%）。

ここで2つが重なっていた。

1. **アプリが落ちるたびに開き直す**（実テストの記録で11回）
2. **開き直すと、止まった名刺から再開する**

つまり**いま作業している名刺が、毎回いちばん精度の低い読み方をされる**。
しかも結果は覚え込まれるので、その回のあいだ直らない。

実テスト35枚目（笠間 信一郎）はこれに当たり、姓が `Sele]` と読まれて
氏名の欄がローマ字（`Kasama` / `Shinichiro`）になっていた。もう一方の
読み取り機は、この名刺を一度も見ていない。

## 何をするか

軽いほうで即座に下書きを出す狙いは変えない（45秒の空白を作らない）。
そのうえで裏で読み直し、**利用者がまだ一度も触っていない欄だけ**差し替える。
待ち時間は増えず、精度は戻る。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402


def _card(directory: Path, name: str) -> Path:
    path = directory / name
    Image.new("RGB", (600, 380), "white").save(path)
    return path


class TestTheFirstCardIsMarkedForRevision:
    def test_the_first_draft_says_it_is_being_revised(self, tmp_path, monkeypatch):
        """1枚目は `revising` を立てて返す。画面はこれを見て待つ。"""
        _card(tmp_path, "a.png")
        seen: list[str] = []

        def fake_child(args):
            seen.append(args[2])
            first = args[2] == label.FIRST_CARD_HINT
            # 実際の読み直しはモデルの読み込みで45秒かかる。ここで待たないと
            # 印を確かめる前に下りてしまう。
            if not first:
                time.sleep(0.5)
            return {
                "fields": {"last_name": "軽" if first else "重"},
                "text": "text",
            }

        monkeypatch.setattr(label, "run_in_child", fake_child)

        with TestClient(label.build_app(tmp_path, True)) as client:
            body = client.get("/api/label/a.png?draft=1").json()

        assert body["revising"] is True
        assert body["values"]["last_name"] == "軽"
        assert seen[0] == label.FIRST_CARD_HINT

    def test_the_revision_replaces_the_cached_draft(self, tmp_path, monkeypatch):
        """読み直しが終わると、次に訊いたときは新しい値になり印も下りる。"""
        _card(tmp_path, "a.png")

        def fake_child(args):
            first = args[2] == label.FIRST_CARD_HINT
            if not first:
                time.sleep(0.3)
            return {"fields": {"last_name": "軽" if first else "重"}, "text": "t"}

        monkeypatch.setattr(label, "run_in_child", fake_child)

        with TestClient(label.build_app(tmp_path, True)) as client:
            assert client.get("/api/label/a.png?draft=1").json()["revising"] is True
            deadline = time.monotonic() + 10
            body = {}
            while time.monotonic() < deadline:
                body = client.get("/api/label/a.png?draft=1").json()
                if not body["revising"]:
                    break
                time.sleep(0.05)

        assert body["revising"] is False
        assert body["values"]["last_name"] == "重", "読み直しの結果に入れ替わっていない"

    def test_a_later_card_is_not_marked(self, tmp_path, monkeypatch):
        """2枚目からは既定の読み取り機。読み直す理由が無い。"""
        _card(tmp_path, "a.png")
        _card(tmp_path, "b.png")
        monkeypatch.setattr(
            label, "run_in_child", lambda args: {"fields": {"last_name": "x"}, "text": "t"}
        )

        with TestClient(label.build_app(tmp_path, True)) as client:
            client.get("/api/label/a.png?draft=1")
            body = client.get("/api/label/b.png?draft=1").json()

        assert body["revising"] is False


class TestTheRevisionDoesNotBlockTheScreen:
    def test_a_failing_revision_still_clears_the_flag(self, tmp_path, monkeypatch):
        """読み直せなくても印は必ず下ろす。残すと画面が待ち続ける。"""
        _card(tmp_path, "a.png")

        def fake_child(args):
            if args[2] != label.FIRST_CARD_HINT:
                raise RuntimeError("わざと失敗")
            return {"fields": {"last_name": "軽"}, "text": "t"}

        monkeypatch.setattr(label, "run_in_child", fake_child)

        with TestClient(label.build_app(tmp_path, True)) as client:
            client.get("/api/label/a.png?draft=1")
            deadline = time.monotonic() + 10
            body = {}
            while time.monotonic() < deadline:
                body = client.get("/api/label/a.png?draft=1").json()
                if not body["revising"]:
                    break
                time.sleep(0.05)

        assert body["revising"] is False
        assert body["values"]["last_name"] == "軽", "失敗したのに元の下書きまで消えている"


class TestTheRevisionIsNotMistakenForACrash:
    """読み直しの記録を、落ちた名刺の判定に混ぜない。

    `cards_that_crashed` は工程名を見ず**名刺の名前だけ**を拾う。読み直しを
    `開始 …` `完了 …` の形で書くと、その途中で落ちたときにこの名刺が
    「触ってはいけない名刺」になる。軽いほうの下書きは既に出来ていて作業
    できるのに、それを塞ぐことになる。
    """

    def test_an_interrupted_revision_does_not_block_the_card(self, tmp_path):
        log = tmp_path / "ラベル入力ログ.txt"
        log.write_text("08/24 10:00:00  読み直しに入る: a.png\n", encoding="utf-8")

        assert label.cards_that_crashed(log) == set()

    def test_an_interrupted_ocr_still_blocks_the_card(self, tmp_path):
        """本来の判定は変えない。"""
        log = tmp_path / "ラベル入力ログ.txt"
        log.write_text("08/24 10:00:00  開始 OCR b.png\n", encoding="utf-8")

        assert label.cards_that_crashed(log) == {"b.png"}

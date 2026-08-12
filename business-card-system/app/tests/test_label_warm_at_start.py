"""立ち上げたらすぐ、1枚目のOCRを裏で始める。

先読みは「利用者が名刺を開いたら、その次の2枚を進める」作りだった。
**1枚目だけは誰も温めていない。** そこに EasyOCR のモデルの読み込みが乗る。

実測（開発機）:

    easyocr（1回目・モデル読み込み込み）  16.2秒
    tesseract                              2.1秒
    併用ぜんぶ（2回目・温まった状態）      3.5秒

1枚目だけ十数秒かかり、そのあいだ画面は空欄のまま進まない。実テストでも
最初の報告が「立ち上げ時に既にサーバが落ちている」（1枚目で18秒のバー）で、
記録にも1枚目の画像だけが残って途切れた起動がある（08/04 12:00:57）。

利用者がブラウザを開いて画面を見るまでのあいだに済ませる。
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from poc import label  # noqa: E402


def a_folder_of_cards(root: Path, names: list[str]) -> None:
    for name in names:
        Image.new("RGB", (300, 190), "white").save(root / name)


class TestTheFirstCardIsWarmedAtStart:
    def test_it_asks_for_the_first_card(self, tmp_path: Path, monkeypatch):
        asked: list[str] = []
        monkeypatch.setattr(
            label, "run_in_child", lambda args: asked.append(args[1]) or {"fields": {}, "text": ""}
        )
        a_folder_of_cards(tmp_path, ["a.png", "b.png", "c.png"])

        with TestClient(label.build_app(tmp_path, True)):
            pass  # 立ち上げと後片付けだけ。画面は開かない。

        assert asked, "起動しても1枚目を温めていない"
        assert Path(asked[0]).name == "a.png"


class TestItWarmsTheCardTheScreenOpens:
    """画面は入力済みを飛ばす。温めるほうも合わせる。

    合っていないと、読み取り機が1本しかないため、利用者が開いた名刺は
    温めている名刺の後ろに並ぶ。実テストで **45秒が65秒に悪化した**
    （入力済み20枚、画面は3枚目から開く場合）。
    """

    def test_it_skips_the_ones_already_labeled(self, tmp_path: Path, monkeypatch):
        asked: list[str] = []
        monkeypatch.setattr(
            label, "run_in_child", lambda args: asked.append(args[1]) or {"fields": {}, "text": ""}
        )
        a_folder_of_cards(tmp_path, ["a.png", "b.png", "c.png"])
        for done in ("a.json", "b.json"):
            (tmp_path / done).write_text("{}", encoding="utf-8")

        with TestClient(label.build_app(tmp_path, True)):
            pass

        assert asked, "起動しても温めていない"
        assert Path(asked[0]).name == "c.png", "入力済みの名刺を温めている"

    def test_all_labeled_falls_back_to_the_first(self, tmp_path: Path, monkeypatch):
        """全部入力済みなら画面は先頭を開く。温めるほうも先頭にする。"""
        asked: list[str] = []
        monkeypatch.setattr(
            label, "run_in_child", lambda args: asked.append(args[1]) or {"fields": {}, "text": ""}
        )
        a_folder_of_cards(tmp_path, ["a.png", "b.png"])
        for done in ("a.json", "b.json"):
            (tmp_path / done).write_text("{}", encoding="utf-8")

        with TestClient(label.build_app(tmp_path, True)):
            pass

        assert asked and Path(asked[0]).name == "a.png"

    def test_the_screen_and_the_warm_up_use_the_same_rule(self):
        """画面側の選び方（入力済みを飛ばす）と食い違わせない。"""
        source = (APP / "poc" / "label.py").read_text(encoding="utf-8")

        assert "findIndex(f => !f.labeled)" in source, "画面側の選び方が変わっている"
        body = source[source.index("def warm_up_at_start") : source.index("at_start.append")]
        assert "label_path(p).exists()" in body, "温める側が入力済みを飛ばしていない"

    def test_an_empty_folder_does_not_break_startup(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(label, "run_in_child", lambda args: {"fields": {}, "text": ""})

        with TestClient(label.build_app(tmp_path, True)) as client:
            assert client.get("/api/files").status_code == 200

    def test_a_failure_does_not_break_startup(self, tmp_path: Path, monkeypatch):
        """温められなくても起動する。先読みは無くても動く仕掛け。"""
        def boom(args):
            raise RuntimeError("読めません")

        monkeypatch.setattr(label, "run_in_child", boom)
        a_folder_of_cards(tmp_path, ["a.png"])

        with TestClient(label.build_app(tmp_path, True)) as client:
            assert client.get("/api/files").status_code == 200

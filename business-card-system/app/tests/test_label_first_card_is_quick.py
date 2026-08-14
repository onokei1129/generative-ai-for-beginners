"""その回の1枚目だけ、軽い読み取り機で下書きする。

既定は EasyOCR と tesseract の併用で、精度は高いが**最初の1枚で EasyOCR の
モデルを読み込む**。実測（利用者の環境）:

    1枚目          45秒
    2枚目以降      ほぼゼロ（先読みが間に合う）

待たされるのは1枚目だけ。そこだけ tesseract にすると数秒で返り、利用者は
すぐ作業を始められる。その裏で2枚目以降の先読みが走り、モデルの読み込みは
そこで済む。

代償はその1枚の精度（併用 77.2% → tesseract のみ 68.0%。1枚あたり1項目ほど
修正が増える）。45秒の空白は「サーバーが落ちている」と受け取られており、
実テストでは実際にその状態で黒い画面を閉じられていた（記録の終了コード
3221225786）。1枚ぶんの手直しと引き換える。
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
from tests.test_label_warm_at_start import wait_for  # noqa: E402


def a_folder_of_cards(root: Path, names: list[str]) -> None:
    for name in names:
        Image.new("RGB", (300, 190), "white").save(root / name)


def asked_providers(tmp_path: Path, monkeypatch, cards: list[str]) -> list[str]:
    """OCRを頼むたびに、指定された読み取り機を並べて返す。"""
    seen: list[str] = []

    def watching(args):
        if args[0] == "ocr":
            seen.append(args[2] if len(args) > 2 else "")
        return {"fields": {}, "text": ""}

    monkeypatch.setattr(label, "run_in_child", watching)
    a_folder_of_cards(tmp_path, cards)

    with TestClient(label.build_app(tmp_path, True)) as client:
        wait_for(seen)
        for name in cards:
            client.get(f"/api/label/{name}", params={"draft": "1"})
    return seen


class TestOnlyTheFirstCardGetsTheHint:
    def test_the_first_one_is_flagged(self, tmp_path: Path, monkeypatch):
        seen = asked_providers(tmp_path, monkeypatch, ["a.png", "b.png", "c.png"])

        assert seen, "OCRを頼んでいない"
        assert seen[0] == label.FIRST_CARD_HINT == "first"

    def test_the_rest_are_not(self, tmp_path: Path, monkeypatch):
        """2枚目からは合図を出さない。空文字は「設定どおり」の意味。"""
        seen = asked_providers(tmp_path, monkeypatch, ["a.png", "b.png", "c.png"])

        assert len(seen) > 1, "2枚目以降を頼んでいない"
        assert all(name == "" for name in seen[1:]), f"1枚目以外にも合図を出している: {seen}"


class TestTheChildDecidesWhichEngine:
    """落とすのは併用構成のときだけ。設定を無視して置き換えない。

    擬似OCR（試験）や別のサービスを指定している環境では、モデルの読み込みが
    無いので落とす理由も無い。設定を無視すると、それらの環境の読み取り機まで
    tesseract に置き換えてしまう。
    """

    def test_the_combined_setup_drops_to_the_quick_one(self, monkeypatch):
        from bcards.config import settings
        from poc import one_card

        monkeypatch.setattr(settings, "ocr_provider", "combined")
        assert one_card.provider_for("first") == one_card.QUICK_PROVIDER

    def test_other_setups_are_left_alone(self, monkeypatch):
        from bcards.config import settings
        from poc import one_card

        for configured in ("mock", "azure", "tesseract"):
            monkeypatch.setattr(settings, "ocr_provider", configured)
            assert one_card.provider_for("first") is None, configured

    def test_no_hint_means_the_setting(self, monkeypatch):
        from bcards.config import settings
        from poc import one_card

        monkeypatch.setattr(settings, "ocr_provider", "combined")
        assert one_card.provider_for(None) is None
        assert one_card.provider_for("") is None

    def test_the_hint_reaches_the_child(self, tmp_path: Path, monkeypatch):
        from poc import one_card

        got: list = []
        monkeypatch.setattr(
            one_card, "run_ocr", lambda path, hint=None: got.append(hint) or {}
        )
        one_card.dispatch("ocr", [str(tmp_path / "a.png"), "first"])
        one_card.dispatch("ocr", [str(tmp_path / "a.png")])

        assert got == ["first", None]

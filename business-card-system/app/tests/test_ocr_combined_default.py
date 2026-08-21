"""併用構成を既定にする（論点C：決裁 2026-08-02）。

案2の計測で、EasyOCR と tesseract の併用が 68.0% → 74.9%（1枚あたりの
修正 4.2 → 3.2 項目）と分かったため、既定を `combined` にした。

既定にすると、**入っていない環境で黙って劣化する**という新しい危険が出る。
EasyOCR は依存が大きく（約1.5GB）自動では入らないため、入れ忘れた環境では
tesseract だけで動き、見た目は正常なまま精度が戻る。気づけない。

（数値は当時の物差しのもの。2026/08/20 に測り直して 64.8% → 78.2% になった。
ocr-poc-report.md §0 を参照。差が開いたので、知らせる必要はむしろ増えた。）

そこで、使えなかったエンジンを結果に残し、起動時と動作確認（doctor）で
知らせる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from bcards.config import settings  # noqa: E402
from bcards.services import ocr  # noqa: E402
from bcards.services.ocr.base import OcrOutput  # noqa: E402
from bcards import startup  # noqa: E402
from bcards.startup import check_configuration  # noqa: E402


class TestTheDefaultIsTheCombinedProvider:
    def test_the_setting_defaults_to_combined(self):
        """テスト全体は mock を強制している（conftest.py）ため、
        `settings.ocr_provider` を見ても既定値は分からない。

        module を読み直すと `settings` が別物に差し替わり、それを掴んで
        いる他のテストが壊れる（実際に3件壊した）。既定値の宣言そのものを
        見る。
        """
        source = (APP / "src" / "bcards" / "config.py").read_text(encoding="utf-8")

        assert '_env("BCARDS_OCR_PROVIDER", "combined")' in source

    def test_recognize_card_uses_it_without_being_told(self, monkeypatch: pytest.MonkeyPatch):
        _install_fakes(monkeypatch)
        monkeypatch.setattr(settings, "ocr_provider", "combined")

        output, _ = ocr.recognize_card(_image())

        assert output.provider == ocr.COMBINED


class TestAMissingEngineIsNotSilent:
    def test_the_result_records_which_engines_ran(self, monkeypatch: pytest.MonkeyPatch):
        _install_fakes(monkeypatch, break_engine="easyocr")
        monkeypatch.setattr(settings, "ocr_provider", "combined")

        output, _ = ocr.recognize_card(_image())

        assert output.raw["engines"] == ["tesseract"]
        assert output.raw["failures"]

    def test_startup_warns_when_easyocr_is_missing(self, monkeypatch: pytest.MonkeyPatch):
        """入れ忘れると精度が 68.0% に戻る。黙って戻ってはいけない。"""
        monkeypatch.setattr(settings, "ocr_provider", "combined")
        monkeypatch.setattr(startup, "_missing_engines", lambda: [("EasyOCR", "easyocr")])

        messages = " ".join(f.message for f in check_configuration())

        assert "EasyOCR" in messages
        assert "requirements-combined.txt" in messages

    def test_startup_is_quiet_when_every_engine_is_installed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "ocr_provider", "combined")
        monkeypatch.setattr(startup, "_missing_engines", lambda: [])

        messages = " ".join(f.message for f in check_configuration())

        assert "EasyOCR" not in messages

    def test_a_single_engine_setting_is_not_warned_about(self, monkeypatch: pytest.MonkeyPatch):
        """`tesseract` を明示的に選んでいる環境に、この警告は関係ない。"""
        monkeypatch.setattr(settings, "ocr_provider", "tesseract")
        monkeypatch.setattr(startup, "_missing_engines", lambda: [("EasyOCR", "easyocr")])

        messages = " ".join(f.message for f in check_configuration())

        assert "EasyOCR" not in messages

    def test_the_check_does_not_start_the_engine(self):
        """起動すると PyTorch とモデルの読み込みで数秒かかる。
        設定の点検のたびにそれを払わないこと。"""
        source = (APP / "src" / "bcards" / "startup.py").read_text(encoding="utf-8")

        assert "find_spec" in source
        assert "EasyOcrProvider" not in source


class TestTheCheckerLooksAtTheRealDefault:
    SOURCE = (APP / "poc" / "doctor.py").read_text(encoding="utf-8")

    def test_the_ocr_check_no_longer_pins_tesseract(self):
        """既定を変えたのに、動作確認だけ tesseract を見ていては意味がない。"""
        assert 'os.environ["BCARDS_OCR_PROVIDER"] = "tesseract"' not in self.SOURCE

    def test_easyocr_has_its_own_check(self):
        assert "EasyOCR" in self.SOURCE


def _image() -> Image.Image:
    return Image.new("RGB", (60, 40), "white")


def _install_fakes(monkeypatch: pytest.MonkeyPatch, break_engine: str = "") -> None:
    def make(name: str):
        def factory():
            if break_engine in (name, "both"):
                raise RuntimeError(f"{name} は入っていません")
            return _FakeProvider(name, ["株式会社サンプル"])

        return factory

    monkeypatch.setattr(ocr, "_PROVIDERS", dict(ocr._PROVIDERS))
    monkeypatch.setitem(ocr._PROVIDERS, "easyocr", make("easyocr"))
    monkeypatch.setitem(ocr._PROVIDERS, "tesseract", make("tesseract"))


class _FakeProvider:
    def __init__(self, name: str, lines: list[str]) -> None:
        self.name = name
        self.lines = lines

    def recognize(self, image: Image.Image) -> OcrOutput:
        return OcrOutput(
            provider=self.name,
            api_version="0",
            text="\n".join(self.lines),
            lines=list(self.lines),
            raw={},
            confidence=0.5,
        )

"""2つの読み取りエンジンを併用する構成（論点C：案2の計測結果）。

論点Cの比較で、tesseract と EasyOCR の弱点が重ならないことが分かった。

    正解      takahashi@hokkaido-foods.example
    EasyOCR   takahashi@hokkaido-foodsexample     ← 英数字の記号を落とす
    正解      株式会社ロジスティクス九州
    tesseract 株 式 会 社 ロ ジス ティ クス 九州   ← 日本語を1字ずつ切る

そこで両方かけて、項目ごとに取れたほうを採る。合成サンプル20枚では
項目正答率 70.4% → 76.8%、1枚あたりの修正 4.2 → 3.2 項目だった。

ここで守るのは併合の規則そのもの。「どちらを優先するか」「片方が
落ちたときどうするか」を変えると、この構成の意味が変わる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services import ocr  # noqa: E402
from bcards.services.ocr.base import OcrOutput  # noqa: E402


class TestTheMergeRule:
    def test_the_first_engine_wins_when_it_has_a_value(self):
        merged = ocr.merge_fields(
            [
                {"fields": {"company_name": "株式会社ロジスティクス九州"}},
                {"fields": {"company_name": "株 式 会 社 ロ ジス ティ クス 九州"}},
            ]
        )

        assert merged["fields"]["company_name"] == "株式会社ロジスティクス九州"

    def test_the_next_engine_fills_an_empty_value(self):
        """これが併用の狙い。EasyOCR が落とした英数字を tesseract が埋める。"""
        merged = ocr.merge_fields(
            [
                {"fields": {"email": ""}},
                {"fields": {"email": "takahashi@hokkaido-foods.example"}},
            ]
        )

        assert merged["fields"]["email"] == "takahashi@hokkaido-foods.example"

    def test_a_field_missing_from_the_first_engine_is_still_taken(self):
        merged = ocr.merge_fields([{"fields": {}}, {"fields": {"url": "https://example.jp"}}])

        assert merged["fields"]["url"] == "https://example.jp"

    def test_both_empty_stays_empty(self):
        merged = ocr.merge_fields([{"fields": {"fax": ""}}, {"fields": {"fax": ""}}])

        assert merged["fields"]["fax"] == ""

    def test_the_confidence_follows_the_value_that_was_taken(self):
        """採らなかったほうの確信度を持ち回ると、値と食い違う。"""
        merged = ocr.merge_fields(
            [
                {"fields": {"tel": ""}, "confidence": {"tel": 0.1}},
                {"fields": {"tel": "03-1234-5678"}, "confidence": {"tel": 0.9}},
            ]
        )

        assert merged["confidence"]["tel"] == 0.9

    def test_the_order_of_engines_is_pinned(self):
        """日本語のほうが項目数が多いため、EasyOCR を先に置いている。"""
        assert ocr.COMBINED_ENGINES == ("easyocr", "tesseract")


class TestAPlausibleWrongValueGivesWay:
    """空欄なら人が気づくが、それらしい誤りは気づかれずに登録される。

    EasyOCR は英数字の記号を落とすため、ちょうどこの誤り方をする。

    ただし拾えるのは形が壊れたものだけ。`example.co.jp` の途中のドットが
    落ちて `exampleco.jp` になった場合はメールの形として正しいため、
    この検査では見分けられない（実測でも3件あった）。読み取りの誤りを
    後段で完全に救うことはできない。
    """

    def test_an_email_with_no_dot_after_the_at_gives_way(self):
        """実測で出た誤り：takahashi@hokkaido-foods.example → …foodsexample"""
        merged = ocr.merge_fields(
            [
                {"fields": {"email": "takahashi@hokkaido-foodsexample"}},
                {"fields": {"email": "takahashi@hokkaido-foods.example"}},
            ]
        )

        assert merged["fields"]["email"] == "takahashi@hokkaido-foods.example"

    def test_a_dot_lost_in_the_middle_cannot_be_caught(self):
        """見分けられないことを、分かったうえで残す。"""
        merged = ocr.merge_fields(
            [
                {"fields": {"email": "taro@exampleco.jp"}},
                {"fields": {"email": "taro@example.co.jp"}},
            ]
        )

        assert merged["fields"]["email"] == "taro@exampleco.jp"

    def test_a_url_with_a_broken_scheme_gives_way(self):
        merged = ocr.merge_fields(
            [
                {"fields": {"url": "https:Illogi-kyushuexample"}},
                {"fields": {"url": "https://logi-kyushu.example"}},
            ]
        )

        assert merged["fields"]["url"] == "https://logi-kyushu.example"

    def test_the_confidence_follows_the_replacement(self):
        merged = ocr.merge_fields(
            [
                {"fields": {"email": "taro@exampleco"}, "confidence": {"email": 0.9}},
                {"fields": {"email": "taro@example.co.jp"}, "confidence": {"email": 0.4}},
            ]
        )

        assert merged["confidence"]["email"] == 0.4

    def test_a_shaped_value_is_not_displaced_by_a_broken_one(self):
        merged = ocr.merge_fields(
            [
                {"fields": {"email": "taro@example.co.jp"}},
                {"fields": {"email": "taro@exampleco"}},
            ]
        )

        assert merged["fields"]["email"] == "taro@example.co.jp"

    def test_a_broken_value_is_kept_when_nothing_better_exists(self):
        """空にすると手がかりごと失う。人が直せるように残す。"""
        merged = ocr.merge_fields(
            [{"fields": {"email": "taro@exampleco"}}, {"fields": {"email": ""}}]
        )

        assert merged["fields"]["email"] == "taro@exampleco"

    def test_fields_without_a_fixed_shape_are_not_checked(self):
        """住所や会社名に形の検査を掛けると、正しい値まで落ちる。"""
        merged = ocr.merge_fields(
            [
                {"fields": {"address": "東京都千代田区千代田1-1-1"}},
                {"fields": {"address": "東京都千代田区千代田"}},
            ]
        )

        assert merged["fields"]["address"] == "東京都千代田区千代田1-1-1"


class TestRecognizeCard:
    def test_the_combined_provider_runs_every_engine(self, monkeypatch: pytest.MonkeyPatch):
        _install_fakes(monkeypatch)

        output, parsed = ocr.recognize_card(_image(), ocr.COMBINED)

        assert output.raw["engines"] == ["easyocr", "tesseract"]
        assert parsed["fields"]["company_name"] == "株式会社サンプル"
        assert parsed["fields"]["email"] == "taro@example.co.jp"

    def test_both_engines_texts_are_kept_and_labelled(self, monkeypatch: pytest.MonkeyPatch):
        """確認画面でどちらが読めたのかを見分けられないと、原因を切り分けられない。"""
        _install_fakes(monkeypatch)

        output, _ = ocr.recognize_card(_image(), ocr.COMBINED)

        assert "--- easyocr ---" in output.text
        assert "--- tesseract ---" in output.text

    def test_one_broken_engine_does_not_stop_the_other(self, monkeypatch: pytest.MonkeyPatch):
        _install_fakes(monkeypatch, break_engine="easyocr")

        output, parsed = ocr.recognize_card(_image(), ocr.COMBINED)

        assert output.raw["engines"] == ["tesseract"]
        assert parsed["fields"]["email"] == "taro@example.co.jp"
        assert any("easyocr" in reason for reason in output.raw["failures"])

    def test_every_engine_broken_raises_instead_of_falling_back_to_mock(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """mock に落とすと、擬似OCRの値を読み取り結果として保存してしまう。"""
        _install_fakes(monkeypatch, break_engine="both")

        with pytest.raises(RuntimeError, match="読み取りエンジン"):
            ocr.recognize_card(_image(), ocr.COMBINED)

    def test_a_single_provider_is_untouched(self, monkeypatch: pytest.MonkeyPatch):
        _install_fakes(monkeypatch)

        output, _ = ocr.recognize_card(_image(), "tesseract")

        assert output.provider == "tesseract"


def _image() -> Image.Image:
    return Image.new("RGB", (60, 40), "white")


def _install_fakes(monkeypatch: pytest.MonkeyPatch, break_engine: str = "") -> None:
    """実物のエンジンを使わずに併合の規則だけを見る。

    EasyOCR 役は日本語を続けて読むがメールのドットを落とし、
    tesseract 役は日本語を1字ずつ切るがメールは取れる — 実測どおりに作る。
    """

    lines = {
        "easyocr": ["株式会社サンプル", "taro@exampleco"],
        "tesseract": ["株 式 会 社 サ ン プル", "taro@example.co.jp"],
    }

    def make(name: str):
        def factory():
            if break_engine in (name, "both"):
                raise RuntimeError(f"{name} は入っていません")
            return _FakeProvider(name, lines[name])

        return factory

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

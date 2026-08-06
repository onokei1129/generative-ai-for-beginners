"""読めなかった名刺は、回してもう一度読む（services/ocr）。

実テスト 22枚目（縦書き）は、どちらの読み取り機も意味のある文字を1つも
取れなかった。

    夢 / 蟹   麗 / 喜 / 川 1 / 昌 / 昌   亀 / 量 / 喜 麗 / 畳

縦書きの名刺は、字が縦に並ぶだけでなく**紙ごと横倒しで取り込まれている**
ことが多い。画像を90度回せば、ふつうの横書きとして読める。

回すかどうかは**結果を見て決める**。読めた名刺はそのまま返すので、
横書きの名刺は1枚も遅くならない。何枚が縦書きかを数えなくてよい。

読めたかどうかは、取り出せた項目の数で見る。メール・電話・郵便番号・
会社名——どれ1つ取れていなければ、その読み取りは失敗している。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import OcrOutput, looks_unreadable  # noqa: E402


def parsed(**fields) -> dict:
    keys = ("last_name", "first_name", "company_name", "email", "tel", "mobile",
            "postal_code", "address", "title", "department_name", "url", "fax")
    return {"fields": {key: fields.get(key, "") for key in keys}}


class TestDecidingItFailed:
    def test_a_card_with_nothing_useful_is_unreadable(self):
        assert looks_unreadable(parsed())

    def test_a_stray_name_alone_is_not_enough(self):
        """実テスト 22枚目は 姓『蟹』名『麗』だけが出ていた。"""
        assert looks_unreadable(parsed(last_name="蟹", first_name="麗"))

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("email", "taro@example.co.jp"),
            ("tel", "03-1234-5678"),
            ("postal_code", "100-0001"),
        ],
    )
    def test_one_checkable_field_is_enough(self, key: str, value: str):
        """形を確かめられる項目が1つでも取れていれば、その名刺は読めている。"""
        assert not looks_unreadable(parsed(**{key: value}))

    @pytest.mark.parametrize("key", ["company_name", "address"])
    def test_free_text_is_not_evidence(self, key: str):
        """住所と会社名は証拠に数えない。

        はじめは数えていた。実テスト 25枚目（縦書き）で、読み崩れが住所欄に
        入るたびに「読めた」と判定され、回して読み直す仕掛けが止まっていた。
        歯止めを足しても別のゴミが通る（`bEOO-SEI=…` → `soipms OOWVN IVQNV8`）。
        自由な文字列は証拠にしないのが筋。詳しくは
        `test_ocr_readable_needs_a_checkable_field.py`。
        """
        assert looks_unreadable(parsed(**{key: "株式会社サンプル"}))


class TestTurningTheImage:
    def test_the_image_is_read_again_when_it_failed(self, monkeypatch: pytest.MonkeyPatch):
        """縦向きのときだけ文字が出る、という読み取り機で確かめる。"""
        import bcards.services.ocr as ocr

        seen: list[tuple[int, int]] = []

        def fake(image: Image.Image, provider_name=None) -> tuple[OcrOutput, dict]:
            seen.append(image.size)
            if image.width > image.height:      # 元の向き。読めない
                return OcrOutput(provider="fake", api_version=None, text="蟹 麗"), parsed(last_name="蟹")
            return OcrOutput(provider="fake", api_version=None, text="読めた"), parsed(
                company_name="株式会社サンプル", email="taro@example.co.jp"
            )

        monkeypatch.setattr(ocr, "_recognize_once", fake)
        image = Image.new("RGB", (1050, 640), "white")

        _, result = ocr.recognize_card(image, provider_name="combined")

        assert result["fields"]["company_name"] == "株式会社サンプル"
        assert len(seen) > 1, "1回しか読んでいない"

    def test_a_card_that_is_unreadable_in_every_direction_costs_little(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """回しても読めない名刺で、重い読み取りを何度も走らせないこと。

        実測（大きめの読めない画像）で、重い読み取りを3回走らせると **63秒**
        かかった。1枚あたりの上限は120秒なので、実名刺（1回15〜18秒）では
        打ち切りに達する。**下読みは軽い読み取り機だけ**で行い、そこで手応えが
        あったときにだけ本読みする。
        """
        import bcards.services.ocr as ocr

        heavy: list[str] = []

        def fake(image: Image.Image, provider_name=None) -> tuple[OcrOutput, dict]:
            if provider_name != ocr.PROBE_ENGINE:
                heavy.append(provider_name or "")
            return OcrOutput(provider="fake", api_version=None, text="蟹 麗"), parsed(last_name="蟹")

        monkeypatch.setattr(ocr, "_recognize_once", fake)

        ocr.recognize_card(Image.new("RGB", (1050, 640), "white"), provider_name="combined")

        assert len(heavy) == 1, f"重い読み取りが {len(heavy)} 回走っている"

    def test_a_readable_card_is_read_only_once(self, monkeypatch: pytest.MonkeyPatch):
        """横書きの名刺は遅くならない。ここが要。"""
        import bcards.services.ocr as ocr

        calls = []

        def fake(image: Image.Image, provider_name=None) -> tuple[OcrOutput, dict]:
            calls.append(image.size)
            return OcrOutput(provider="fake", api_version=None, text="読めた"), parsed(
                company_name="株式会社サンプル", email="taro@example.co.jp"
            )

        monkeypatch.setattr(ocr, "_recognize_once", fake)

        ocr.recognize_card(Image.new("RGB", (1050, 640), "white"), provider_name="combined")

        assert len(calls) == 1

    def test_the_original_is_kept_when_turning_does_not_help(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """回しても読めなければ、元の結果を返す。空にして帰らない。"""
        import bcards.services.ocr as ocr

        def fake(image: Image.Image, provider_name=None) -> tuple[OcrOutput, dict]:
            return OcrOutput(provider="fake", api_version=None, text="蟹 麗"), parsed(last_name="蟹")

        monkeypatch.setattr(ocr, "_recognize_once", fake)

        output, result = ocr.recognize_card(
            Image.new("RGB", (1050, 640), "white"), provider_name="combined"
        )

        assert result["fields"]["last_name"] == "蟹"
        assert output.text

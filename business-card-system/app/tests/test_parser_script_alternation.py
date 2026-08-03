"""漢字とカタカナが何度も入れ替わる行は氏名ではない（実テスト 17枚目）。

    印字      METEORISE（ロゴ）
    EasyOCR   小ケ戸テンク南ア三        ← ロゴの読み崩れ
    tesseract Shunsuke Katsumata

姓『小ケ』／ 名『戸テンク南ア三』になっていた。併用構成では両方のエンジンが
姓も名も埋めたため、埋まった数では決まらず、先の EasyOCR が採られた。

日本語の氏名で漢字とカタカナが入れ替わるのは1回まで（`ジョンソン裕子`）。
何度も入れ替わるのは読み崩れ。ひらがなは数えない（`山田はな子` は氏名）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import merge_fields, parse_fields  # noqa: E402
from bcards.services.ocr.parser import _looks_like_person_name  # noqa: E402


@pytest.mark.parametrize(
    "name", ["ジョンソン裕子", "山田はな子", "パトリシオバスケス", "舟木香織", "小ケ戸"]
)
def test_a_real_name_is_accepted(name: str):
    assert _looks_like_person_name(name)


@pytest.mark.parametrize("noise", ["小ケ戸テンク南ア三", "小ケ戸テンク南"])
def test_a_broken_reading_is_rejected(noise: str):
    assert not _looks_like_person_name(noise)


class TestTheMeteoriseCard:
    """実テスト 17枚目。姓『小ケ』／ 名『戸テンク南ア三』になっていた。"""

    EASYOCR = """小ケ戸テンク南ア三
Shunsuke Katsumata
Producer
Meteorise Inc:
VORTSuehiro-choIIZF6-14-3, Sotokanda
Chiyoda-Ku Tokyo 101-0021JnPAN
TEL 03-5817-4645 FAX03-5817-4644
hZmatter@meteorisecojp
https IIVw mereorise co Jpl"""
    TESSERACT = """Shunsuke Katsumata
Producer
Meteorise Inc.
VORT Suehiro-cho II 2F, 6-14-3, Sotokanda,
Chiyoda-ku, Tokyo 101-0021, JAPAN
TEL 03-5817-4645    FAX 03-5817-4644
k2matter@meteorise.co.jp
https://www.meteorise.co.jp/"""

    def fields(self) -> dict:
        parsed = [parse_fields(t.splitlines()) for t in (self.EASYOCR, self.TESSERACT)]
        return merge_fields(parsed)["fields"]

    def test_the_name_is_the_one_that_was_read(self):
        got = self.fields()

        assert got["last_name"] == "Katsumata"
        assert got["first_name"] == "Shunsuke"

    def test_the_other_fields_are_still_taken(self):
        got = self.fields()

        assert got["title"] == "Producer"
        assert got["tel"] == "03-5817-4645"
        assert got["fax"] == "03-5817-4644"

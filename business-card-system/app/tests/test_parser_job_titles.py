"""職種を表す語を役職として扱う（実テスト 16・18枚目）。

役職の語に無い職種は、行ごと氏名の候補になる。18枚目では

    印字   水引アーティスト        ← 職種
           舟　木　香　織          ← 氏名

で 姓『水引』／ 名『アーティスト』になっていた。氏名も正しく読めていたのに、
先に来た職種の行を採っていた。

16枚目は `シナリオライター/プランナー` が役職に入らず空欄だった。

`ディレクター` `プロデューサー` `コンサルタント` はすでに登録してある。
同じ種類の語を足す。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import merge_fields, parse_fields  # noqa: E402


@pytest.mark.parametrize(
    "line",
    ["水引アーティスト", "シナリオライター", "プランナー", "グラフィックデザイナー", "専門相談員"],
)
def test_a_job_title_does_not_become_the_name(line: str):
    got = parse_fields([line, "舟木 香織"])["fields"]

    assert got["last_name"] == "舟木"
    assert got["first_name"] == "香織"
    assert got["title"]


class TestTheKimusubiCard:
    """実テスト 18枚目。姓『水引』／ 名『アーティスト』になっていた。"""

    EASYOCR = """亨
kimusubi
水引アーティスト
Nlizuliiki irtist
舟 木 香 織
Kuori Funaki
080-3419-6077
info@kimusubitokyo
kimusubitokyo 喜結kimusubi
@Kaorillizuhiki kimusubi"""
    TESSERACT = """)
kimusubi
水引 アー ティ スト
Mizuhiki Artist
舟　木　香　織
Kaori Funaki
080-3419-6077
info@kimusubi.tokyo
個 kimusubitokyo"""

    def fields(self) -> dict:
        parsed = [parse_fields(t.splitlines()) for t in (self.EASYOCR, self.TESSERACT)]
        return merge_fields(parsed)["fields"]

    def test_the_person_is_the_name(self):
        got = self.fields()

        assert got["last_name"] == "舟木"
        assert got["first_name"] == "香織"

    def test_the_company_has_no_leading_rubbish(self):
        """社名はメールのドメインとの一致で見つける。一致に効いていない
        先頭の塊（アイコンの読み崩れ）は落とす。"""
        assert self.fields()["company_name"] == "kimusubi"

    def test_the_other_fields_are_still_taken(self):
        got = self.fields()

        assert got["mobile"] == "080-3419-6077"
        assert got["email"] == "info@kimusubi.tokyo"


class TestTheScenarioWriterCard:
    """実テスト 16枚目。役職が空欄だった。"""

    EASYOCR = """シナリオライターノプランナー
竹廣　乃葉
Noba Takehiro
〒900-0005 沖縄県那覇市天久2-8-28#303
MOBILE: 070-6554-4516
E-MAIL; noba-takehiro@gmailcom"""
    TESSERACT = """シナ リオ ライ ター/ プ ラン ナー
一
Ve 乃 葉
Noba Takehiro
900-0005 沖縄 県 那覇 市 天久 2-8-28#303
MOBILE: 070-6554-4516
E-MAIL: noba.takehiro@gmailcom"""

    def fields(self) -> dict:
        parsed = [parse_fields(t.splitlines()) for t in (self.EASYOCR, self.TESSERACT)]
        return merge_fields(parsed)["fields"]

    def test_the_role_is_taken(self):
        assert self.fields()["title"]

    def test_the_name_is_unchanged(self):
        got = self.fields()

        assert got["last_name"] == "竹廣"
        assert got["first_name"] == "乃葉"

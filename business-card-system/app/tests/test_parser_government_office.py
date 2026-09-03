"""官公庁の組織名と部署を分ける（実テスト 18枚目）。

    印字   沖縄労働局 職業安定部
           需給調整事業室

    出力   会社名 空欄  ／  部署『沖縄労働局職業安定部』

`局` を部署の語に入れてあるため、行まるごとが部署になり、**組織名の欄が
空**になっていた。会社の名刺なら `株式会社サンプル 営業本部` は
会社名『株式会社サンプル』・部署『営業本部』に分かれるので、官公庁でも
同じように分かれるべき。

`局` `庁` `署` `省` は組織の名前の終わりを示す。**空白のうしろに部署の語が
続いていれば、そこが切れ目**。

    沖縄労働局 職業安定部
        ↑ 組織    ↑ 部署

空白が無い（`沖縄労働局` だけ）なら組織名。うしろが部署の語でなければ、
これまでどおり触らない。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402

CARD = [
    "沖縄労働局 職業安定部",
    "霧給調整事業室",
    "霧給調整事業専門相談員",
    "迎 亮一",
    "テ900-0006 沖縄県那覇市おもろまち2丁目1番1号",
    "E-mail mukai-ryouichipm3@mhlygojp",
]


class TestTheLabourBureauCard:
    def test_the_organisation_goes_to_the_company_field(self):
        got = parse_fields(CARD)["fields"]

        assert got["company_name"] == "沖縄労働局"

    def test_the_department_keeps_only_the_department(self):
        got = parse_fields(CARD)["fields"]

        assert got["department_name"].startswith("職業安定部")
        assert "沖縄労働局" not in got["department_name"]

    def test_the_name_is_untouched(self):
        got = parse_fields(CARD)["fields"]

        assert (got["last_name"], got["first_name"]) == ("迎", "亮一")


class TestOtherGovernmentOffices:
    @pytest.mark.parametrize(
        ("line", "company", "department"),
        [
            ("東京労働局 労働基準部", "東京労働局", "労働基準部"),
            ("国税庁 課税部", "国税庁", "課税部"),
            ("千代田税務署 総務課", "千代田税務署", "総務課"),
        ],
    )
    def test_the_line_is_split(self, line: str, company: str, department: str):
        got = parse_fields([line, "山田 太郎"])["fields"]

        assert got["company_name"] == company
        assert got["department_name"] == department


class TestNothingElseChanges:
    def test_an_organisation_without_a_department_is_the_company(self):
        got = parse_fields(["沖縄労働局", "山田 太郎"])["fields"]

        assert got["company_name"] == "沖縄労働局"

    def test_a_company_card_is_untouched(self):
        got = parse_fields(["株式会社サンプル", "営業本部 第一営業部", "山田 太郎"])["fields"]

        assert got["company_name"] == "株式会社サンプル"
        assert got["department_name"] == "営業本部第一営業部"

    def test_a_department_word_alone_is_still_a_department(self):
        got = parse_fields(["株式会社サンプル", "情報システム室", "山田 太郎"])["fields"]

        assert got["department_name"] == "情報システム室"

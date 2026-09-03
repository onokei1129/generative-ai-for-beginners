"""日本の番号が国際表記で印字されている場合（実テスト 9枚目・Causal Foundry）。

名刺には `+81-70-1508-9897` と印字されている。同じ番号だが、利用者が
正解として入力したのは `070-1508-9897` だった。

種別の判定（携帯か電話か）は既に `domestic_digits` で国内表記に直してから
見ているので正しく携帯に入る。直っていないのは**保存する値のほう**で、
`+81-70-1508-9897` のまま入っていた。

`+81` は「日本国内では 0 に読み替える」という表記なので、国内表記へ直す。
印字されている区切り（ハイフン・空白）はそのまま残す。

**他国の番号は直さない。** 国番号を落として 0 を付ける規則は日本のもので、
韓国の `+82-10-3661-0778`（実テスト 8枚目）に当てはめると別の番号になる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheCausalFoundryCard:
    def test_the_mobile_number_is_domestic(self):
        got = parse_fields(["yuko@causalfoundry.ai", "+81-70-1508-9897"])["fields"]

        assert got["mobile"] == "070-1508-9897"


class TestTheDomesticForm:
    @pytest.mark.parametrize(
        ("printed", "want"),
        [
            ("+81-70-1508-9897", "070-1508-9897"),
            ("+81 90-1234-5678", "090-1234-5678"),
            ("+81-3-1234-5678", "03-1234-5678"),
            ("+81 3 1234 5678", "03 1234 5678"),
            ("+81(0)90-1234-5678", "090-1234-5678"),
            ("+81 (0) 90-1234-5678", "090-1234-5678"),
        ],
    )
    def test_it_is_rewritten(self, printed: str, want: str):
        got = parse_fields([f"TEL {printed}"])["fields"]

        assert (got["tel"] or got["mobile"]) == want

    def test_a_number_already_domestic_is_untouched(self):
        assert parse_fields(["TEL 03-1234-5678"])["fields"]["tel"] == "03-1234-5678"


class TestForeignNumbersAreLeftAlone:
    @pytest.mark.parametrize(
        "printed",
        ["+82.10.3661.0778", "+82-2-6421-7777", "+1-415-555-0100", "+44 20 7946 0958"],
    )
    def test_they_keep_their_country_code(self, printed: str):
        got = parse_fields([f"TEL {printed}"])["fields"]

        assert (got["tel"] or got["mobile"]) == printed

    def test_the_nexon_card_is_unchanged(self):
        """実テスト 8枚目（韓国）。`+82.10…` を `010…` にしてはいけない。"""
        got = parse_fields([
            "Team 1                             C +82.10.3661.0778",
            "Team Member                        E eonlee@nexongames.co.kr",
        ])["fields"]

        assert got["mobile"] == "+82.10.3661.0778"

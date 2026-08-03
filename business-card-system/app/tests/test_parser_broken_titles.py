"""読み崩れた役職を氏名にしない（実テスト 28・30枚目）。

2枚で同じことが起きた。

    30枚目  印字 代表取締役    →  姓『代表』名『取締彼』
    28枚目  印字 執行役員      →  姓『勢行』名『役員』

`代表取締役` はそのままなら役職の語に一致するので氏名にならない。しかし
**1文字でも崩れると一致しなくなり**、漢字2文字＋漢字3文字の並びが氏名の
形に見えるため、そのまま姓と名になる。

読み崩れる語をすべて数え上げることはできない。**崩れにくい部品のほう**を
見る。`役員`・`代表`・`取締`・`常務`・`専務` は氏名にはまず現れない。

`執行` は姓として実在するため入れない（同じ行の `役員` で止まる）。

空欄になるだけなら入力する人が気づく。誤った氏名は気づかれずに登録される。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import _looks_like_person_name, parse_fields  # noqa: E402


class TestTheHinataCard:
    """実テスト 30枚目。印字は `代表取締役`。"""

    def test_the_broken_title_is_not_a_name(self):
        got = parse_fields(["HINATA株式会社", "代表 取締彼", "kawamura@hinata3.co.jp"])["fields"]

        assert got["last_name"] != "代表"
        assert got["first_name"] != "取締彼"


class TestTheDelightWorksCard:
    """実テスト 28枚目。印字は `執行役員`。"""

    def test_the_broken_title_is_not_a_name(self):
        got = parse_fields(["ディライトワークス株式会社", "勢行 役員", "〒153-0042"])["fields"]

        assert got["last_name"] != "勢行"
        assert got["first_name"] != "役員"


class TestPartsOfTitlesAreNotNames:
    @pytest.mark.parametrize(
        "line",
        [
            "代表 取締彼",
            "勢行 役員",
            "執行 役員",
            "常務 取締彼",
            "専務 取締役",
            "監査 役員",
        ],
    )
    def test_the_line_is_rejected(self, line: str):
        assert not _looks_like_person_name(line)


class TestRealNamesStillWork:
    @pytest.mark.parametrize(
        ("line", "last", "first"),
        [
            ("辰田 光章", "辰田", "光章"),
            ("河村 直哉", "河村", "直哉"),
            ("高橋 佳広", "高橋", "佳広"),
            ("山田 太郎", "山田", "太郎"),
            ("舟木 香織", "舟木", "香織"),
        ],
    )
    def test_the_name_is_taken(self, line: str, last: str, first: str):
        got = parse_fields(["株式会社サンプル", line])["fields"]

        assert (got["last_name"], got["first_name"]) == (last, first)

    def test_the_title_itself_is_still_a_title(self):
        """正しく読めた役職は、これまでどおり役職に入る。"""
        got = parse_fields(["株式会社サンプル", "代表取締役 山田 太郎"])["fields"]

        assert got["title"] == "代表取締役"
        assert (got["last_name"], got["first_name"]) == ("山田", "太郎")

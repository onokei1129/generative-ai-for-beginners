"""氏名が2行に分かれて印字されている場合（実テスト 10枚目・VK）。

大きな活字の名刺では、姓と名が別々の行になる。

    German
    Kurnikov
    Game Business Development

以前は「1行1語では氏名と判断できない」として見送っていた。実テストで
氏名が空のまま残るため、条件を絞って拾う。

## 誤って社名を氏名にしないための条件

社名も1語ずつ2行になることがある。次を全部満たすときだけ氏名とする。

- 他のどの規則でも氏名が取れていない
- 続いた2行が、それぞれ**英字1語**
- 先頭が大文字で、**残りは小文字**（`German`）。社名に多い全大文字
  （`ACME` `SOLUTIONS`）は外す
- どちらも会社を示す語（Inc. Ltd. など）を含まない
- どちらも「氏名ではない語」（office・business・japan など）でない
- 名刺の**上のほう**にある（氏名は上部に印字される）

**残る危険**は `Acme` `Solutions` のように、大文字小文字の形が氏名と同じ
社名です。これは形だけでは見分けられません。空欄より誤った氏名のほうが
気づかれにくいので、条件を緩めるときは実データで確かめること。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheVkCard:
    """実テスト 10枚目。"""

    LINES = [
        "German",
        "Kurnikov",
        "Game Business Development",
        "+7 916 737-23-13",
        "g.kurnikov@vkteam.ru",
        "125167, Moscow,",
        "Leningradsky prospekt 39, bld. 79",
    ]

    def test_the_name_is_taken(self):
        got = parse_fields(self.LINES)["fields"]

        assert (got["last_name"], got["first_name"]) == ("Kurnikov", "German")

    def test_the_other_fields_are_unaffected(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["email"] == "g.kurnikov@vkteam.ru"
        assert got["postal_code"] == "125167"


class TestWhatMustNotBecomeAName:
    @pytest.mark.parametrize(
        ("first", "second"),
        [
            ("ACME", "SOLUTIONS"),          # 全大文字は社名の形
            ("Acme", "Inc."),               # 会社を示す語
            ("Head", "Office"),             # 氏名ではない語
            ("Business", "Development"),    # 同上
            ("Tokyo", "Japan"),             # 国・地域の語
            ("German", "737-23-13"),        # 数字を含む
        ],
    )
    def test_the_pair_is_rejected(self, first: str, second: str):
        got = parse_fields([first, second, "info@example.com"])["fields"]

        assert not got["last_name"] and not got["first_name"]

    def test_a_name_on_one_line_still_wins(self):
        """1行で読めているなら、そちらを使う。"""
        got = parse_fields(["Acme", "Solutions", "German Kurnikov"])["fields"]

        assert (got["last_name"], got["first_name"]) == ("Kurnikov", "German")

    def test_lines_far_down_the_card_are_ignored(self):
        """氏名は上部に印字される。下のほうの2語は拾わない。"""
        lines = ["ACME CORP", "info@example.com", "TEL 03-1234-5678"]
        lines += ["Sales", "Office", "Building", "Alpha", "Beta"]

        got = parse_fields(lines)["fields"]

        assert not got["last_name"] and not got["first_name"]

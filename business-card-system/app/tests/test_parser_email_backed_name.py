"""メールアドレスが裏づけるラテン文字の氏名を優先する（実テスト 4・7枚目）。

日本語の名刺では氏名も日本語で印字されるので、日本語の候補を英字より先に
採っている。しかし**日本語が読み崩れて英字のほうが正しい**名刺がある。

    4枚目  印字 `ANA FERNÁNDEZ DEL RÍO`   出力 姓『心万』名『心』
    7枚目  印字 `Sangeon Lee`             出力 姓『巨』名『メロ』

どちらも紙の汚れや罫線が漢字・カタカナとして読まれ、それが氏名になった。
形だけでは、読み崩れた断片と本物の日本語の氏名を見分けられない。

**メールアドレスが裏づけになる。**

    ana@causalfoundry.ai        ← `ANA`
    eonlee@nexongames.co.kr     ← `Lee`

英字の候補の語がメールの`@`より前に現れ、日本語の候補には裏づけが無い
なら、英字のほうを採る。裏づけがどちらにも無い名刺は、これまでどおり
日本語を先に採る。

降ろすのは**3文字以下**の候補だけにする。`パトリシオ　バスケス` は
`Patricio Vásquez` の音写で、`patricio@aonegames.com` はラテン文字の側しか
裏づけられない（かなとラテン文字は文字が違うため）。長い候補まで降ろすと、
日本語で印字された氏名を捨ててしまう。

`ceo@` `info@` のような役職・部署のアドレスは裏づけにならないので、
そういう名刺（3枚目 `ceo@omorobot.com`）はこの規則では直らない。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402


class TestTheAnaCard:
    """実テスト 4枚目。英字だけの名刺に、汚れが漢字として混ざった。"""

    LINES = [
        "心万",
        "心",
        "ANA FERNÁNDEZ DEL RÍO",
        "Principal Data Scientist",
        "ana@causalfoundry.ai",
    ]

    def test_the_latin_name_is_taken(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["last_name"] != "心万"
        assert "ANA" in f"{got['last_name']}{got['first_name']}".upper()

    def test_the_title_is_untouched(self):
        assert parse_fields(self.LINES)["fields"]["title"] == "Principal Data Scientist"


class TestTheNexonCard:
    """実テスト 7枚目。"""

    LINES = [
        "巨   メロ",
        "NEXON GAMES",
        "Sangeon Lee",
        "Planning & Coordination Dept",
        "eonlee@nexongames.co.kr",
    ]

    def test_the_latin_name_is_taken(self):
        got = parse_fields(self.LINES)["fields"]

        assert (got["last_name"], got["first_name"]) == ("Lee", "Sangeon")


class TestJapaneseStillComesFirst:
    def test_a_japanese_name_without_email_support_still_wins(self):
        """裏づけがどちらにも無ければ、これまでどおり日本語を先に採る。"""
        got = parse_fields([
            "株式会社サンプル",
            "山田 太郎",
            "Taro Yamada",
            "info@example.co.jp",
        ])["fields"]

        assert (got["last_name"], got["first_name"]) == ("山田", "太郎")

    def test_a_transliterated_katakana_name_is_kept(self):
        """`パトリシオ　バスケス` は `Patricio Vásquez` の音写。捨てない。"""
        got = parse_fields([
            "パトリシオ　バスケス",
            "Patricio Vásquez",
            "patricio@aonegames.com",
        ])["fields"]

        assert (got["last_name"], got["first_name"]) == ("パトリシオ", "バスケス")

    def test_a_japanese_name_backed_by_the_email_wins(self):
        """日本語の側にも裏づけがあれば日本語（ローマ字の姓が入る名刺）。"""
        got = parse_fields([
            "株式会社サンプル",
            "長谷川 幸子",
            "sachiko.hasegawa@gree.net",
        ])["fields"]

        assert (got["last_name"], got["first_name"]) == ("長谷川", "幸子")

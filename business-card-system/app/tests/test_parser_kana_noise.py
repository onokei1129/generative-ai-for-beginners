"""読み崩れたかなを氏名にしない（実テスト 10枚目）。

ロシアの名刺（German Kurnikov）で、氏名が 姓『にロニ』名『エニ』になった。

    印字  German Kurnikov
    読み  に ロニ エニ        ← 飾りが、かなとして読まれたもの

かなの氏名は外国名の音写なので**カタカナで印字される**（`ユン ソクン`
`パトリシオ バスケス`）。ひらがなが混じっているものは読み崩れであって
氏名ではない。ひらがなだけの行は、ふりがなとして別に扱っている。

空欄なら入力する人が気づくが、それらしい誤りは気づかれずに保存される。
ここで守るのは「入れないこと」であって、正しい氏名を当てることではない。
この名刺の `German Kurnikov` は2行に分かれて読まれており（`@ German` と
`Kurnikov`）、1行1語では氏名と判断できないため空欄のままになる。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr import parse_fields  # noqa: E402
from bcards.services.ocr.parser import _looks_like_person_name  # noqa: E402


class TestKanaMixedWithHiraganaIsNotAName:
    def test_the_broken_reading_is_rejected(self):
        assert not _looks_like_person_name("にロニエニ")

    def test_a_katakana_name_is_still_accepted(self):
        assert _looks_like_person_name("ユンソクン")
        assert _looks_like_person_name("パトリシオバスケス")

    def test_a_katakana_name_with_a_long_vowel_is_still_accepted(self):
        assert _looks_like_person_name("ジョーンズ")

    def test_a_name_holding_kanji_is_untouched(self):
        """漢字が入っていれば、かなの規則は関係しない（`山田はな子`）。"""
        assert _looks_like_person_name("山田はな子")


class TestTheRussianCard:
    """実テスト 10枚目。姓『にロニ』名『エニ』になっていた。"""

    OCR = """@   German
Kurnikov
Game Business Development
BREE.   +7 916 737-23-13
ee BO   g.kurnikov@vkteam.ru
ee   rustore.ru/en
に ロニ エニ
pa ES 13   125167, Moscow,
=:   スー   Leningradsky prospekt 39, bld. 79"""

    def fields(self) -> dict:
        return parse_fields(self.OCR.splitlines())["fields"]

    def test_the_broken_reading_does_not_become_the_name(self):
        got = self.fields()
        assert got["last_name"] != "にロニ"
        assert got["first_name"] != "エニ"

    def test_the_name_split_over_two_lines_is_assembled(self):
        """以前はここを空欄が正解としていた。

        `German` と `Kurnikov` は別々の行にあり、1行を氏名として見る規則では
        拾えないため「読めていない以上、作れない」としていた。実テストで
        氏名が空のまま残るという報告を受け、続いた2行から組み立てるように
        した（tests/test_parser_name_over_two_lines.py）。
        """
        got = self.fields()
        assert (got["last_name"], got["first_name"]) == ("Kurnikov", "German")

    def test_the_fields_that_were_read_are_still_taken(self):
        got = self.fields()
        assert got["email"] == "g.kurnikov@vkteam.ru"
        assert got["tel"] == "+7 916 737-23-13"

    def test_the_role_line_does_not_become_the_name(self):
        """`Game Business Development` を 姓『Business Development』名
        『Game』として登録していた（この修正の途中で作った不具合）。"""
        got = self.fields()
        assert got["last_name"] != "Business Development"
        assert got["first_name"] != "Game"

"""漢字だけの長い行を氏名にしない（実テスト 19枚目・沖縄労働局）。

    印字        需給調整事業専門相談員
                迎　　亮一

    tesseract   需給 調整 事業 専門 相談      ← 末尾の「員」が落ちる
                （`迎 亮一` の行はそもそも読めていない）

    出力        姓『需給調整事業』／名『専門相談』

職名が氏名の欄に入っていた。「員」が読めていれば役職の語尾
（`TITLE_TAIL_WORDS`）で弾けたが、**1文字落ちただけで**氏名になる。

語で見分けようとすると、職名の語彙を数え上げることになって切りがない。
長さで断てる。日本語の氏名の上限は12文字にしてあるが、これはかなで書く
外国名（`オロブスキー スタニスラフ`）に合わせたもの。漢字の氏名はそこまで
長くならない——姓は最長でも5文字（`勘解由小路` `左衛門三郎`）、実際に多いのは
4文字まで（`小比類巻` `勅使河原`）で、名を足しても8文字を超えない。

**姓が6文字の日本人はいない。** 空いていた4文字ぶんに職名が入っていた。

かなを1文字でも含む行にはこの上限を掛けない（音写の氏名を巻き添えに
しないため）。

なお、この名刺は氏名の行そのものが読めていないので、直したあとも氏名は
正しくならない。**それらしい誤りが黄色い欄に入るより、空欄か明らかな
読み崩れのほうがよい**（入力する人が気づける）。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import (  # noqa: E402
    MAX_KANJI_NAME,
    _looks_like_person_name,
    parse_fields,
)


class TestTheOkinawaLabourBureauCard:
    """実テスト19枚目の読み取りをそのまま流す。"""

    LINES = [
        "6 う   Ry EIR HA",
        "ひと、 くらし、    電 給 調 EE",
        "みらい の た め に",
        "需給 調整 事業 専門 相談",
        "た",
        "クロ",
        "〒900-0006 沖縄 市 お も ろ ま ち 2 丁 目 1 番 1 号",
        "那 第 2 地方 合同 庁舎 1 号館 3",
        "©",
        "E-mail : mukai-ryouichipm3@mhlw.go.jp",
    ]

    def test_the_job_title_is_not_the_name(self):
        got = parse_fields(self.LINES)["fields"]

        assert got["last_name"] != "需給調整事業"
        assert got["first_name"] != "専門相談"

    def test_the_rest_of_the_card_still_comes_out(self):
        """氏名を退けたはずみで、取れていた項目を落とさない。"""
        got = parse_fields(self.LINES)["fields"]

        assert got["postal_code"] == "900-0006"
        assert got["email"] == "mukai-ryouichipm3@mhlw.go.jp"
        assert "おもろまち" in got["address"]


class TestTheLimitOnKanjiNames:
    def test_a_job_title_of_ten_kanji_is_not_a_name(self):
        assert not _looks_like_person_name("需給調整事業専門相談")

    def test_ordinary_names_are_untouched(self):
        for name in ("迎亮一", "佐々木健", "山田太郎", "高岡徹", "小比類巻真一"):
            assert _looks_like_person_name(name), name

    def test_the_longest_real_surname_plus_a_given_name_still_passes(self):
        """`勘解由小路`（5文字）＋名。上限はここを割り込まない。"""
        assert len("勘解由小路義郎") <= MAX_KANJI_NAME
        assert _looks_like_person_name("勘解由小路義郎")

    def test_kana_names_keep_the_longer_limit(self):
        """かなを含む行には掛けない。8文字を超えても氏名のまま。"""
        for name in ("オロブスキースタニスラフ", "パトリシオバスケス"):
            assert len(name) > MAX_KANJI_NAME, name
            assert _looks_like_person_name(name), name

    def test_a_short_mixed_name_is_untouched(self):
        assert _looks_like_person_name("ジョンソン裕子")

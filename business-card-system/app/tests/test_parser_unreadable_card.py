"""何も読めなかった名刺から氏名を作らない（実テスト 22枚目・縦書き）。

縦書きの名刺は、どちらの読み取り機も文字として意味のあるものを1つも
取れない。読み取りはこうだった。

    夢 / 蟹   麗 / 喜 / 川 1 / 昌 / 昌   亀 / 量 / 喜 麗 / 畳

それでも 姓『蟹』名『麗』が出ていた。1文字＋1文字の並びが氏名の形に
見えるためで、絵柄や罫線の読み崩れは**いくらでもこの形になる**。

**空欄なら入力する人が気づく。誤った氏名は気づかれずに登録される。**

見分けの手がかりは「ほかに何も取れていない」こと。メール・電話・郵便番号・
会社名——どれか1つでも取れていれば、その名刺は読めている。何も無いのに
1文字＋1文字だけが取れているなら、それは読めたのではなく形が似ただけ。

`伊 藤`＋`しの`（別の実データ）は姓が1文字ずつに割れた例だが、そちらは
同じ名刺から住所も電話も取れているので、ここには当たらない。

縦書きそのものは、この直しでは読めるようにならない。画像を回して読み直す
必要があり、別の手当てになる。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr.parser import parse_fields  # noqa: E402

NOISE = ["夢", "蟹   麗", "喜", "川 1", "昌", "昌   亀", "量", "喜 麗", "畳"]


class TestNothingIsInvented:
    def test_no_name_comes_out_of_noise(self):
        got = parse_fields(NOISE)["fields"]

        assert got["last_name"] == ""
        assert got["first_name"] == ""

    def test_the_read_text_is_still_kept(self):
        """読めた文字そのものは残す。手入力の手がかりになる。"""
        assert parse_fields(NOISE)["fields"]["note"]


class TestARealCardIsUntouched:
    def test_a_single_character_name_survives_when_the_card_is_readable(self):
        """ほかの項目が取れていれば、1文字＋1文字でも残す。"""
        got = parse_fields([
            "株式会社サンプル",
            "森 蘭",
            "〒100-0001 東京都千代田区1-1-1",
            "TEL 03-1234-5678",
        ])["fields"]

        assert (got["last_name"], got["first_name"]) == ("森", "蘭")

    def test_a_normal_name_is_untouched(self):
        got = parse_fields(["株式会社サンプル", "山田 太郎"])["fields"]

        assert (got["last_name"], got["first_name"]) == ("山田", "太郎")

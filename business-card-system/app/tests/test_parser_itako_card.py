"""実テスト34枚目（ITAKO）の読み取りから見つかった4件（services/ocr/）。

この1枚の読み取り結果は次のとおりだった。**同じ名刺を、2つのエンジンが
まったく違うふうに読んでいる。**

    --- easyocr ---            --- tesseract ---
    株式会社IAKO                株 式 会 社 ITAKO
    代千取橋役                   代表 取締 役
    河野修弘                    河野 修 弘
    (03)6313-7095              TEL (03) 6313-7096
                               東京 者 新宿 区 新宿 3-3-23
                               http://www itakoh.cojo/

併合は項目ごとに「先に値があるほう」を採り、姓名はまとめて「埋まった数の
多いほう、同数なら先のエンジン」で採る。EasyOCR が先に並んでいるため、
**両方が読めている項目では EasyOCR が勝つ**。そのため崩れた `代千取橋役` が、
正しく読めていた `河野 修 弘` を押しのけていた。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import merge_fields  # noqa: E402
from bcards.services.ocr.parser import parse_fields  # noqa: E402

EASYOCR = [
    "ITAKo", "株式会社IAKO", "代千取橋役", "河野修弘",
    "ncbunioronomiukoho", "IGO", "323", "Cm", "(03)6313-7095", "Ioc0",
]
TESSERACT = [
    "株 式 会 社 ITAKO", "代表 取締 役", "河野 修 弘   é",
    "Nobuhiro. kono@iitakoh.co.jp   <", "〒160-0023",
    "東京 者 新宿 区 新宿 3-3-23   1   a", "ファ ミー ル 新宿 004   /   )",
    "TEL (03) 6313-7096", "http://www itakoh.cojo/",
]


def _merged() -> dict:
    return merge_fields([parse_fields(EASYOCR), parse_fields(TESSERACT)])["fields"]


class TestTheTitleIsNotTakenForAName:
    def test_the_real_name_survives(self):
        """`代千取橋役` を弾けば、正しく読めていたほうが残る。"""
        got = _merged()

        assert (got["last_name"], got["first_name"]) == ("河野", "修弘")

    def test_a_broken_title_is_not_a_name(self):
        from bcards.services.ocr.parser import _looks_like_person_name

        assert not _looks_like_person_name("代千取橋役")
        assert not _looks_like_person_name("代表取締役")

    def test_only_the_tail_is_judged(self):
        """`役` は**末尾のときだけ**弾く。

        `役所`（役所広司）のように先頭に来る姓が実在するので、どこでも弾くと
        本物の氏名を巻き添えにする。この規則は末尾しか見ない。

        なお `役所 広司` 自体は、この規則より前に `COMPANY_KEYWORDS` の
        『役所』『市役所』で落ちる（以前からの動き。ここでは変えていない）。
        """
        from bcards.services.ocr.parser import _looks_like_person_name

        assert _looks_like_person_name("役川 広司"), "先頭の『役』で弾いてはいけない"
        assert not _looks_like_person_name("山田 監査役")


class TestThePhoneInParentheses:
    """`TEL (03) 6313-7096` が空欄になっていた。頭に `(` が付くだけで外れる。"""

    def test_it_is_picked_up(self):
        got = parse_fields(TESSERACT)["fields"]

        assert "6313-7096" in got["tel"]

    def test_the_plain_form_still_works(self):
        got = parse_fields(["山田 太郎", "株式会社サンプル", "TEL 03-6313-7096"])["fields"]

        assert got["tel"] == "03-6313-7096"

    def test_fax_in_parentheses_too(self):
        got = parse_fields(["山田 太郎", "株式会社サンプル", "FAX (03) 6313-7097"])["fields"]

        assert "6313-7097" in got["fax"]


class TestTheUrlNeedsAHost:
    """`http://www itakoh.cojo/` が空白で切れ、`http://www` が入っていた。"""

    def test_a_hostless_fragment_is_dropped(self):
        assert _merged()["url"] == ""

    def test_real_urls_are_kept(self):
        for line in ("http://www.itakoh.co.jp/", "www.donuts.ne.jp", "https://jda.example"):
            got = parse_fields(["山田 太郎", "株式会社サンプル", line])["fields"]

            assert got["url"], f"{line} が落ちている"


class TestTheMisreadPrefecture:
    """`東京都新宿区` が `東京者新宿区` と読まれていた。"""

    def test_it_is_repaired(self):
        assert _merged()["address"].startswith("東京都新宿区")


class TestWhatIsStillWrong:
    """直せていないものを、消えないように書き留めておく。

    どちらも **EasyOCR が1文字を落として（読み違えて）いる**もので、形の
    検査では正誤を見分けられない。併合は先のエンジンを採るので、そのまま
    残る。1枚の標本で併合の順を変えると、他の名刺を壊す側に回る。
    """

    def test_the_company_name_still_loses_a_letter(self):
        # 印字は ITAKO。tesseract は正しく読めているが、EasyOCR の IAKO が勝つ。
        assert _merged()["company_name"] == "株式会社IAKO"

    def test_the_phone_keeps_the_misread_digit(self):
        # 印字は 6313-7096。EasyOCR は 7095 と読んでいる。桁数も形も正しいので
        # 見分けられない。
        assert "7095" in _merged()["tel"]

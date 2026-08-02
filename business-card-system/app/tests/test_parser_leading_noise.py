"""行頭に付いたOCRのノイズ（実テスト 10枚目・11枚目）。

ロゴやアイコンは短い記号として読まれ、その行の**先頭**に付く。末尾の
ノイズは `trim_ocr_noise` が落としていたが、あれは日本語を含む行だけを
見るため、英字だけの行には効かない。

11枚目（Edge Creators）では、これで社名が空になっていた。

    読み  x) Edge Creators
    メール sakamoto@edgecre.co.jp

社名はメールのドメイン `edgecre` との前方一致で見つける作りになっている
（`edgecre` ← `Edge Creators`）。ところが照合に使う文字列が行頭の `x` を
含んで `xedgecreators` になるため、一致しない。

`Edge` のような**記号を含まない4文字の語**を落としてはいけない。落とすと
社名そのものが消える。落とすのは記号を含む短い塊だけに限る。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr import parse_fields  # noqa: E402
from bcards.services.ocr.parser import strip_leading_noise  # noqa: E402


class TestWhatCountsAsLeadingNoise:
    def test_a_symbol_with_no_letters_is_noise(self):
        assert strip_leading_noise("@   German") == "German"

    def test_a_short_token_holding_a_symbol_is_noise(self):
        assert strip_leading_noise("x) Edge Creators") == "Edge Creators"

    def test_a_short_word_without_a_symbol_is_kept(self):
        """`Edge` を落とすと社名そのものが消える。"""
        assert strip_leading_noise("Edge Creators") == "Edge Creators"

    def test_a_longer_token_holding_a_symbol_is_kept(self):
        """`e-mail:` のようなラベルまで落とすと、行の意味が変わる。"""
        assert strip_leading_noise("e-mail: sakamoto@edgecre.co.jp").startswith("e-mail:")

    def test_only_the_leading_token_is_touched(self):
        assert strip_leading_noise("Edge Creators (x)") == "Edge Creators (x)"

    def test_a_line_that_is_only_noise_becomes_empty(self):
        assert strip_leading_noise("=:") == ""


class TestTheEdgeCreatorsCard:
    """実テスト 11枚目。社名が空になっていた。"""

    OCR = """x) Edge Creators
代表 取締 役 社長
坂本 EBS
を
mobile: 090-6596-0349   る 。
e-mail: sakamoto@edgecre.co.jp   2
ro,
の"""

    def fields(self) -> dict:
        return parse_fields(self.OCR.splitlines())["fields"]

    def test_the_company_is_found_through_the_email_domain(self):
        assert self.fields()["company_name"] == "Edge Creators"

    def test_the_company_does_not_become_the_person_name(self):
        """社名を氏名として登録すると、姓『Edge』名『Creators』になる。"""
        got = self.fields()
        assert got["last_name"] != "Edge"
        assert got["first_name"] != "Creators"

    def test_the_other_fields_still_come_out(self):
        got = self.fields()
        assert got["title"] == "代表取締役社長"
        assert got["mobile"] == "090-6596-0349"
        assert got["email"] == "sakamoto@edgecre.co.jp"

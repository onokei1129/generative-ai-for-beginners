"""郵便番号と電話番号の取り違え（services/ocr/parser.py）。

実データ（韓国の方の名刺）で、7項目のうち3項目しか取れず、うち2項目は
誤った値が入っていた。

    郵便番号  `070-9385`   ← 携帯番号 `070-9385-4004` の前半
    住所      `-4004`      ← その残り
    電話      （空）        ← `Tel 050-3110-2873` を携帯として扱い、
                             先に入っていた携帯に押し出されて消えた
    携帯      （空→誤り）   `HP` を携帯のラベルとして知らなかった
    住所      `Add 〒…`    住所のラベルを値に含めていた

正しい値が入ることと、日本語の名刺を壊していないことを対で置く。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import POSTAL_RE, find_labels, parse_fields  # noqa: E402

# 実データのOCR結果に相当する行
KOREAN_CARD = [
    "代表取締役",
    "ユン ソクン",
    "SEOKHOON YOON",
    "HP 070-9385-4004",
    "Tel 050-3110-2873",
    "E-mail ceo@omorobot.com",
    "Add 〒580-0021 大阪府松原市高見の里六丁目7-18",
]


def fields(*lines: str) -> dict:
    return parse_fields(list(lines))["fields"]


class TestPostalIsNotPartOfAPhoneNumber:
    @pytest.mark.parametrize(
        "line",
        [
            "HP 070-9385-4004",
            "Tel 050-3110-2873",
            "TEL 03-1234-5678",
            "携帯 090-1234-5678",
            "0120-123-4567",
        ],
    )
    def test_phone_numbers_are_not_read_as_a_postal_code(self, line: str):
        """電話番号の中の「3桁-4桁」を郵便番号にしないこと。"""
        assert POSTAL_RE.search(line) is None, f"{line} を郵便番号として拾っている"

        got = fields(line)
        assert got["postal_code"] == ""
        assert got["address"] == ""

    @pytest.mark.parametrize(
        "line",
        [
            "〒100-0001 東京都千代田区千代田1-1-1",
            "T100-0001 東京都千代田区千代田1-1-1",
            "7100-0001 東京都千代田区千代田1-1-1",
            "100-0001 東京都千代田区千代田1-1-1",
        ],
    )
    def test_postal_codes_are_still_read(self, line: str):
        """〒の読み違えを含め、郵便番号は従来どおり拾うこと。"""
        got = fields(line)

        assert got["postal_code"] == "100-0001"
        assert got["address"].replace(" ", "") == "東京都千代田区千代田1-1-1"

    def test_a_card_with_both_keeps_them_apart(self):
        got = fields(*KOREAN_CARD)

        assert got["postal_code"] == "580-0021"
        assert got["address"] == "大阪府松原市高見の里六丁目7-18"


class TestHandphoneLabel:
    @pytest.mark.parametrize("label", ["HP", "H.P", "hp", "ＨＰ"])
    def test_hp_is_a_mobile(self, label: str):
        """`HP`（handphone）を携帯として扱うこと。海外の名刺で使われる。"""
        assert fields(f"{label} 070-9385-4004")["mobile"] == "070-9385-4004"

    def test_hp_inside_another_word_is_not_a_label(self):
        """別の語の一部の `hp` をラベルにしないこと。"""
        assert find_labels("graphpad 03-1234-5678") == []
        assert find_labels("HP 070-9385-4004") == [(0, "mobile")]

    def test_labels_at_the_head_of_a_word_still_match(self):
        """`telephone` `cellular` のように語が続くラベルを取り逃がさないこと。"""
        assert find_labels("telephone: 03-1234-5678") == [(0, "tel")]
        assert find_labels("cellular: 090-1234-5678") == [(0, "mobile")]


class TestLabelWinsOverThePrefix:
    def test_ip_phone_with_a_tel_label_is_a_tel(self):
        """`Tel 050-…` は固定電話。050 はIP電話で携帯ではない。"""
        got = fields("Tel 050-3110-2873")

        assert got["tel"] == "050-3110-2873"
        assert got["mobile"] == ""

    def test_mobile_prefix_after_a_tel_label_is_still_a_mobile(self):
        """ラベルが前の番号のものなら、先頭3桁で見直すこと。

        `TEL 03-… / 090-…` のように1つのラベルで2つ並べる名刺がある。
        """
        got = fields("TEL 03-1234-5678 / 090-1234-5678")

        assert got["tel"] == "03-1234-5678"
        assert got["mobile"] == "090-1234-5678"

    def test_both_numbers_are_kept(self):
        got = fields(*KOREAN_CARD)

        assert got["mobile"] == "070-9385-4004"
        assert got["tel"] == "050-3110-2873"

    def test_unlabelled_ip_phone_is_a_tel(self):
        assert fields("050-3110-2873")["tel"] == "050-3110-2873"

    def test_unlabelled_mobile_is_still_a_mobile(self):
        assert fields("090-1234-5678")["mobile"] == "090-1234-5678"


class TestTitleAndNumberOnOneLine:
    """役職と番号を1行に印字する名刺。番号を採ったあと役職が空になっていた。"""

    def test_daihyo_torishimariyaku_is_not_a_tel_label(self):
        """`代表取締役` の `代表` を電話のラベルと数えないこと。

        代表電話のラベル `代表` は残す（`代表 03-1234-5678`）。
        """
        assert find_labels("代表取締役 090-1234-5678") == []
        assert find_labels("代表 03-1234-5678") == [(0, "tel")]

    def test_the_number_and_the_title_are_both_kept(self):
        got = fields("代表取締役 090-1234-5678")

        assert got["mobile"] == "090-1234-5678"
        assert got["title"] == "代表取締役"

    def test_a_label_before_the_title_is_removed(self):
        got = fields("部長 TEL 03-1234-5678")

        assert got["tel"] == "03-1234-5678"
        assert got["title"] == "部長"

    def test_a_phone_only_line_yields_no_title(self):
        got = fields("TEL 03-1234-5678  FAX 03-1234-5679")

        assert got["title"] == ""


class TestAddressLabel:
    @pytest.mark.parametrize("label", ["Add", "Address", "住所", "所在地", "ADD:"])
    def test_label_is_not_part_of_the_value(self, label: str):
        got = fields(f"{label} 〒100-0001 東京都千代田区千代田1-1-1")

        assert got["address"].replace(" ", "") == "東京都千代田区千代田1-1-1"

    def test_label_finds_an_address_without_other_hints(self):
        """郵便番号も都道府県も無い住所を、ラベルを頼りに拾うこと。"""
        got = fields("John Smith", "Add: 350 Fifth Avenue, New York")

        assert got["address"] == "350 Fifth Avenue, New York"

    def test_garbled_postal_is_not_left_in_the_address(self):
        """桁が合わず郵便番号として取れなかった `〒…` を住所に混ぜないこと。

        実測では `〒530-0001 大阪府…` が `〒5390-0091 大阪府…` と読まれていた。
        郵便番号は空でよい（誤った番号より直しやすい）が、住所は正しく取る。
        """
        got = fields("〒5390-0091 大阪府大阪市北区梅田2-2-2")

        assert got["postal_code"] == ""
        assert got["address"].replace(" ", "") == "大阪府大阪市北区梅田2-2-2"

    def test_a_leading_house_number_is_not_stripped(self):
        """英字住所の先頭の番地を、郵便番号の残骸と間違えて削らないこと。"""
        got = fields("John Smith", "7-1-1 Chiyoda, Chiyoda-ku, Tokyo")

        assert got["address"].startswith("7-1-1")

    def test_a_broken_url_line_is_not_an_address(self):
        """読み崩れたURLの行を住所にしないこと。

        実測では `www.kaido-foods.example` の行が
        `tal 7 <kaido-foods.example` と読まれ、住所に入っていた。
        """
        got = fields("山田 太郎", "tal 7 <kaido-foods.example")

        assert got["address"] == ""

    def test_a_word_starting_with_add_is_not_a_label(self):
        """`Addison Road` を `ison Road` にしないこと。"""
        got = fields("John Smith", "Addison Road 25, Springfield")

        assert got["address"].startswith("Addison")


class TestKoreanCardOverall:
    def test_seven_printed_items_are_all_extracted(self):
        """名刺に印字された7項目すべてが入ること。"""
        got = fields(*KOREAN_CARD)

        assert got["last_name"] == "ユン"
        assert got["first_name"] == "ソクン"
        assert got["title"] == "代表取締役"
        assert got["mobile"] == "070-9385-4004"
        assert got["tel"] == "050-3110-2873"
        assert got["email"] == "ceo@omorobot.com"
        assert got["postal_code"] == "580-0021"
        assert got["address"] == "大阪府松原市高見の里六丁目7-18"

    def test_nothing_is_invented(self):
        """名刺に無いものを埋めないこと（社名はロゴで、OCRに出ていない）。"""
        got = fields(*KOREAN_CARD)

        assert got["company_name"] == ""
        assert got["fax"] == ""

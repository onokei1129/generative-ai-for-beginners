"""住所の取り出し（services/ocr/parser.py）。

実テスト（222枚）で、住所について2つの報告があった。

1. **折り返された住所が空になる**（7枚目・NEXON GAMES）

       2621, Nambusunhwan-ro,
       Gangnam-gu, Seoul, Korea,
       06267

   1行ずつ見ると、1行目は語数が足りず、2行目は数字が無く、3行目は語数が
   足りない。どれも英字住所の条件を満たさず、住所が空になっていた。
   行末の読点は「次の行へ続く」という印なので、そこでつなぐ。

2. **読み崩れた断片が住所に入る**（8枚目・Causal Foundry G.K.）

   住所が `〒4 らの - の９の` になっていた。`〒150-0022` の行が読み崩れた
   もので、数字も空白区切りの語も条件を満たすため拾われていた。
   住所には地名が要る、という最低限の歯止めを置く。

歯止めは**厳しくしすぎない**こと。空欄なら人が入れれば済むが、正しい住所を
落とすと「なぜ取れないのか」が分からなくなる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.ocr.parser import (  # noqa: E402
    is_house_number_only,
    looks_like_address,
    parse_fields,
    repair_address_symbols,
    wrapped_blocks,
)


def address(lines: list[str]) -> str:
    return parse_fields(lines)["fields"]["address"]


class TestAWrappedAddressIsJoined:
    def test_the_real_card_that_came_back_empty(self):
        """7枚目の体裁。3行に分かれて印字されている。"""
        got = address([
            "NEXON GAMES",
            "2621, Nambusunhwan-ro,",
            "Gangnam-gu, Seoul, Korea,",
            "06267",
            "Sangeon Lee   T +82.2.6421.7777",
        ])

        assert got == "2621, Nambusunhwan-ro, Gangnam-gu, Seoul, Korea, 06267"

    @pytest.mark.parametrize("comma", [",", "、", "，"])
    def test_the_join_follows_any_comma(self, comma: str):
        got = wrapped_blocks([f"1 Main Street{comma}", "Springfield USA"], set())

        assert got[0] == (0, 1, f"1 Main Street{comma} Springfield USA")

    def test_a_line_without_a_comma_stands_alone(self):
        got = wrapped_blocks(["山田 太郎", "株式会社サンプル"], set())

        assert [block[2] for block in got] == ["山田 太郎", "株式会社サンプル"]

    def test_lines_already_taken_are_not_pulled_in(self):
        """他の項目に使った行を住所へ巻き込まないこと。"""
        got = wrapped_blocks(["1 Main Street,", "yamada@example.com"], {1})

        assert got[0] == (0, 0, "1 Main Street,")

    def test_the_joined_lines_are_not_reused(self):
        """つないだ行を、あとから他の項目に取られないこと。

        以前は住所に使うのが1行だけだったため、`used` に入れるのも1行だった。
        つないだぶんを全部入れないと、残りが会社名や部署に流れ込む。
        """
        fields = parse_fields([
            "株式会社サンプル商事",
            "2621, Nambusunhwan-ro,",
            "Gangnam-gu, Seoul, Korea,",
            "06267",
        ])["fields"]

        assert fields["company_name"] == "株式会社サンプル商事"
        assert "Gangnam" not in fields["department_name"]
        assert "Gangnam" not in fields["title"]


class TestGarbageIsNotAnAddress:
    def test_the_real_card_that_got_a_fragment(self):
        """8枚目の体裁。`〒150-0022` が読み崩れたもの。"""
        got = address([
            "ジョンソン 裕子",
            "Causal Foundry G.K.",
            "〒4 らの - の９の",
        ])

        assert got == ""

    @pytest.mark.parametrize(
        "text",
        [
            "〒4 らの - の９の",
            "の 9 の -",
            "1 2 3",
        ],
    )
    def test_fragments_are_rejected(self, text: str):
        assert not looks_like_address(text)

    @pytest.mark.parametrize(
        "text",
        [
            "2621, Nambusunhwan-ro, Gangnam-gu, Seoul, Korea, 06267",
            "Santa Beatriz 111 of 1008, Providencia. Santiago de Chile",
            "東京都渋谷区恵比寿南1-1-1 ヒューマックス恵比寿ビル8F",
            "大阪市北区梅田 1-1-1",
        ],
    )
    def test_real_addresses_are_kept(self, text: str):
        assert looks_like_address(text)

    def test_a_japanese_address_still_comes_through_the_normal_path(self):
        """歯止めは最終手段にだけ掛ける。手がかりのある住所は従来どおり。"""
        got = address([
            "山田 太郎",
            "〒150-0022 東京都渋谷区恵比寿南1-1-1",
        ])

        assert got == "東京都渋谷区恵比寿南1-1-1"


class TestAMisreadHyphenIsPutBack:
    """住所に `@` は入らない。

    実テスト（7枚目）で、住所が
    `2621, Nambusunhwan-ro, Gangnam@gu, Seoul, Korea` になっていた。
    `Gangnam-gu` の字の間のハイフンを `@` と読み違えたもの。読み違えそのものは
    OCRの側の問題だが、住所に `@` が入りえない以上、登録する前に戻せる。
    """

    def test_the_real_card_that_came_back_with_an_at_sign(self):
        got = repair_address_symbols("2621, Nambusunhwan-ro, Gangnam@gu, Seoul, Korea")

        assert got == "2621, Nambusunhwan-ro, Gangnam-gu, Seoul, Korea"

    @pytest.mark.parametrize(
        ("text", "want"),
        [
            ("A@B", "A-B"),
            ("1@2", "1-2"),
            ("Gangnam@gu@dong", "Gangnam-gu-dong"),
        ],
    )
    def test_it_only_touches_an_at_sign_between_characters(self, text: str, want: str):
        assert repair_address_symbols(text) == want

    @pytest.mark.parametrize("text", ["@example の建物", "建物 @", "@", "ビル @2F"])
    def test_a_standalone_at_sign_is_left_alone(self, text: str):
        """`@` で始まる ID などを壊さないこと。"""
        assert repair_address_symbols(text) == text

    def test_a_japanese_address_is_unchanged(self):
        text = "東京都渋谷区恵比寿南1-1-1 ヒューマックス恵比寿ビル8F"

        assert repair_address_symbols(text) == text

    def test_the_email_field_is_not_touched(self):
        """直すのは住所だけ。メールの `@` は残す。"""
        fields = parse_fields([
            "山田 太郎",
            "yamada@example.co.jp",
            "〒150-0022 東京都渋谷区恵比寿南1-1-1",
        ])["fields"]

        assert fields["email"] == "yamada@example.co.jp"


class TestTheGuardAppliesToEveryPath:
    """歯止めは経路によらず最後に掛けること。

    はじめは英字住所の最終手段にだけ掛けていた。実テスト（8枚目）では
    それとは別の経路から `〒4 らの - の９の` が入り、直したはずの名刺で
    残ったままだった。
    """

    def test_the_check_runs_on_the_final_value(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src/bcards/services/ocr/parser.py"
        ).read_text()
        tail = source.rsplit("leftovers =", 1)[0]

        assert 'if fields["address"] and not looks_like_address(fields["address"])' in tail

    def test_the_confidence_goes_with_it(self):
        """値を消したら確からしさも残さないこと。"""
        source = (
            Path(__file__).resolve().parents[1]
            / "src/bcards/services/ocr/parser.py"
        ).read_text()

        assert 'confidence.pop("address", None)' in source

    @pytest.mark.parametrize(
        "text",
        [
            "ヒューマックスビル",
            "サンシャインシティ",
        ],
    )
    def test_a_katakana_building_is_kept(self, text: str):
        """漢字が無くてもカタカナの建物名なら住所として通す。"""
        assert looks_like_address(text)

    @pytest.mark.parametrize("text", ["1-2-3", "らの - の９の", "〒4 らの - の９の"])
    def test_kana_and_digits_alone_are_rejected(self, text: str):
        assert not looks_like_address(text)


class TestAHouseNumberOnTheNextLineIsJoined:
    """番地だけが次の行に回った場合につなぐ。

    実テスト（227枚）の3枚目で、住所が `大阪府松原市高見の里六丁目` になり、
    番地の `7-18` が落ちていた。名刺には1行で印字されているが、OCRは
    別の行として返していた。

    英字の住所は行末の読点が折り返しの印になるが、日本語の住所には印が無い。
    数字だけの行は、その手前の住所の続きとみなす。

    電話番号・郵便番号を巻き込まないこと。どちらも数字と区切りだけの行に
    なりうるうえ、住所の近くに印字される。
    """

    def test_the_real_card_that_lost_its_house_number(self):
        got = parse_fields([
            "代表取締役",
            "ユン ソクン",
            "SEOKHOON YOON",
            "HP 070-9385-4004",
            "Tel 050-3110-2873",
            "E-mail ceo@omorobot.com",
            "Add 〒580-0021",
            "大阪府松原市高見の里六丁目",
            "7-18",
        ])["fields"]

        assert got["address"] == "大阪府松原市高見の里六丁目7-18"

    def test_the_other_fields_are_not_disturbed(self):
        got = parse_fields([
            "Add 〒580-0021",
            "大阪府松原市高見の里六丁目",
            "7-18",
            "HP 070-9385-4004",
            "Tel 050-3110-2873",
        ])["fields"]

        assert got["postal_code"] == "580-0021"
        assert got["tel"] == "050-3110-2873"
        assert got["mobile"] == "070-9385-4004"

    @pytest.mark.parametrize("text", ["7-18", "1-2-3", "2621", "18"])
    def test_a_house_number_is_recognised(self, text: str):
        assert is_house_number_only(text)

    @pytest.mark.parametrize(
        "text",
        [
            "580-0021",       # 郵便番号
            "03-1234-5678",   # 固定電話
            "090-1234-5678",  # 携帯
            "123456789",      # 9桁。電話番号の桁数
            "六丁目",           # 数字ではない
            "7-18 Osaka",     # 数字だけの行ではない
            "",
        ],
    )
    def test_other_numbers_are_left_alone(self, text: str):
        assert not is_house_number_only(text)

    def test_a_phone_line_is_not_swallowed(self):
        """住所の次が電話番号でも、住所につながないこと。"""
        got = parse_fields([
            "〒100-0001 東京都千代田区千代田",
            "03-1234-5678",
        ])["fields"]

        assert got["address"] == "東京都千代田区千代田"
        assert got["tel"] == "03-1234-5678"

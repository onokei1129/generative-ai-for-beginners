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
    looks_like_address,
    parse_fields,
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

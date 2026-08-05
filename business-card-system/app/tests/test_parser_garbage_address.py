"""読み崩れの断片を住所にしない（実テスト 25枚目・縦書き）。

住所欄にこれが入っていた。

    bEOO-SEI= YfEと szEZ:i〕E7fとEr_井子_料

「漢字が2つ以上あれば住所」という歯止めしか無く、`井` `子` `料` が散らばって
いるだけで通っていた。

害は2つある。

1. 住所欄に読めない文字列が入る
2. **住所が埋まっているせいで「読めた」と判定され、画像を回して読み直す
   仕掛けが動かない**（`services/ocr.looks_unreadable`）。縦書きのために
   入れた仕掛けが、まさにその1枚で発火していなかった

読み崩れの目印は2つ。

- 住所に出ない記号（`=` `〕` `_` `|`）
- 語の途中で小文字から大文字へ跳ぶ並び（`bEOO` `YfE` `szEZ`）。
  実在の綴り（`McDonald`）でも起こるので、**2回以上**を条件にする
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import looks_unreadable  # noqa: E402
from bcards.services.ocr.parser import looks_like_address, parse_fields  # noqa: E402

GARBAGE = "bEOO-SEI= YfEと szEZ:i〕E7fとEr_井子_料"


class TestTheGarbageIsRejected:
    def test_the_fragment_is_not_an_address(self):
        assert not looks_like_address(GARBAGE)

    def test_the_field_stays_empty(self):
        got = parse_fields(["株式会社サンプル", GARBAGE])["fields"]

        assert got["address"] == ""

    def test_the_card_is_then_seen_as_unreadable(self):
        """住所が空になることで、回して読み直す仕掛けが動くようになる。"""
        parsed = parse_fields([GARBAGE])

        assert looks_unreadable(parsed)

    @pytest.mark.parametrize(
        "text",
        [
            "bEOO-SEI= YfEと szEZ",
            "東京都 = 千代田区",
            "ab〕cd 東京 都",
            "aBcDeF 品川 区",
        ],
    )
    def test_other_broken_fragments_are_rejected(self, text: str):
        assert not looks_like_address(text)


class TestRealAddressesAreKept:
    @pytest.mark.parametrize(
        "text",
        [
            "東京都千代田区千代田1-1-1",
            "東京都渋谷区恵比寿南1-1-1 ヒューマックス恵比寿ビル8F",
            "8F, First Tower, 55, Bundang-ro, Bundang-gu, Seongnam-si, Gyeonggi-do",
            "2621, Nambusunhwan-ro, Gangnam-gu, Seoul, Korea",
            "沖縄県那覇市おもろまち2丁目1番1号",
            "大阪府松原市高見の里六丁目7-18",
            "Santa Beatriz 111 of 1008, Providencia. Santiago de Chile",
        ],
    )
    def test_the_address_is_kept(self, text: str):
        assert looks_like_address(text)

    def test_one_odd_capital_is_not_enough_to_reject(self):
        """`McDonald` のような綴りは実在する。1回では弾かない。"""
        assert looks_like_address("1 McDonald Avenue, Brooklyn, New York")

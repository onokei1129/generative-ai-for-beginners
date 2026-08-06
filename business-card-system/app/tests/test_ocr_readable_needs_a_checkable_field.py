"""「読めた」の判定は、形を確かめられる項目だけで行う（services/ocr）。

実テスト 25枚目（縦書き）で2回続けて同じことが起きた。

    1回目  住所『bEOO-SEI= YfEと szEZ:i〕E7fとEr_井子_料』
    2回目  住所『soipms OOWVN IVQNV8』   ← 記号を弾いたら別のゴミが通った

住所と会社名は**自由な文字列**なので、読み崩れがいくらでも似た形になる。
歯止めを1つ足すたびに別のゴミが通る、といういたちごっこになっていた。

**形を確かめられる項目だけを「読めた証拠」にする。**

    メール      `@` とドメインの形
    電話・FAX   桁数と区切り
    郵便番号    3桁-4桁
    URL         スキームかドメインの形

これらは読み崩れではまず満たせない。住所・会社名は証拠に数えない。

住所と会社名しか無い名刺は、回して読み直す手間（軽い下読み2回）が増える
だけで、結果は変わらない。誤って回さないことによる損失——縦書きが読めない
まま——のほうが大きい。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

from bcards.services.ocr import looks_unreadable  # noqa: E402
from bcards.services.ocr.parser import looks_like_address  # noqa: E402


def parsed(**fields) -> dict:
    keys = ("last_name", "first_name", "company_name", "email", "tel", "mobile",
            "postal_code", "address", "title", "department_name", "url", "fax")
    return {"fields": {key: fields.get(key, "") for key in keys}}


class TestFreeTextIsNotEvidence:
    def test_an_address_alone_does_not_count(self):
        """実テスト 25枚目。読み崩れが住所欄に入り、回す判定を止めていた。"""
        assert looks_unreadable(parsed(address="soipms OOWVN IVQNV8"))

    def test_a_real_address_alone_also_does_not_count(self):
        """本物でも、住所だけでは回す判定を止めない。回しても結果は変わらない。"""
        assert looks_unreadable(parsed(address="東京都千代田区千代田1-1-1"))

    def test_a_company_name_alone_does_not_count(self):
        assert looks_unreadable(parsed(company_name="株式会社サンプル"))


class TestCheckableFieldsCount:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("email", "taro@example.co.jp"),
            ("tel", "03-1234-5678"),
            ("mobile", "090-1234-5678"),
            ("fax", "03-1234-5679"),
            ("postal_code", "100-0001"),
            ("url", "https://www.example.co.jp"),
        ],
    )
    def test_one_checkable_field_is_enough(self, key: str, value: str):
        assert not looks_unreadable(parsed(**{key: value}))


class TestTheGarbageAddressIsAlsoRejected:
    """欄そのものも汚さない。空欄なら入力する人が気づく。"""

    @pytest.mark.parametrize(
        "text",
        [
            "soipms OOWVN IVQNV8",
            "SHAS gay ODINVN",
            "coouueuleDud MMM",
        ],
    )
    def test_the_fragment_is_not_an_address(self, text: str):
        assert not looks_like_address(text)

    @pytest.mark.parametrize(
        "text",
        [
            "8F, First Tower, 55, Bundang-ro, Bundang-gu, Seongnam-si, Gyeonggi-do",
            "2621, Nambusunhwan-ro, Gangnam-gu, Seoul, Korea",
            "Santa Beatriz 111 of 1008, Providencia. Santiago de Chile",
            "東京都千代田区千代田1-1-1",
            "沖縄県那覇市おもろまち2丁目1番1号",
        ],
    )
    def test_a_real_address_is_kept(self, text: str):
        assert looks_like_address(text)

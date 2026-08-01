"""複数ページPDFで画像が出なくなる不具合（poc/label.py, services/images.py）。

実テスト（225枚）で「7枚目以降の名刺の画像が見られない」という報告があった。
利用者の見立て（メモリの問題）が当たっていた。

ラベル入力の画面は各ファイルの**1枚目しか使わない**が、読み込みは
全ページを展開していた。読み取り機は複数枚をまとめて1つのPDFにするため、
1ファイルが数十ページになる。1ページの展開に15MB前後かかるので、

    20ページのPDF（229KB）  load_pages    3.73秒 / 展開した画素 297MB
                            process_file 22.87秒 / 最大RSS 1.17GB

となり、さらに次の名刺を裏で先読みする（`_warm_next`）ぶんが重なって
メモリを使い切り、以降の画像が出なくなっていた。

修正後は先頭1ページだけを読む（`load_pages(limit=1)` /
`process_file(page_limit=1)`）。取込の本線は全ページのまま。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services.images import load_pages, process_file  # noqa: E402

PAGE_COUNT = 6


def multi_page_pdf(count: int = PAGE_COUNT) -> bytes:
    pages = [Image.new("RGB", (1050, 640), (250, 250, 250)) for _ in range(count)]
    buffer = io.BytesIO()
    pages[0].save(buffer, format="PDF", save_all=True, append_images=pages[1:])
    return buffer.getvalue()


def multi_page_tiff(count: int = PAGE_COUNT) -> bytes:
    pages = [Image.new("RGB", (1050, 640), (250, 250, 250)) for _ in range(count)]
    buffer = io.BytesIO()
    pages[0].save(buffer, format="TIFF", save_all=True, append_images=pages[1:])
    return buffer.getvalue()


class TestLoadPagesLimit:
    def test_all_pages_by_default(self):
        """取込の本線は全ページを読む（表裏や複数枚を落とさないため）。"""
        assert len(load_pages(multi_page_pdf(), "many.pdf")) == PAGE_COUNT

    def test_only_the_first_page_when_limited(self):
        assert len(load_pages(multi_page_pdf(), "many.pdf", limit=1)) == 1

    def test_the_limit_can_be_more_than_one(self):
        assert len(load_pages(multi_page_pdf(), "many.pdf", limit=3)) == 3

    def test_a_limit_larger_than_the_document_is_harmless(self):
        assert len(load_pages(multi_page_pdf(), "many.pdf", limit=99)) == PAGE_COUNT

    def test_the_page_number_is_still_recorded(self):
        pages = load_pages(multi_page_pdf(), "many.pdf", limit=1)

        assert pages[0].page_no == 1

    @pytest.mark.parametrize("limit", [1, 2])
    def test_multi_page_tiff_is_limited_too(self, limit: int):
        """複数ページTIFFも同じ扱いにすること（読み取り機の設定で出る形式）。"""
        assert len(load_pages(multi_page_tiff(), "many.tif", limit=limit)) == limit

    def test_a_single_page_file_is_unaffected(self):
        buffer = io.BytesIO()
        Image.new("RGB", (1050, 640), (255, 255, 255)).save(buffer, format="PNG")

        assert len(load_pages(buffer.getvalue(), "one.png", limit=1)) == 1


class TestProcessFilePageLimit:
    def test_all_pages_by_default(self):
        cards = process_file(multi_page_pdf(), "many.pdf", correct=False)

        assert len(cards) == PAGE_COUNT

    def test_only_the_first_page_when_limited(self):
        """画面が使うのは1枚目だけ。残りのページに補正まで掛けないこと。"""
        cards = process_file(multi_page_pdf(), "many.pdf", correct=False, page_limit=1)

        assert len(cards) == 1
        assert cards[0].page_no == 1

    def test_the_card_is_usable(self):
        cards = process_file(multi_page_pdf(), "many.pdf", correct=False, page_limit=1)

        assert cards[0].image.size[0] > 0
        assert cards[0].ocr_image.size[0] > 0


class TestTheLabelScreenPassesTheLimit:
    """画面側で必ず1ページに絞っていること。

    ここを渡し忘れると不具合が戻る。呼び出しの引数で確かめる。
    """

    def test_both_call_sites_limit_to_one_page(self):
        """1ページに絞る指定は、重い処理を任せた子プロセス側にある。

        画面（label.py）は子を呼ぶだけになった。読み込み自体は
        `poc/one_card.py` が行う（`run_in_child` の説明を参照）。
        """
        source = (Path(__file__).resolve().parents[1] / "poc" / "one_card.py").read_text(
            encoding="utf-8"
        )

        assert "load_pages(path.read_bytes(), path.name, limit=1)" in source
        assert "process_file(path.read_bytes(), path.name, page_limit=1)" in source


class TestServerDownIsNotReportedAsOneCard:
    """サーバーが落ちているときに「この1枚だけの問題」と出さないこと。

    実テストでは、以降の名刺もすべて画像が出ない状態で「この1枚だけ」と
    表示していたため、原因をファイルだと見誤ることになった。
    """

    def test_the_page_distinguishes_the_two_cases(self):
        source = (Path(__file__).resolve().parents[1] / "poc" / "label.py").read_text(
            encoding="utf-8"
        )

        assert "サーバーが応答していません" in source
        # 生存確認をしてから「この1枚だけ」と言うこと
        assert "'/api/files', { cache: 'no-store' }" in source

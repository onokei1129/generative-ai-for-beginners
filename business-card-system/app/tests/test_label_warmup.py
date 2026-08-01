"""ラベル入力の先読みとキャッシュ（poc/label.py）。

実テスト（222枚）で、続けて進めている最中に**サーバーが落ちた**。画像が
出ず、下書きも止まったままになった。

先読みは「保存して次へ」を押すたびにスレッドを最大2本立てる作りで、上限が
無かった。1本あたり画像1枚（実測78MB）と tesseract のプロセスを抱えるため、
速く進めるほど積み上がる。結果を覚えておく側にも上限が無く、1件ごとに
OCRの読み取り文字を丸ごと持っていた。

先読みは**速くするための仕掛け**で、無くても動く。積み上がるくらいなら
捨ててよい。

画面はサーバーを起動しないと動かせないので、ここでは中身を読んで確かめる。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

LABEL = Path(__file__).resolve().parents[1] / "poc" / "label.py"


def source() -> str:
    return LABEL.read_text(encoding="utf-8")


class TestOnlyOneWarmUpRunsAtATime:
    """押すたびにスレッドを立てないこと。"""

    def test_the_work_goes_through_a_queue(self):
        text = source()

        assert "_warm_queue: queue.Queue[Path] = queue.Queue()" in text
        assert "_warm_queue.put(directory / nxt)" in text

    def test_a_single_worker_drains_it(self):
        text = source()

        assert "def _warm_worker() -> None:" in text
        assert "_warm_queue.get()" in text

    def test_the_worker_is_started_only_once(self):
        text = source()

        assert "if not _warm_started.is_set():" in text
        assert "_warm_started.set()" in text

    def test_no_thread_is_started_per_card(self):
        """以前の形（1枚ごとに Thread を立てる）へ戻らないこと。"""
        text = source()

        assert "threading.Thread(target=_ocr_draft" not in text

    def test_the_queue_does_not_grow_without_bound(self):
        """押すのが速いと並びが伸びる。伸びたぶんは捨てる。"""
        text = source()

        assert "if _warm_queue.qsize() >= 4:" in text

    def test_a_failed_warm_up_does_not_stop_the_worker(self):
        text = source()
        worker = text.split("def _warm_worker", 1)[1].split("def _warm_next", 1)[0]

        assert "except Exception:" in worker
        assert "_warm_queue.task_done()" in worker


class TestTheCacheHasALimit:
    """覚えておく枚数に上限を置くこと。

    1件あたりOCRの読み取り文字を丸ごと持つため、222枚を通すと積み上がる。
    行き来するのは前後数枚なので、少なくて足りる。
    """

    def test_the_limit_is_stated(self):
        text = source()

        assert "CACHE_LIMIT = 40" in text

    def test_the_oldest_is_dropped_first(self):
        text = source()

        assert "OrderedDict" in text
        assert "_ocr_cache.popitem(last=False)" in text

    def test_every_store_goes_through_the_helper(self):
        """上限を通さずに直接入れないこと。"""
        text = source()
        stores = re.findall(r"_ocr_cache\[[^\]]+\]\s*=", text)

        assert len(stores) == 1
        assert "def _remember(" in text

    def test_looking_at_a_card_keeps_it(self):
        """見た分を最近使ったものとして扱う（古い順に捨てるため）。"""
        text = source()

        assert "_ocr_cache.move_to_end(name)" in text


class TestTheDraftStillWorks:
    """作り直しても、下書きそのものの約束は変えないこと。"""

    def test_only_the_first_page_is_used(self):
        assert "page_limit=1" in source()

    def test_a_failure_is_not_remembered(self):
        """一時的な失敗を覚え込まない（直しても開き直すまで直らなくなる）。"""
        text = source()

        assert "失敗はキャッシュしない" in text

    def test_the_ocr_text_is_returned_for_the_screen(self):
        """項目が空のとき、読めていないのか取り出せていないのかの切り分けに要る。"""
        assert "OCRが読んだ文字そのもの" in source()

    @pytest.mark.parametrize("name", ["queue", "OrderedDict"])
    def test_what_it_needs_is_imported(self, name: str):
        head = source().split("app = FastAPI", 1)[0]

        assert name in head

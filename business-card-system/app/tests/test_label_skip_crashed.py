"""前回落ちた名刺は、次に開いたとき処理しない（poc/label.py）。

実テストで、ある名刺を開くとサーバーが落ちる。開き直しても**同じ名刺から
始まる**ため、また落ちる。利用者は先へ進めない。

    19 / 221 枚目  (会社名)_雷 日.pdf
    立ち上げた時点でもう応答しない

原因はまだ特定できていない（`落ちた記録.txt` を待っている）。しかし原因が
分かるまで作業が止まるのは困る。**落ちた名刺を覚えて、次は触らない**ように
すれば、その1枚を飛ばして先へ進める。

判定は記録から行う。`_log_step` は工程の前後に1行ずつ書く。

    08/03 13:12:46  開始 OCR あぶない.pdf
    ← 「完了」が無い＝この名刺の処理中に落ちた

その名刺は下書きも画像の変換もせず、理由だけを返す。画面には「前回ここで
落ちました」と出るので、利用者は飛ばすか、手で入力できる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_worker():
    label.stop_worker()
    yield
    label.stop_worker()


def write_log(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestReadingTheRecord:
    def test_a_step_without_a_finish_is_a_crash(self, tmp_path: Path):
        log = tmp_path / "ログ.txt"
        write_log(log, "08/03 13:00:00  開始 OCR あぶない.pdf")

        assert label.cards_that_crashed(log) == {"あぶない.pdf"}

    def test_a_finished_step_is_not_a_crash(self, tmp_path: Path):
        log = tmp_path / "ログ.txt"
        write_log(
            log,
            "08/03 13:00:00  開始 OCR ふつう.pdf",
            "08/03 13:00:05  完了 OCR ふつう.pdf",
        )

        assert label.cards_that_crashed(log) == set()

    def test_only_the_unfinished_one_is_returned(self, tmp_path: Path):
        log = tmp_path / "ログ.txt"
        write_log(
            log,
            "08/03 13:00:00  開始 OCR ふつう.pdf",
            "08/03 13:00:05  完了 OCR ふつう.pdf",
            "08/03 13:00:06  開始 OCR あぶない.pdf",
        )

        assert label.cards_that_crashed(log) == {"あぶない.pdf"}

    def test_the_image_step_counts_too(self, tmp_path: Path):
        log = tmp_path / "ログ.txt"
        write_log(log, "08/03 13:00:00  開始 画像の表示 あぶない.pdf")

        assert label.cards_that_crashed(log) == {"あぶない.pdf"}

    def test_a_clean_shutdown_clears_everything_before_it(self, tmp_path: Path):
        """黒い画面を閉じただけなら、処理中だった名刺は落ちていない。

        実テストで、19枚目は**18秒かかっただけ**で落ちていなかった。待って
        いる途中で閉じれば「開始」だけが残る。それを落ちたことにすると、
        **読める名刺を二度と読まなくなる**。落ちたときは終了の印を書けない
        （C の側で落ちるため Python は動かない）ので、印の有無で分けられる。
        """
        log = tmp_path / "ログ.txt"
        write_log(
            log,
            "08/03 13:00:00  開始 OCR おそい.pdf",
            "08/03 13:00:18  --- 終了 ---",
        )

        assert label.cards_that_crashed(log) == set()

    def test_a_crash_after_a_clean_shutdown_still_counts(self, tmp_path: Path):
        """印より後ろの「開始」だけは、今回落ちたということ。"""
        log = tmp_path / "ログ.txt"
        write_log(
            log,
            "08/03 13:00:00  開始 OCR おそい.pdf",
            "08/03 13:00:18  --- 終了 ---",
            "08/03 13:05:00  開始 OCR あぶない.pdf",
        )

        assert label.cards_that_crashed(log) == {"あぶない.pdf"}

    def test_no_record_means_nothing_crashed(self, tmp_path: Path):
        assert label.cards_that_crashed(tmp_path / "ない.txt") == set()

    def test_a_name_with_spaces_is_read_whole(self, tmp_path: Path):
        """`(会社名)_雷 日.pdf` のように名前に空白が入る。"""
        log = tmp_path / "ログ.txt"
        write_log(log, "08/03 13:00:00  開始 OCR (会社名)_雷 日.pdf")

        assert label.cards_that_crashed(log) == {"(会社名)_雷 日.pdf"}


class TestTheCardIsLeftAlone:
    @pytest.fixture
    def cards(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        Image.new("RGB", (1050, 640), "white").save(tmp_path / "あぶない.png")
        Image.new("RGB", (1050, 640), "white").save(tmp_path / "ふつう.png")
        log = tmp_path / "ログ.txt"
        write_log(log, "08/03 13:00:00  開始 OCR あぶない.png")
        monkeypatch.setattr(label, "LOG_PATH", log)
        return tmp_path

    def test_the_draft_is_not_made(self, cards: Path):
        client = TestClient(label.build_app(cards, prefill=True))

        body = client.get("/api/label/あぶない.png?draft=1").json()

        assert "前回" in body["source"]
        assert body["kind"] == "error"

    def test_the_other_cards_still_work(self, cards: Path):
        client = TestClient(label.build_app(cards, prefill=True))

        body = client.get("/api/label/ふつう.png?draft=1").json()

        assert body["kind"] == "draft"

    def test_the_screen_still_answers(self, cards: Path):
        """落ちた名刺でも画面は返る。返らないと利用者は先へ進めない。"""
        client = TestClient(label.build_app(cards, prefill=True))

        assert client.get("/api/label/あぶない.png?draft=1").status_code == 200

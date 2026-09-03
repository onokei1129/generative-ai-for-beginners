"""重い処理をする子プロセスを、名刺ごとに作り直さない（実テスト 5・6枚目）。

実テストで、ラベル入力のサーバーが落ちた。

    5枚目  取得できませんでした: TypeError: Failed to fetch
    6枚目  サーバーが応答していません。

原因の候補として、まず測れることを測った。併用構成（EasyOCR + tesseract）
を既定にしたあと、子プロセスは**1枚あたり 1.4GB / 12秒**かかっている。
名刺ごとに作り直すので、EasyOCR のモデルを毎回読み直している。先読みの
裏方と合わせて同時に2つ動くため、ピークは約2.8GBになる。

子を1つ保ち続ければ、モデルの読み込みは1回で済み、同時に2つ動くことも
なくなる。別プロセスである以上、C のライブラリが落ちても道連れになるのは
子だけ、という当初の狙いは変わらない（落ちたら作り直す）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
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


@pytest.fixture
def card(tmp_path: Path) -> Path:
    path = tmp_path / "card.png"
    Image.new("RGB", (1050, 640), "white").save(path)
    return path


class TestTheWorkerIsReused:
    def test_two_cards_share_one_process(self, card: Path):
        label.run_in_child(["ocr", str(card)])
        first = label.worker_pid()
        label.run_in_child(["ocr", str(card)])

        assert first is not None
        assert label.worker_pid() == first

    def test_the_result_still_comes_back(self, card: Path):
        got = label.run_in_child(["ocr", str(card)])

        assert "fields" in got
        assert "text" in got

    def test_making_an_image_works_through_the_same_worker(self, card: Path, tmp_path: Path):
        out = tmp_path / "out.jpg"

        label.run_in_child(["image", str(card), str(out)])

        assert out.exists() and out.stat().st_size > 0


class TestACrashedWorkerIsReplaced:
    def test_the_next_card_still_works(self, card: Path):
        """C のライブラリが落ちると子ごと消える。作り直して先へ進む。"""
        label.run_in_child(["ocr", str(card)])
        first = label.worker_pid()
        label.kill_worker()

        got = label.run_in_child(["ocr", str(card)])

        assert "fields" in got
        assert label.worker_pid() != first


class TestClosingDoesNotWaitForTheCard:
    """OCRの最中に閉じても、その1枚が終わるまで止まらないこと。

    頼みごとは1件ずつ順に渡す。ここまでは要る（同時に2枚を処理させない）。
    ただし**片付ける側まで同じ順番待ちに入れてはいけない**。入れると、
    Ctrl-C やウィンドウを閉じたときに、その1枚が終わるまで（最長300秒）
    固まって見える。

    「処理中に閉じる」をそのまま作るのは、このテストでは無理がある。テストの
    OCRは mock で1秒とかからず、閉じる前に終わってしまうため。**性質を2つに
    分けて**、それぞれ確かめる。
    """

    def test_cleaning_up_does_not_queue_behind_a_card(self, card: Path):
        """順番待ちの錠を握ったまま——1枚を処理している最中と同じ状態にする。"""
        import time

        label.run_in_child(["ocr", str(card)])

        with label.lane_lock("ocr"):
            started = time.time()
            label.stop_worker()
            took = time.time() - started

        assert took < 5, f"片付けに {took:.1f}秒かかった"
        assert label.worker_pid() is None

    def test_a_waiting_caller_is_released_when_the_child_dies(self):
        """返事を待っている側は、子が消えたら理由を受け取って進めること。

        ここが待ち続けると、画面は「サーバーが応答していません」のまま戻らない。
        """
        worker = label._Worker()
        worker.process.kill()
        worker.process.wait(timeout=10)

        with pytest.raises(label.ChildFailed):
            worker.ask("ocr", ["どれでもよい.png"])


class TestAFailureIsExplained:
    def test_a_missing_file_gives_a_reason(self, tmp_path: Path):
        with pytest.raises(label.ChildFailed) as caught:
            label.run_in_child(["ocr", str(tmp_path / "ない.png")])

        assert str(caught.value)

    def test_the_worker_survives_a_failed_card(self, card: Path, tmp_path: Path):
        """1枚の失敗で、そのあとの全部が止まってはいけない。"""
        with pytest.raises(label.ChildFailed):
            label.run_in_child(["ocr", str(tmp_path / "ない.png")])

        got = label.run_in_child(["ocr", str(card)])

        assert "fields" in got

    def test_an_unknown_mode_is_reported(self, card: Path):
        with pytest.raises(label.ChildFailed):
            label.run_in_child(["しらない", str(card)])


class TestTheChildsTracebackIsKept:
    """画面に出せるのは1行だけ。全文が残らないと報告の往復になる。

    1枚ごとに子を作り直していた頃は、終わってからまとめて標準エラーを読めた。
    常駐させるとその機会が無いので、失敗のたびに読んで記録へ移す。
    """

    @pytest.fixture
    def log(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "ログ.txt"
        monkeypatch.setattr(label, "LOG_PATH", path)
        return path

    def test_a_failed_card_leaves_the_whole_traceback(self, log: Path, tmp_path: Path):
        with pytest.raises(label.ChildFailed):
            label.run_in_child(["ocr", str(tmp_path / "ない.png")])

        text = log.read_text(encoding="utf-8")
        assert "Traceback" in text
        assert "ない.png" in text

    def test_the_next_failure_does_not_repeat_the_first(self, log: Path, tmp_path: Path):
        """前回ぶんが混ざると、どこからが今回か分からなくなる。"""
        for name in ("いち.png", "に.png"):
            with pytest.raises(label.ChildFailed):
                label.run_in_child(["ocr", str(tmp_path / name)])

        second = log.read_text(encoding="utf-8").split("=====")[-1]
        assert "に.png" in second
        assert "いち.png" not in second


class TestTextThatBreaksCp932:
    def test_japanese_comes_back_intact(self):
        """`ソ` は cp932 で 2バイト目が円記号。UTF-8 のバイトで渡すこと。

        子は `label.py` と同じやり方で立てる（ファイルをそのまま渡す）。
        `python -c` に読み込ませて動かすと `__file__` が無く、子が自分の
        居場所から `src` を辿れない。**動かし方まで含めて**確かめる。
        """
        import json
        import subprocess

        proc = subprocess.Popen(
            [sys.executable, str(APP / "poc" / "one_card.py"), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            request = {"mode": "echo", "args": ["ソ 表 能 十"]}
            proc.stdin.write(json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        finally:
            proc.kill()

        assert line, f"返事がありません: {proc.stderr.read().decode('utf-8', 'replace')}"
        reply = json.loads(line)
        assert reply["ok"] is True
        assert reply["result"]["echo"] == "ソ 表 能 十"

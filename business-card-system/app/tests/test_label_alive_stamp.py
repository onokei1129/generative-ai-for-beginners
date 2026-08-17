"""サーバーが生きているあいだ、その印を上書きし続ける（poc/label.py）。

## なぜ要るのか

実テストの記録（08/17）から、ここまでは確定した。

    12:12:14  --- 開始 --- 版 4a37cfd
    ...
    12:12:36  開始 OCR (会社名)_雷 日.pdf     ← 完了が無い
    12:57:22  --- 開始 --- 版 28d2a8d          ← 次に立ち上げた回

1. `--- 終了 ---`（atexit で書く印）が無い
2. `サーバーが落ちました: 終了コード ○○`（見張り役が子の死を書く印）も無い
3. `落ちた記録.txt`（faulthandler）は空

1と2が同時に無いということは、**見張り役とサーバーが一緒に、Python の
後始末を1行も通さずに止まった**ということ。子だけが死んだのなら2が書かれ、
Ctrl-C なら1が書かれる。3から、C のライブラリの異常終了でもない。

ただし記録だけでは、次の2つを**区別できない**。

    ア  プロセスごと外から止められた（窓を閉じた／終了させられた）
    イ  生きているが応答しない（画面には同じ「応答していません」が出る）

記録に残るのは名刺の処理だけで、画面が繋がらなければ処理は来ない。
つまりどちらでも記録は同じところで止まる。**8日間この区別が付かず、
原因に辿り着けていない。**

## 何をするか

生きているあいだ、時刻とメモリ使用量を小さなファイルへ**上書き**する。

    08/17 12:58:20  版 28d2a8d  メモリ 412MB

次に「応答していません」が出たとき、この印の時刻を見れば分かる。

    印が進み続けている  → イ（生きている。別の手当てが要る）
    印が止まっている    → ア（プロセスが消えている）

追記ではなく上書きにする。記録を汚さず、大きくもならない。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402


class TestTheStamp:
    def test_it_writes_the_time(self, tmp_path, monkeypatch):
        stamp = tmp_path / "動いている印.txt"
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)

        label.note_alive()

        assert stamp.exists()
        assert label._RUNNING_VERSION in stamp.read_text(encoding="utf-8")

    def test_it_overwrites_rather_than_appends(self, tmp_path, monkeypatch):
        """追記だと、動かしっぱなしで際限なく増える。"""
        stamp = tmp_path / "動いている印.txt"
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)

        label.note_alive()
        label.note_alive()
        label.note_alive()

        assert len(stamp.read_text(encoding="utf-8").strip().splitlines()) == 1

    def test_a_bad_path_does_not_stop_the_server(self, tmp_path, monkeypatch):
        """印は手がかりであって、目的ではない。書けなくても止めない。"""
        monkeypatch.setattr(label, "ALIVE_PATH", tmp_path / "無い階層" / "印.txt")

        label.note_alive()  # 例外を出さない


class TestTheHeartbeat:
    def test_it_keeps_writing(self, tmp_path, monkeypatch):
        stamp = tmp_path / "動いている印.txt"
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)

        stop = label.start_heartbeat(seconds=0.05)
        try:
            deadline = time.monotonic() + 5
            seen = set()
            while time.monotonic() < deadline and len(seen) < 2:
                if stamp.exists():
                    seen.add(stamp.read_text(encoding="utf-8"))
                time.sleep(0.02)
        finally:
            stop()

        assert len(seen) >= 2, "印が進んでいない"

    def test_it_does_not_hold_the_process_open(self, tmp_path, monkeypatch):
        """待ち続ける裏方が残ると、閉じても終われなくなる。"""
        monkeypatch.setattr(label, "ALIVE_PATH", tmp_path / "印.txt")

        stop = label.start_heartbeat(seconds=60)
        try:
            assert label._heartbeat_thread is not None
            assert label._heartbeat_thread.daemon
        finally:
            stop()


class TestItIsOfferedToTheOperator:
    def test_the_screen_names_it(self, tmp_path):
        """落ちたときに送っていただくファイルの一覧に入れる。"""
        Image.new("RGB", (300, 190), "white").save(tmp_path / "a.png")

        with TestClient(label.build_app(tmp_path, False)) as client:
            logs = client.get("/api/files").json()["logs"]

        assert str(label.ALIVE_PATH) in logs

    def test_the_startup_reports_the_last_one(self, tmp_path, monkeypatch, capsys):
        """立ち上げ直したとき、前回いつまで動いていたかを出す。"""
        stamp = tmp_path / "動いている印.txt"
        stamp.write_text("08/17 12:58:20  版 28d2a8d  メモリ 412MB\n", encoding="utf-8")
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)

        label.report_last_alive()

        assert "08/17 12:58:20" in capsys.readouterr().out


class TestTheMemoryReading:
    def test_it_is_a_number_or_nothing(self):
        """測れない環境では黙って省く。ここで落ちては本末転倒。"""
        got = label.memory_in_use()

        assert got is None or (isinstance(got, int) and got > 0)

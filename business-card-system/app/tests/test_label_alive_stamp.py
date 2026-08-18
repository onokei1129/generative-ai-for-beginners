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

生きているあいだ、時刻・メモリ・いまの工程を小さなファイルへ書き続ける。

    08/18 14:00:26  版 0fc8340  メモリ 412MB  開始 OCR 名刺A.pdf
    08/18 14:00:31  版 0fc8340  メモリ 688MB  開始 画像 名刺A.pdf

次に「応答していません」が出たとき、この印を見れば分かる。

    印が進み続けている  → イ（生きている。別の手当てが要る）
    印が止まっている    → ア（プロセスが消えている）

## 08/18 に届いた印から直したこと

はじめは1行への上書きにしていた。届いたのはこの1行だけだった。

    08/18 14:00:31  版 0fc8340 08/17 08:36

ここから2つ分かった。どちらも、この仕掛けの狙いを損なっていた。

1. **メモリが出ていない。** Windows の測り方が誤っていて、常に測れない
   ままだった（`GetCurrentProcess` の返り値の型を指定していなかったため、
   64ビットの取っ手が欠けて渡り、呼び出しが必ず失敗する）。落ちる原因と
   してメモリ不足を疑っているのに、肝心のメモリだけが空だった。

2. **1行では、アとイを分けられない。** 印が止まっているかどうかは、画面に
   「応答していません」が出ている**その最中に**見に行かないと判らない。
   落ちたあとで受け取っても、時刻が1つあるだけである。

そこで直近ぶん（`ALIVE_KEEP` 行）を残すことにした。1度受け取れば、止まった
時刻・メモリの増え方・最後の工程が、まとめて読める。上書きにしていた理由
（際限なく増やさない）は、行数の上限で引き受ける。
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

    def test_it_keeps_the_recent_ones(self, tmp_path, monkeypatch):
        """1行だけでは、止まったのか進み続けたのかが読めない。

        08/18に届いた印は1行きりで、そこで止まったのか、その後も打たれた
        のかが判らなかった。直近ぶんが残っていれば、1度受け取るだけで済む。
        """
        stamp = tmp_path / "動いている印.txt"
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)

        label.note_alive()
        label.note_alive()
        label.note_alive()

        assert len(stamp.read_text(encoding="utf-8").strip().splitlines()) == 3

    def test_it_stops_growing(self, tmp_path, monkeypatch):
        """際限なく増えては困る。上書きをやめた代わりに行数で切る。"""
        stamp = tmp_path / "動いている印.txt"
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)
        monkeypatch.setattr(label, "ALIVE_KEEP", 5)

        for _ in range(20):
            label.note_alive()

        assert len(stamp.read_text(encoding="utf-8").strip().splitlines()) == 5

    def test_it_keeps_the_newest_and_drops_the_oldest(self, tmp_path, monkeypatch):
        stamp = tmp_path / "動いている印.txt"
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)
        monkeypatch.setattr(label, "ALIVE_KEEP", 3)
        for n in range(5):
            label.append_alive_line(f"{n}行目")

        lines = stamp.read_text(encoding="utf-8").strip().splitlines()

        assert lines == ["2行目", "3行目", "4行目"]

    def test_it_says_what_it_was_doing(self, tmp_path, monkeypatch):
        """止まった印だけで「どの名刺の、どの工程で」まで分かるようにする。"""
        stamp = tmp_path / "動いている印.txt"
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)
        monkeypatch.setattr(label, "LOG_PATH", tmp_path / "ラベル入力ログ.txt")
        label._log_step("開始 OCR 名刺A.pdf")

        label.note_alive()

        assert "開始 OCR 名刺A.pdf" in stamp.read_text(encoding="utf-8")

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

    def test_it_marks_where_this_run_starts(self, tmp_path, monkeypatch):
        """前回ぶんが残るので、区切りが無いと今回との境が読めない。"""
        stamp = tmp_path / "動いている印.txt"
        stamp.write_text("08/17 12:58:20  前回の行\n", encoding="utf-8")
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)

        stop = label.start_heartbeat(seconds=60)
        try:
            text = stamp.read_text(encoding="utf-8")
        finally:
            stop()

        assert "前回の行" in text, "前回ぶんが消えている"
        assert "ここから今回の起動" in text

    def test_reading_it_never_sees_a_blank(self, tmp_path, monkeypatch):
        """動いている最中に開かれる。消してから書くと空が見える。"""
        stamp = tmp_path / "動いている印.txt"
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)
        label.append_alive_line("はじめの行")

        stop = label.start_heartbeat(seconds=0.001)
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                assert stamp.read_text(encoding="utf-8").strip(), "空が見えた"
        finally:
            stop()

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

    def test_the_startup_reports_only_the_last_line(self, tmp_path, monkeypatch, capsys):
        """直近ぶんを丸ごと出すと画面が埋まる。要るのは止まった1行。"""
        stamp = tmp_path / "動いている印.txt"
        stamp.write_text("古い行1\n古い行2\n最後の行\n", encoding="utf-8")
        monkeypatch.setattr(label, "ALIVE_PATH", stamp)

        label.report_last_alive()
        out = capsys.readouterr().out

        assert "最後の行" in out
        assert "古い行1" not in out
        assert str(stamp) in out, "残りの在り処を示していない"


class TestTheMemoryReading:
    def test_it_is_a_number_or_nothing(self):
        """測れない環境では黙って省く。ここで落ちては本末転倒。"""
        got = label.memory_in_use()

        assert got is None or (isinstance(got, int) and got > 0)

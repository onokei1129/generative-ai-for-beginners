"""仕分けは、増えたぶんだけを見る（poc/classify.py）。

スキャンフォルダは増えていく一方で、既にあるファイルの中身は変わらない。
それを毎回すべて判定し直していた。1枚に数秒かかるので、**数枚足すだけでも
全件ぶんの時間を待つ**ことになる（実テストでは200枚を超えている）。

前回の判定を記録に残し、大きさと更新時刻が変わっていないファイルは判定を
省く。差し替えられた場合は更新時刻が変わるので、判定し直しになる。

## コピーも今回判定したぶんだけにする

以前は毎回すべてコピーし直していた。ラベル入力の画面で「これは名刺では
ない」と外した1枚は not-cards へ移されるが、次に仕分けを動かすと同じ
ファイルが戻ってきてしまう。外した判断が消えるうえ、同じ1枚を何度も
突き返されることになる。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

from poc import classify  # noqa: E402


def a_scan(path: Path, size: tuple[int, int] = (1050, 640)) -> Path:
    Image.new("RGB", size, "white").save(path)
    return path


def run(source: Path, record: Path, *extra: str, copy_to: Path | None = None) -> list[str]:
    """仕分けを動かし、判定した（＝判定を省かなかった）ファイル名を返す。"""
    looked: list[str] = []

    def watching(path: Path, use_ocr: bool = True) -> classify.Verdict:
        looked.append(path.name)
        return classify.Verdict(path=path, label="business_card", score=3.0, ratio=1.64)

    argv = ["classify.py", str(source), "--no-ocr", "--record", str(record), *extra]
    if copy_to is not None:
        argv += ["--copy-to", str(copy_to)]

    real_classify, real_argv = classify.classify_file, sys.argv
    classify.classify_file, sys.argv = watching, argv
    try:
        classify.main()
    finally:
        classify.classify_file, sys.argv = real_classify, real_argv
    return looked


class TestItSkipsWhatItAlreadyJudged:
    def test_the_second_run_looks_at_nothing(self, tmp_path: Path):
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        a_scan(source / "b.png")
        record = tmp_path / "記録.json"

        first = run(source, record)
        second = run(source, record)

        assert sorted(first) == ["a.png", "b.png"]
        assert second == [], "同じファイルを判定し直している"

    def test_only_the_added_file_is_looked_at(self, tmp_path: Path):
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        record = tmp_path / "記録.json"
        run(source, record)

        a_scan(source / "b.png")
        again = run(source, record)

        assert again == ["b.png"], "増えたぶん以外も判定している"

    def test_a_replaced_file_is_judged_again(self, tmp_path: Path):
        """差し替えられたら更新時刻が変わる。判定し直す。"""
        source = tmp_path / "scans"
        source.mkdir()
        card = a_scan(source / "a.png")
        record = tmp_path / "記録.json"
        run(source, record)

        a_scan(card, (700, 1400))
        os.utime(card, (card.stat().st_atime + 60, card.stat().st_mtime + 60))

        assert run(source, record) == ["a.png"]

    def test_recheck_looks_at_everything(self, tmp_path: Path):
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        a_scan(source / "b.png")
        record = tmp_path / "記録.json"
        run(source, record)

        assert sorted(run(source, record, "--recheck")) == ["a.png", "b.png"]


class TestTheOutputsStillShowEverything:
    def test_the_csv_lists_the_skipped_ones_too(self, tmp_path: Path):
        """「増えたぶんだけの一覧」になると、全体を見る用途に使えない。"""
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        record = tmp_path / "記録.json"
        csv_out = tmp_path / "sort.csv"
        run(source, record, "--csv", str(csv_out))

        a_scan(source / "b.png")
        run(source, record, "--csv", str(csv_out))

        written = csv_out.read_text(encoding="utf-8-sig")
        assert "a.png" in written, "判定を省いたファイルが一覧から消えている"
        assert "b.png" in written


class TestItDoesNotBringBackRemovedCards:
    def test_only_the_newly_judged_are_copied(self, tmp_path: Path):
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        record = tmp_path / "記録.json"
        cards = tmp_path / "real-cards"
        run(source, record, copy_to=cards)
        assert (cards / "a.png").exists()

        # 利用者が「これは名刺ではない」で外した状態にする。
        (cards / "a.png").unlink()
        a_scan(source / "b.png")
        run(source, record, copy_to=cards)

        assert not (cards / "a.png").exists(), "外した1枚が戻ってきている"
        assert (cards / "b.png").exists()


class TestTheRecordSurvivesTrouble:
    def test_a_broken_record_does_not_stop_the_run(self, tmp_path: Path):
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        record = tmp_path / "記録.json"
        record.write_text("これはJSONではない", encoding="utf-8")

        assert run(source, record) == ["a.png"], "壊れた記録で止まっている"

    def test_the_record_keeps_the_verdict(self, tmp_path: Path):
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        record = tmp_path / "記録.json"
        run(source, record)

        kept = json.loads(record.read_text(encoding="utf-8"))
        entry = next(iter(kept.values()))
        assert entry["label"] == "business_card"
        assert "size" in entry and "mtime" in entry


class TestALockedOutputDoesNotFailTheRun:
    """一覧を書けなくても、仕分けは失敗にしない。

    実テストで、2回目の仕分けがこれで止まった:

        PermissionError: [Errno 13] Permission denied: 'sort.md'
        [エラー] 仕分けに失敗しました。

    判定も記録もコピーも終わったあとの話で、失敗したのは一覧の書き出しだけ
    だった。それでも全体が失敗として終わっていた。Windows では、そのファイルを
    別のソフトで開いていると書き込めない。
    """

    def locked(self, tmp_path: Path) -> Path:
        out = tmp_path / "sort.md"
        out.write_text("開いたまま", encoding="utf-8")
        return out

    def test_it_keeps_going(self, tmp_path: Path, monkeypatch):
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        record = tmp_path / "記録.json"
        report = self.locked(tmp_path)

        def denied(_: Path) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(classify, "write_report", lambda *a, **k: denied(report))

        # 例外で終わらず、判定は行われる。
        assert run(source, record, "--report", str(report)) == ["a.png"]

    def test_the_record_is_still_kept(self, tmp_path: Path, monkeypatch):
        """記録が残らないと、次に動かしてまた全件を判定し直すことになる。"""
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        record = tmp_path / "記録.json"
        report = self.locked(tmp_path)

        monkeypatch.setattr(
            classify,
            "write_report",
            lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "Permission denied")),
        )
        run(source, record, "--report", str(report))

        assert record.exists(), "記録が残っていない"

    def test_it_says_what_to_do(self, tmp_path: Path, capsys):
        out = tmp_path / "sort.md"

        def denied(_: Path) -> None:
            raise PermissionError(13, "Permission denied")

        assert classify.write_or_warn("レポート", out, denied) is False
        said = capsys.readouterr().err
        assert "開いていませんか" in said, "直し方を出していない"
        assert "仕分け自体は終わっています" in said, "何が終わったのかを出していない"

    def test_a_real_unwritable_path_is_caught(self, tmp_path: Path):
        """作り物の失敗だけでなく、実際に書けない先でも止まらないこと。"""
        source = tmp_path / "scans"
        source.mkdir()
        a_scan(source / "a.png")
        record = tmp_path / "記録.json"
        # フォルダを書き出し先に指定すると、実際に書き込みが失敗する。
        blocked = tmp_path / "フォルダ"
        blocked.mkdir()

        assert run(source, record, "--report", str(blocked)) == ["a.png"]
        assert record.exists(), "記録が残っていない"

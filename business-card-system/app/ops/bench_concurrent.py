"""取込ワーカーが動いている最中の検索応答を測る。

    PYTHONPATH=src .venv/bin/python ops/bench_concurrent.py --readers 5 --seconds 30

要件§5 の想定は利用者10名（うち同時取込2名）。
検索だけを単独で測っても、実運用で問題になるのは
「誰かが名刺を取り込んでいる最中に、別の人が検索する」場面である。
OCRはCPUを使い切るため、その裏で検索が遅くならないかを確認する。

`ops/bench.py` が単独時の値、本スクリプトが競合時の値。両方を比べて判断する。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcards.db import SessionLocal  # noqa: E402
from bcards.services import search  # noqa: E402

QUERIES = ["佐藤", "テクノロジー", "株式会社", "03-1", "山田"]


def build_sample_image() -> bytes:
    """取込負荷をかけるための名刺画像。loadgen と同じ描画を使う。"""
    import io
    import random

    from loadgen import _person_fields, _render  # 同じ ops/ 配下

    image = _render(_person_fields(random.Random(1), 1), 1)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def reader_loop(stop: threading.Event, durations: list[float], index: int) -> None:
    """検索を繰り返し、1回ごとの所要時間を記録する。"""
    position = index
    while not stop.is_set():
        keyword = QUERIES[position % len(QUERIES)]
        position += 1
        start = time.perf_counter()
        try:
            with SessionLocal() as db:
                query = search.build_query(db, {"q": keyword})
                query.count()
                query.limit(50).all()
        except Exception as exc:  # 接続断などは記録だけして続ける
            print(f"  読み取りエラー: {exc}", file=sys.stderr)
            continue
        durations.append(time.perf_counter() - start)


def importer_loop(stop: threading.Event, counter: dict, sample: bytes) -> None:
    """裏でOCRを回し続ける（取込中の負荷を再現する）。"""
    from bcards.services.images import process_file
    from bcards.services.ocr import recognize_card

    while not stop.is_set():
        try:
            cards = process_file(sample, "bench.jpg")
            for card in cards:
                recognize_card(card.ocr_image)
                counter["done"] += 1
                if stop.is_set():
                    break
        except Exception as exc:
            print(f"  取込エラー: {exc}", file=sys.stderr)
            counter["errors"] += 1


def summarize(label: str, durations: list[float]) -> dict:
    if not durations:
        return {"label": label, "count": 0}
    ordered = sorted(durations)
    return {
        "label": label,
        "count": len(ordered),
        "median": statistics.median(ordered),
        "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "worst": ordered[-1],
    }


def run(readers: int, seconds: float, importers: int, sample: bytes | None) -> dict:
    stop = threading.Event()
    durations: list[float] = []
    counter = {"done": 0, "errors": 0}
    threads: list[threading.Thread] = []

    for index in range(readers):
        thread = threading.Thread(target=reader_loop, args=(stop, durations, index), daemon=True)
        thread.start()
        threads.append(thread)

    if sample is not None:
        for _ in range(importers):
            thread = threading.Thread(target=importer_loop, args=(stop, counter, sample), daemon=True)
            thread.start()
            threads.append(thread)

    time.sleep(seconds)
    stop.set()
    for thread in threads:
        thread.join(timeout=30)

    return {"durations": list(durations), "imported": counter["done"], "errors": counter["errors"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--readers", type=int, default=5, help="同時に検索する人数")
    parser.add_argument("--importers", type=int, default=2, help="同時に取込を行う人数（要件§5の想定は2）")
    parser.add_argument("--seconds", type=float, default=30, help="各条件の測定秒数")
    parser.add_argument("--out", help="Markdown レポートの出力先")
    args = parser.parse_args()

    sample = build_sample_image()

    print(f"条件1: 検索{args.readers}人のみ（{args.seconds:.0f}秒）")
    baseline = run(args.readers, args.seconds, 0, None)
    base = summarize("検索のみ", baseline["durations"])
    print(f"  {base['count']} 回 / 中央値 {base['median']*1000:.0f}ms / p95 {base['p95']*1000:.0f}ms / 最悪 {base['worst']*1000:.0f}ms")

    print(f"条件2: 検索{args.readers}人 ＋ 取込{args.importers}人（{args.seconds:.0f}秒）")
    loaded = run(args.readers, args.seconds, args.importers, sample)
    busy = summarize("検索＋取込", loaded["durations"])
    print(f"  {busy['count']} 回 / 中央値 {busy['median']*1000:.0f}ms / p95 {busy['p95']*1000:.0f}ms / 最悪 {busy['worst']*1000:.0f}ms")
    print(f"  裏で処理した名刺: {loaded['imported']} 枚 / エラー {loaded['errors']} 件")

    lines = [
        "# 同時アクセス時の検索応答",
        "",
        f"- 検索する人数: {args.readers}",
        f"- 同時に取込を行う人数: {args.importers}（要件§5の想定）",
        f"- 各条件の測定時間: {args.seconds:.0f} 秒",
        "",
        "| 条件 | 実行回数 | 中央値 | p95 | 最悪値 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in (base, busy):
        if row["count"]:
            lines.append(
                f"| {row['label']} | {row['count']} | {row['median']*1000:.0f} ms | "
                f"{row['p95']*1000:.0f} ms | {row['worst']*1000:.0f} ms |"
            )
    if base["count"] and busy["count"]:
        ratio = busy["median"] / base["median"]
        lines += ["", f"取込が走っている間、検索の中央値は **{ratio:.1f}倍** になった。", ""]
    lines.append(f"裏で処理した名刺: {loaded['imported']} 枚 / エラー {loaded['errors']} 件")

    report = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\nレポート: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

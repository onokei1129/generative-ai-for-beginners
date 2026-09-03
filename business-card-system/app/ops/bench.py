"""検索・一覧・容量集計の応答時間を測る（非機能要件の確定用）。

    PYTHONPATH=src .venv/bin/python ops/bench.py

`ops/loadgen.py` で本番相当のデータを投入したあとに実行する。
非機能要件「検索応答時間：1万件規模で2秒以内」（screens-and-functions-v0.3.md §5）の
確認に使う。

DB へのクエリだけでなく、画面表示に必要な処理（件数カウント・容量集計）も測る。
実際に遅くなるのはクエリ本体ではなく、周辺の集計であることが多いため。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.db import SessionLocal  # noqa: E402
from bcards.models import BusinessCard, CardImage, Company, Person  # noqa: E402
from bcards.services import search, storage  # noqa: E402

PAGE_SIZE = 50


def timed(label: str, func, repeat: int = 5) -> dict:
    """何度か実行し、中央値と最悪値を返す。1回だけだとキャッシュの影響を受ける。"""
    durations: list[float] = []
    result = None
    for _ in range(repeat):
        start = time.perf_counter()
        result = func()
        durations.append(time.perf_counter() - start)
    return {
        "label": label,
        "median": statistics.median(durations),
        "worst": max(durations),
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--out", help="Markdown レポートの出力先")
    args = parser.parse_args()

    rows: list[dict] = []

    with SessionLocal() as db:
        counts = {
            "名刺": db.query(BusinessCard).count(),
            "人物": db.query(Person).count(),
            "会社": db.query(Company).count(),
            "画像": db.query(CardImage).count(),
        }
        print("データ量: " + " / ".join(f"{k} {v:,}" for k, v in counts.items()))
        print()

        def page(params: dict):
            return search.build_query(db, params).limit(PAGE_SIZE).all()

        def page_with_count(params: dict):
            query = search.build_query(db, params)
            return query.count(), query.limit(PAGE_SIZE).all()

        cases = [
            ("一覧の1ページ目（条件なし）", lambda: page({})),
            ("一覧＋総件数（画面と同じ）", lambda: page_with_count({})),
            ("キーワード検索（氏名）", lambda: page_with_count({"q": "佐藤"})),
            ("キーワード検索（会社名）", lambda: page_with_count({"q": "テクノロジー"})),
            ("キーワード検索（電話番号）", lambda: page_with_count({"q": "03-1"})),
            ("キーワード検索（該当なし）", lambda: page_with_count({"q": "存在しない文字列XYZ"})),
            ("期間で絞り込み", lambda: page_with_count({"from": "2026-01-01", "to": "2026-06-30"})),
            ("氏名順に並べ替え", lambda: page_with_count({"sort": "name"})),
            ("最新のみ＋キーワード", lambda: page_with_count({"q": "株式会社", "latest_only": "1"})),
        ]
        for label, func in cases:
            rows.append(timed(label, func, args.repeat))

        # 画面表示に必要な周辺処理
        rows.append(timed("会社の選択肢（絞り込みプルダウン）",
                          lambda: db.query(Company).order_by(Company.name).limit(500).all(), args.repeat))

    # ストレージ容量の集計はDBの外。ホーム画面と管理画面で毎回呼ばれる
    rows.append(timed("ストレージ使用量の集計", storage.total_bytes, min(args.repeat, 3)))

    lines = [
        "# 応答時間の実測",
        "",
        "| 項目 | 件数 |",
        "| --- | --- |",
    ]
    lines += [f"| {k} | {v:,} |" for k, v in counts.items()]
    lines += [
        "",
        "| 処理 | 中央値 | 最悪値 | 判定（2秒以内） |",
        "| --- | --- | --- | --- |",
    ]
    worst_overall = 0.0
    for row in rows:
        ok = "OK" if row["worst"] < 2.0 else "**NG**"
        worst_overall = max(worst_overall, row["worst"])
        lines.append(
            f"| {row['label']} | {row['median'] * 1000:.0f} ms | {row['worst'] * 1000:.0f} ms | {ok} |"
        )
        print(f"{row['label']:<34} 中央値 {row['median'] * 1000:7.0f} ms  最悪 {row['worst'] * 1000:7.0f} ms")

    lines += ["", f"最も遅い処理: {worst_overall * 1000:.0f} ms", ""]
    report = "\n".join(lines) + "\n"

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\nレポート: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

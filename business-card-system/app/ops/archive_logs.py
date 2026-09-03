"""監査ログのアーカイブと期限切れの破棄（要件§9、open-issues 論点H）。

    python ops/archive_logs.py [--dry-run] [--all]

日次バッチとして実行する想定。既定では1回の実行で最大 5,000 件を退避する。
`--all` を付けると対象がなくなるまで繰り返す（初回や、長く運用したあとの一括処理向け）。

保持期間・アーカイブ期間は管理画面のシステム設定
（`audit_log_retention_days` / `audit_log_archive_after_days`）で変更する。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datetime import timedelta  # noqa: E402

from bcards.db import SessionLocal  # noqa: E402
from bcards.models import utcnow  # noqa: E402
from bcards.services import log_archive  # noqa: E402
from bcards.settings_store import get_setting  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="対象件数を表示するだけで変更しない")
    parser.add_argument("--all", action="store_true", help="対象がなくなるまで繰り返す")
    args = parser.parse_args()

    with SessionLocal() as db:
        archive_days = int(get_setting(db, "audit_log_archive_after_days") or 0)
        retention_days = int(get_setting(db, "audit_log_retention_days") or 0)
        print(f"アーカイブへ移すまで: {archive_days or '移さない'} 日")
        print(f"保持期間            : {retention_days or '無期限'} 日")

        if archive_days <= 0:
            print("アーカイブは無効です。処理をスキップします。")
            return 0

        cutoff = utcnow() - timedelta(days=archive_days)
        pending = log_archive.archive_candidates(db, cutoff)
        print(f"対象の監査ログ      : {pending} 件（{cutoff:%Y-%m-%d} より前）")

        if args.dry_run:
            print("--dry-run のため変更しませんでした。")
            return 0

        total = 0
        while True:
            archive = log_archive.archive_audit_logs(db)
            if archive is None:
                break
            db.commit()
            total += archive.row_count
            print(
                f"  退避: {archive.row_count} 件 "
                f"({archive.period_from:%Y-%m-%d} 〜 {archive.period_to:%Y-%m-%d}) "
                f"-> {archive.storage_key}"
            )
            if not args.all:
                break

        purged = log_archive.purge_expired_archives(db)
        if purged:
            db.commit()
            for archive in purged:
                print(f"  破棄: {archive.row_count} 件 (〜{archive.period_to:%Y-%m-%d})")

        print(f"アーカイブ {total} 件 / 破棄 {sum(a.row_count for a in purged)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""復元後の整合性チェック。

    python ops/verify.py [--sample 200]

DBに登録されている画像レコードに対して、実体がストレージに存在するかを確認する。
バックアップからの復元訓練（operations-guide.md）で、
「DBは戻ったが画像が戻っていない」状態を検出するために使う。

終了コードは 0（問題なし）/ 1（欠損あり）。cron や CI から判定できる。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.config import settings  # noqa: E402
from bcards.db import SessionLocal  # noqa: E402
from bcards.models import CardImage, ImportFile  # noqa: E402
from bcards.services import storage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=0, help="確認する件数の上限（0で全件）")
    args = parser.parse_args()

    print(f"データベース : {settings.database_url.split('@')[-1]}")
    print(f"ストレージ   : {settings.storage_backend}")
    print()

    missing: list[tuple[str, str]] = []
    checked = 0

    with SessionLocal() as db:
        query = db.query(CardImage).order_by(CardImage.created_at.desc())
        if args.sample:
            query = query.limit(args.sample)
        images = query.all()
        for image in images:
            checked += 1
            if not storage.exists(image.storage_key):
                missing.append(("card_image", image.storage_key))

        # 処理待ち・処理中のキューファイルは、実体がないと再処理できない
        pending = (
            db.query(ImportFile).filter(ImportFile.status.in_(("queued", "processing"))).all()
        )
        for import_file in pending:
            checked += 1
            if not storage.exists(import_file.storage_key):
                missing.append(("import_file", import_file.storage_key))

        counts = {
            "名刺": db.query(CardImage).count(),
            "取込キュー(未処理)": len(pending),
        }

    for label, value in counts.items():
        print(f"{label}: {value}")
    print(f"確認した実体: {checked} 件")

    if missing:
        print(f"\n実体が見つからない画像が {len(missing)} 件あります:")
        for table, key in missing[:20]:
            print(f"  {table}: {key}")
        if len(missing) > 20:
            print(f"  ... 他 {len(missing) - 20} 件")
        return 1

    print("\n欠損はありません。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

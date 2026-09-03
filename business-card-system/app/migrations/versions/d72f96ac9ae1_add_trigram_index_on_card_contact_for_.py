"""キーワード検索のための連絡先へのトライグラム索引

Revision ID: d72f96ac9ae1
Revises: cf5130012274
Create Date: 2026-07-28 06:23:13.288385

名刺10万件で実測したところ、キーワード検索の最悪値が 2.2 秒となり、
非機能要件（2秒以内）を超えていた（capacity-report-2026-07.md）。

原因は `card_contact.value_raw` の部分一致（ILIKE '%…%'）だった。
名刺10万件に対して連絡先は40万件あり、ここの全走査が支配的になる。
この索引1本で最悪値が 2.2秒 → 0.4秒 になる。

**効くのはこの索引だけ。** 氏名・会社名などの条件は複数テーブルにまたがる OR のため、
PostgreSQL は結合してから絞り込む計画を選ぶ。列ごとに索引を張っても使われない
（実測でも、連絡先以外に6本追加しても数値は変わらなかった）。

PostgreSQL 専用。SQLite では GIN も pg_trgm も無いため何もしない。

pg_trgm は PostgreSQL 13 以降は trusted 拡張のため、データベースへの CREATE 権限が
あれば作成できる（スーパーユーザーは不要）。ただしマネージドサービスでは
拡張の作成が制限されていることがあるため、失敗しても続行する作りにしてある。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd72f96ac9ae1'
down_revision: Union[str, Sequence[str], None] = 'cf5130012274'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_card_contact_value_trgm"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # 拡張の作成が許されていない環境（マネージドサービス等）でも
    # マイグレーション全体を失敗させたくないため、索引だけ見送る。
    # begin_nested() でセーブポイントを張り、失敗してもトランザクションを続行できるようにする。
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except Exception as exc:
        print(
            "pg_trgm 拡張を作成できませんでした。検索用の索引は作成せず先へ進みます。\n"
            f"  理由: {exc}\n"
            "  権限のある利用者で次を実行したあと、alembic upgrade head をやり直してください。\n"
            "    CREATE EXTENSION pg_trgm;\n"
            "  索引が無くても動作しますが、名刺が数万件を超えると検索が遅くなります。"
        )
        return

    op.execute(
        sa.text(
            f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
            "ON card_contact USING gin (value_raw gin_trgm_ops)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(sa.text(f"DROP INDEX IF EXISTS {INDEX_NAME}"))

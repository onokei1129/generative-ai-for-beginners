"""add import_file_id to import_item

Revision ID: 1257491253b2
Revises: eca5a1c29385
Create Date: 2026-07-28 01:37:59.945560

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1257491253b2'
down_revision: Union[str, Sequence[str], None] = 'eca5a1c29385'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FK_NAME = "fk_import_item_import_file_id"


def upgrade() -> None:
    """取込明細に、由来するキューファイルの参照を追加する。"""
    with op.batch_alter_table("import_item") as batch:
        batch.add_column(sa.Column("import_file_id", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            FK_NAME, "import_file", ["import_file_id"], ["import_file_id"]
        )
    op.create_index(
        op.f("ix_import_item_import_file_id"), "import_item", ["import_file_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_import_item_import_file_id"), table_name="import_item")
    with op.batch_alter_table("import_item") as batch:
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.drop_column("import_file_id")

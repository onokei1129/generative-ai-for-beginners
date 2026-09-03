"""Alembic の実行環境。

接続先はアプリと同じ BCARDS_DATABASE_URL を使う。
alembic.ini に接続文字列を書かないことで、環境ごとの設定を一箇所に保つ。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards import models  # noqa: E402,F401  モデルを読み込んで metadata に登録する
from bcards.config import settings  # noqa: E402
from bcards.db import Base  # noqa: E402

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# モデル定義に持たせず、マイグレーションで直接作る索引。
# PostgreSQL 固有の構文（GIN + pg_trgm）でSQLiteには作れないため、
# モデル側に書くと SQLite の挙動まで変わってしまう。
# 自動生成の比較対象から外し、「モデルに無い＝削除すべき」と誤検出させない。
MIGRATION_ONLY_INDEXES = {"ix_card_contact_value_trgm"}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "index" and name in MIGRATION_ONLY_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
            # SQLite は ALTER TABLE が限定的なため、テーブル再作成方式で適用する
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

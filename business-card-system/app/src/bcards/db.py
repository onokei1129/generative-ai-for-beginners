"""データベース接続。"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

IS_SQLITE = settings.database_url.startswith("sqlite")

connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine_options: dict = {"connect_args": connect_args, "future": True}
if not IS_SQLITE:
    # 本番DB（PostgreSQL等）向け。切断済み接続を掴まないよう毎回確認する
    engine_options.update(
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=1800,
    )
engine = create_engine(settings.database_url, **engine_options)

if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # 取込ワーカーとWebリクエストが同時にアクセスするため、
        # WALモードとロック待ちを設定する（本番でPostgreSQLにする場合は不要）
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """開発・テスト用にテーブルを作る。

    本番では Alembic のマイグレーション（alembic upgrade head）で管理するため、
    BCARDS_AUTO_CREATE_TABLES=0 にしてこの処理を無効にする。
    """
    from . import models  # noqa: F401  モデル登録のため

    if not settings.auto_create_tables:
        return
    Base.metadata.create_all(bind=engine)

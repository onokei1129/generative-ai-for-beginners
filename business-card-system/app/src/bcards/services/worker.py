"""取込ワーカー（キュー方式）。

アプリと同じプロセス内のスレッドとして動かすことも、
別プロセス（app/worker.py）として動かすこともできる。
将来 Celery / SQS 等へ移す場合も、置き換えるのはこのファイルだけで済む。
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid

from ..config import settings
from ..db import SessionLocal
from . import queue as import_queue
from .importer import process_import_file

logger = logging.getLogger("bcards.worker")


def worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def process_one(identifier: str) -> bool:
    """キューから1件取り出して処理する。処理したら True。"""
    with SessionLocal() as db:
        import_file = import_queue.claim_next(db, identifier)
        if import_file is None:
            return False

        logger.info("取込開始 file=%s name=%s", import_file.import_file_id, import_file.source_file_name)
        try:
            error = process_import_file(db, import_file)
        except Exception as exc:  # ワーカーは落とさない
            logger.exception("取込処理で予期しないエラー: %s", exc)
            db.rollback()
            error = f"取込処理でエラーが発生しました: {exc}"
        import_queue.complete(db, import_file, error=error)
        logger.info(
            "取込完了 file=%s status=%s", import_file.import_file_id, import_file.status
        )
        return True


def run_forever(stop_event: threading.Event, identifier: str | None = None) -> None:
    """キューを監視し続ける。stop_event がセットされるまで動く。"""
    identifier = identifier or worker_id()
    logger.info("取込ワーカーを開始しました id=%s", identifier)
    last_sweep = 0.0
    while not stop_event.is_set():
        try:
            worked = process_one(identifier)
        except Exception as exc:  # DB接続断など
            logger.exception("ワーカーループでエラー: %s", exc)
            worked = False

        now = time.monotonic()
        if now - last_sweep > 60:
            last_sweep = now
            try:
                with SessionLocal() as db:
                    recovered = import_queue.requeue_stale(db)
                if recovered:
                    logger.warning("停止したワーカーの処理中ファイルを %d 件戻しました", recovered)
            except Exception:  # pragma: no cover
                logger.exception("滞留ファイルの回収に失敗しました")

        if not worked:
            stop_event.wait(settings.worker_poll_seconds)
    logger.info("取込ワーカーを停止しました id=%s", identifier)


class WorkerPool:
    """アプリ内でワーカースレッドを起動・停止する。"""

    def __init__(self, size: int | None = None) -> None:
        self.size = max(1, size or settings.worker_concurrency)
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        if self.threads:
            return
        for index in range(self.size):
            thread = threading.Thread(
                target=run_forever,
                args=(self.stop_event, f"{worker_id()}-{index}"),
                name=f"bcards-worker-{index}",
                daemon=True,
            )
            thread.start()
            self.threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=timeout)
        self.threads.clear()

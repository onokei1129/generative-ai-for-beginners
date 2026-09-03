#!/usr/bin/env python
"""取込ワーカーを別プロセスで動かす。

    BCARDS_WORKER_ENABLED=0 ./run.sh          # Webはワーカーを起動しない
    PYTHONPATH=src ./.venv/bin/python worker.py   # ワーカーを別プロセスで起動

Ctrl-C（SIGINT）または SIGTERM で、処理中のファイルを終えてから停止する。
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bcards.config import settings  # noqa: E402
from bcards.db import init_db  # noqa: E402
from bcards.services.worker import run_forever, worker_id  # noqa: E402


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()

    stop_event = threading.Event()

    def handle_signal(signum, frame):  # noqa: ANN001, ARG001
        logging.getLogger("bcards.worker").info("停止シグナルを受け取りました。処理中のファイルを完了させます。")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    threads = []
    for index in range(max(1, settings.worker_concurrency)):
        thread = threading.Thread(
            target=run_forever, args=(stop_event, f"{worker_id()}-{index}"), daemon=False
        )
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()

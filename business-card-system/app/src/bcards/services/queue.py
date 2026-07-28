"""取込キュー（要件§3「一時的な大量取込にも対応する」）。

アップロードはファイルをストレージへ保存してキューに積むだけで即座に応答し、
実際の画像処理とOCRはワーカーが取り出して実行する。

キューはDBテーブル（import_file）で実装している。10名規模ではこれで十分で、
外部のキューサービスに置き換える場合も claim_next / complete の実装を
差し替えるだけでよい。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    FILE_DONE,
    FILE_ERROR,
    FILE_PROCESSING,
    FILE_QUEUED,
    ImportFile,
    ImportItem,
    ImportJob,
    User,
    utcnow,
)
from . import storage

MAX_ATTEMPTS = 3


def enqueue_files(
    db: Session, user: User, files: list[tuple[str, bytes]], *, source: str
) -> ImportJob:
    """アップロードされたファイルを保存し、キューに積む。"""
    job = ImportJob(created_by=user.user_id, file_count=len(files), status=FILE_QUEUED)
    db.add(job)
    db.flush()

    for filename, data in files:
        key = storage.put_bytes(data, suffix=_suffix_of(filename), prefix="uploads")
        db.add(
            ImportFile(
                import_job_id=job.import_job_id,
                source_file_name=filename,
                storage_key=key,
                byte_size=len(data),
                source=source,
                status=FILE_QUEUED,
            )
        )
    db.flush()
    return job


def _suffix_of(filename: str) -> str:
    name = (filename or "").lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ".bin"


def claim_next(db: Session, worker_id: str) -> ImportFile | None:
    """キューから1件を排他的に取り出す。

    UPDATE の WHERE 句に status を含めることで、複数ワーカーが
    同じ行を取得しないようにしている（取得できた行数で判定）。
    """
    candidate = (
        db.query(ImportFile)
        .filter(ImportFile.status == FILE_QUEUED)
        .order_by(ImportFile.created_at)
        .first()
    )
    if candidate is None:
        return None

    result = db.execute(
        update(ImportFile)
        .where(
            ImportFile.import_file_id == candidate.import_file_id,
            ImportFile.status == FILE_QUEUED,
        )
        .values(
            status=FILE_PROCESSING,
            locked_by=worker_id,
            locked_at=utcnow(),
            attempts=ImportFile.attempts + 1,
        )
    )
    db.commit()
    if result.rowcount != 1:
        return None  # 他のワーカーが先に取得した
    db.expire_all()
    return db.get(ImportFile, candidate.import_file_id)


def complete(db: Session, import_file: ImportFile, *, error: str | None = None) -> None:
    import_file.status = FILE_ERROR if error else FILE_DONE
    import_file.error_message = error
    import_file.locked_by = None
    import_file.finished_at = utcnow()
    db.flush()
    refresh_job_status(db, import_file.import_job_id)
    db.commit()


def requeue_stale(db: Session, lease_seconds: int | None = None) -> int:
    """ワーカーが落ちたまま残った処理中の行をキューへ戻す。"""
    lease = timedelta(seconds=lease_seconds or settings.worker_lease_seconds)
    cutoff = utcnow() - lease
    stale = (
        db.query(ImportFile)
        .filter(ImportFile.status == FILE_PROCESSING, ImportFile.locked_at < cutoff)
        .all()
    )
    affected_jobs: set[str] = set()
    for import_file in stale:
        if import_file.attempts >= MAX_ATTEMPTS:
            import_file.status = FILE_ERROR
            import_file.error_message = (
                f"取込処理が {MAX_ATTEMPTS} 回とも完了しませんでした。再アップロードしてください。"
            )
            import_file.finished_at = utcnow()
        else:
            import_file.status = FILE_QUEUED
            import_file.locked_by = None
            import_file.locked_at = None
        affected_jobs.add(import_file.import_job_id)

    if stale:
        db.flush()
        # 打ち切りになったファイルがある場合、ジョブが processing のまま残ると
        # 取込ジョブ画面が自動更新を続けてしまうため、ここで状態を確定させる
        for job_id in affected_jobs:
            refresh_job_status(db, job_id)
        db.commit()
    return len(stale)


def refresh_job_status(db: Session, import_job_id: str) -> None:
    """ジョブ全体の状態を、ファイルと明細の状態から決める。"""
    job = db.get(ImportJob, import_job_id)
    if job is None:
        return
    files = db.query(ImportFile).filter(ImportFile.import_job_id == import_job_id).all()
    if not files:
        return

    statuses = {f.status for f in files}
    if statuses <= {FILE_QUEUED}:
        job.status = "queued"
        job.started_at = None
    elif statuses & {FILE_QUEUED, FILE_PROCESSING}:
        job.status = "processing"
        job.started_at = job.started_at or utcnow()
    else:
        item_error = (
            db.query(ImportItem)
            .filter(ImportItem.import_job_id == import_job_id, ImportItem.status == "error")
            .count()
        )
        if statuses == {FILE_ERROR}:
            job.status = "failed"
        elif FILE_ERROR in statuses or item_error:
            job.status = "partially_done"
        else:
            job.status = "done"
        job.finished_at = job.finished_at or utcnow()
    db.flush()


def queue_stats(db: Session) -> dict[str, Any]:
    counts = {
        status: db.query(ImportFile).filter(ImportFile.status == status).count()
        for status in (FILE_QUEUED, FILE_PROCESSING, FILE_DONE, FILE_ERROR)
    }
    oldest = (
        db.query(ImportFile)
        .filter(ImportFile.status == FILE_QUEUED)
        .order_by(ImportFile.created_at)
        .first()
    )
    counts["oldest_queued_at"] = oldest.created_at if oldest else None
    return counts

"""名刺画像の取込処理（要件§3, §4, §8）。

アップロードされたファイルはキュー（services/queue.py）に積まれ、
ワーカー（services/worker.py）が process_import_file() を呼び出して処理する。
取込待ち → OCR処理中 → 確認待ち → 登録完了／エラー の状態は ImportItem が持つ。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ITEM_ERROR,
    ITEM_OCR,
    ITEM_QUEUED,
    ITEM_REVIEW,
    CardImage,
    ImportFile,
    ImportItem,
    ImportJob,
    OcrResult,
    User,
    utcnow,
)
from ..settings_store import get_setting
from . import storage
from .dedupe import find_candidates
from .images import ProcessedCard, UnsupportedFileError, make_variants, process_file
from .ocr import parse_fields
from .ocr import recognize_card as run_ocr


def create_job(db: Session, user: User, files: list[tuple[str, bytes]]) -> ImportJob:
    job = ImportJob(created_by=user.user_id, file_count=len(files), status=ITEM_QUEUED)
    db.add(job)
    db.flush()
    return job


def process_import_file(db: Session, import_file: ImportFile) -> str | None:
    """キューから取り出したファイル1件を処理する。

    戻り値はエラーメッセージ（正常時は None）。ファイル単位で失敗しても
    他のファイルの処理は続行できるよう、例外はここで受け止める。
    """
    from . import storage

    job = db.get(ImportJob, import_file.import_job_id)
    if job is None:
        return "取込ジョブが見つかりません。"

    try:
        data = storage.get_bytes(import_file.storage_key)
    except FileNotFoundError:
        _error_item(db, job, import_file.source_file_name, "file_missing", "保存されたファイルが見つかりません。")
        return "保存されたファイルが見つかりません。"

    correct = bool(get_setting(db, "image_correction_enabled"))
    try:
        cards = process_file(data, import_file.source_file_name, correct=correct)
    except UnsupportedFileError as exc:
        _error_item(db, job, import_file.source_file_name, "unsupported_format", str(exc))
        return str(exc)
    except Exception as exc:  # 破損ファイルなど
        message = f"ファイルを読み込めませんでした: {exc}"
        _error_item(db, job, import_file.source_file_name, "read_error", message)
        return message

    created_items: list[ImportItem] = []
    for card in cards:
        created_items.append(
            _create_item(db, job, import_file.source_file_name, card, source=import_file.source)
        )
    _detect_front_back(db, created_items)
    db.flush()
    return None


def process_job(db: Session, job: ImportJob, files: list[tuple[str, bytes]], *, source: str) -> None:
    """キューを介さず同期で処理する（seed スクリプトとテスト用）。"""
    job.status = "processing"
    job.started_at = utcnow()
    db.flush()

    correct = bool(get_setting(db, "image_correction_enabled"))
    for filename, data in files:
        try:
            cards = process_file(data, filename, correct=correct)
        except UnsupportedFileError as exc:
            _error_item(db, job, filename, "unsupported_format", str(exc))
            continue
        except Exception as exc:  # 破損ファイルなど
            _error_item(db, job, filename, "read_error", f"ファイルを読み込めませんでした: {exc}")
            continue

        created_items: list[ImportItem] = []
        for card in cards:
            item = _create_item(db, job, filename, card, source=source)
            created_items.append(item)
        _detect_front_back(db, created_items)

    db.flush()
    statuses = {item.status for item in db.query(ImportItem).filter(ImportItem.import_job_id == job.import_job_id)}
    if statuses == {ITEM_ERROR}:
        job.status = "failed"
    elif ITEM_ERROR in statuses:
        job.status = "partially_done"
    else:
        job.status = "done"
    job.finished_at = utcnow()
    db.flush()


def _error_item(db: Session, job: ImportJob, filename: str, code: str, message: str) -> ImportItem:
    item = ImportItem(
        import_job_id=job.import_job_id,
        source_file_name=filename,
        status=ITEM_ERROR,
        error_code=code,
        error_message=message,
    )
    db.add(item)
    db.flush()
    return item


def _create_item(db: Session, job: ImportJob, filename: str, card: ProcessedCard, *, source: str) -> ImportItem:
    item = ImportItem(
        import_job_id=job.import_job_id,
        source_file_name=filename,
        page_no=card.page_no,
        split_index=card.split_index,
        status=ITEM_QUEUED,
    )
    db.add(item)
    db.flush()

    try:
        images = _store_variants(db, item, card, side="front")
        item.status = ITEM_OCR
        db.flush()

        output, parsed = run_ocr(card.ocr_image)
        result = OcrResult(
            import_item_id=item.import_item_id,
            provider=output.provider,
            api_version=output.api_version,
            raw_response={"text": output.text, **output.raw},
            extracted_fields=parsed["fields"],
            field_confidence=parsed["confidence"],
        )
        db.add(result)

        threshold = int(get_setting(db, "duplicate_match_threshold") or 60)
        candidates = [c.as_dict() for c in find_candidates(db, parsed["fields"], threshold=threshold)]
        same_image = _find_same_image(db, images)
        item.duplicate_candidates = {"candidates": candidates, "same_image": same_image}
        item.status = ITEM_REVIEW
    except Exception as exc:  # OCR障害時も取込自体は残し、再処理できるようにする（要件§8）
        item.status = ITEM_ERROR
        item.error_code = "ocr_failed"
        item.error_message = f"OCR処理に失敗しました: {exc}"
    db.flush()
    return item


def _store_variants(db: Session, item: ImportItem, card: ProcessedCard, *, side: str) -> list[CardImage]:
    """原本・表示用・サムネイルを保存する（要件§2）。"""
    stored: list[CardImage] = []
    for variant, (payload, image) in make_variants(card.image, card.ocr_image).items():
        key = storage.put_bytes(payload, suffix=".jpg", prefix=f"cards/{variant}")
        record = CardImage(
            import_item_id=item.import_item_id,
            side=side,
            variant=variant,
            storage_key=key,
            mime_type="image/jpeg",
            original_mime_type=card.original_mime,
            width=image.width,
            height=image.height,
            byte_size=len(payload),
            checksum=storage.checksum(payload),
            correction_applied=card.corrections,
            quality_warning=card.warnings,
        )
        db.add(record)
        stored.append(record)
    db.flush()
    return stored


def _find_same_image(db: Session, images: list[CardImage]) -> dict[str, Any] | None:
    """同一画像の二重取込を検出する（FN-0319）。"""
    originals = [img for img in images if img.variant == "original"]
    if not originals:
        return None
    checksum = originals[0].checksum
    duplicate = (
        db.query(CardImage)
        .filter(
            CardImage.checksum == checksum,
            CardImage.variant == "original",
            CardImage.card_id.isnot(None),
        )
        .first()
    )
    if duplicate is None:
        return None
    return {"card_id": duplicate.card_id, "message": "同じ画像が既に登録されています。"}


def _text_length(db: Session, item: ImportItem) -> int:
    result = (
        db.query(OcrResult)
        .filter(OcrResult.import_item_id == item.import_item_id)
        .order_by(OcrResult.processed_at.desc())
        .first()
    )
    if result is None or not result.raw_response:
        return 0
    return len((result.raw_response.get("text") or "").replace(" ", "").replace("\n", ""))


def _detect_front_back(db: Session, items: list[ImportItem]) -> None:
    """表裏判定（要件§4）。

    1ファイルから2枚検出され、片方の文字量が極端に少ない場合は裏面とみなし、
    表面の名刺画像として統合する。判定は確認画面で利用者が変更できる。
    """
    valid = [item for item in items if item.status == ITEM_REVIEW]
    if len(valid) != 2:
        return
    lengths = [(item, _text_length(db, item)) for item in valid]
    lengths.sort(key=lambda x: x[1], reverse=True)
    (front, front_len), (back, back_len) = lengths
    if front_len < 20 or back_len > front_len * 0.35:
        return

    for image in db.query(CardImage).filter(CardImage.import_item_id == back.import_item_id).all():
        image.import_item_id = front.import_item_id
        image.side = "back"
    db.delete(db.query(OcrResult).filter(OcrResult.import_item_id == back.import_item_id).first())
    db.delete(back)
    db.flush()


def retry_item(db: Session, item: ImportItem) -> None:
    """エラーになった明細を再処理する（要件§8「障害時の再処理方法」）。"""
    images = (
        db.query(CardImage)
        .filter(CardImage.import_item_id == item.import_item_id, CardImage.variant == "original")
        .all()
    )
    if not images:
        item.error_message = "再処理に使える画像が残っていません。再アップロードしてください。"
        db.flush()
        return

    from PIL import Image
    import io

    item.status = ITEM_OCR
    db.flush()
    try:
        image = Image.open(io.BytesIO(storage.get_bytes(images[0].storage_key)))
        output, parsed = run_ocr(image)
        previous = (
            db.query(OcrResult)
            .filter(OcrResult.import_item_id == item.import_item_id)
            .order_by(OcrResult.processed_at.desc())
            .first()
        )
        db.add(
            OcrResult(
                import_item_id=item.import_item_id,
                provider=output.provider,
                api_version=output.api_version,
                raw_response={"text": output.text, **output.raw},
                extracted_fields=parsed["fields"],
                field_confidence=parsed["confidence"],
                retry_count=(previous.retry_count + 1) if previous else 1,
            )
        )
        threshold = int(get_setting(db, "duplicate_match_threshold") or 60)
        item.duplicate_candidates = {
            "candidates": [c.as_dict() for c in find_candidates(db, parsed["fields"], threshold=threshold)],
            "same_image": None,
        }
        item.status = ITEM_REVIEW
        item.error_code = None
        item.error_message = None
    except Exception as exc:
        item.status = ITEM_ERROR
        item.error_code = "ocr_failed"
        item.error_message = f"再処理に失敗しました: {exc}"
    db.flush()


def latest_ocr(db: Session, item: ImportItem) -> OcrResult | None:
    return (
        db.query(OcrResult)
        .filter(OcrResult.import_item_id == item.import_item_id)
        .order_by(OcrResult.processed_at.desc())
        .first()
    )


def manual_fields_from_text(text: str) -> dict[str, Any]:
    return parse_fields(text.splitlines())["fields"]


def storage_usage_percent() -> float:
    used = storage.total_bytes()
    quota = max(1, settings.storage_quota_bytes)
    return round(used / quota * 100, 2)

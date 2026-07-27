"""名刺画像の取込・OCR確認・登録（要件§3, §4, §8, §10）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..db import get_db
from ..deps import current_user, verify_csrf
from ..models import (
    ITEM_ERROR,
    ITEM_REGISTERED,
    ITEM_REVIEW,
    BusinessCard,
    CardImage,
    ImportItem,
    ImportJob,
    Person,
    User,
    utcnow,
)
from ..services.cards import register_card
from ..services.dedupe import find_candidates
from ..services.importer import latest_ocr, retry_item
from ..services.queue import enqueue_files, queue_stats
from ..settings_store import get_setting
from ..web import render

router = APIRouter()

MAX_FILES = 100
MAX_FILE_BYTES = 30 * 1024 * 1024


@router.get("/imports")
def import_jobs(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    jobs = db.query(ImportJob).order_by(ImportJob.created_at.desc()).limit(30).all()
    stats = queue_stats(db)
    items = (
        db.query(ImportItem)
        .filter(ImportItem.status.in_([ITEM_REVIEW, ITEM_ERROR]))
        .order_by(ImportItem.created_at.desc())
        .limit(100)
        .all()
    )
    return render(
        request,
        "import_jobs.html",
        {
            "title": "取込状況",
            "jobs": jobs,
            "items": items,
            "stats": stats,
            "users": {u.user_id: u for u in db.query(User).all()},
        },
    )


@router.get("/imports/upload")
def upload_form(request: Request, user: User = Depends(current_user)):
    return render(request, "upload.html", {"title": "名刺のアップロード"})


@router.post("/imports/upload")
async def upload(
    request: Request,
    csrf_token: str = Form(...),
    source: str = Form("file_upload"),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    verify_csrf(request, csrf_token)
    payloads: list[tuple[str, bytes]] = []
    for upload_file in files[:MAX_FILES]:
        data = await upload_file.read()
        if not data:
            continue
        if len(data) > MAX_FILE_BYTES:
            payloads.append((upload_file.filename or "unknown", b""))
            continue
        payloads.append((upload_file.filename or "unknown", data))

    if not payloads:
        return RedirectResponse("/imports/upload?err=ファイルが選択されていません。", status_code=303)

    # ファイルを保存してキューに積むだけで応答を返す（実処理はワーカー）
    job = enqueue_files(db, user, payloads, source=source)
    log_audit(db, request, user, "import_upload", target_type="import_job", target_id=job.import_job_id,
              detail={"files": len(payloads), "source": source})
    db.commit()
    return RedirectResponse(
        f"/imports/jobs/{job.import_job_id}?msg={len(payloads)}件をキューに登録しました。処理が終わると確認待ちになります。",
        status_code=303,
    )


@router.get("/imports/jobs/{job_id}")
def job_detail(job_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    return render(
        request,
        "import_job_detail.html",
        {"title": "取込ジョブ", "job": job, "auto_refresh": not job.is_finished},
    )


@router.get("/imports/items/{item_id}")
def review_item(item_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.get(ImportItem, item_id)
    if item is None:
        raise HTTPException(status_code=404)

    ocr = latest_ocr(db, item)
    images = db.query(CardImage).filter(
        CardImage.import_item_id == item_id, CardImage.variant == "display"
    ).all()
    candidates_payload = item.duplicate_candidates or {}
    same_image = candidates_payload.get("same_image") if isinstance(candidates_payload, dict) else None

    fields = dict(ocr.extracted_fields) if ocr and ocr.extracted_fields else {}
    # 取込後に別の名刺が登録されている可能性があるため、表示時点で候補を計算し直す（要件§10）
    threshold = int(get_setting(db, "duplicate_match_threshold") or 60)
    candidates = [c.as_dict() for c in find_candidates(db, fields, threshold=threshold)]
    fields.setdefault("exchanged_on", utcnow().strftime("%Y-%m-%d"))
    warnings = []
    for image in db.query(CardImage).filter(
        CardImage.import_item_id == item_id, CardImage.variant == "original"
    ).all():
        if image.quality_warning:
            warnings += image.quality_warning.get("messages", [])

    return render(
        request,
        "review.html",
        {
            "title": "OCR結果の確認",
            "item": item,
            "ocr": ocr,
            "images": images,
            "fields": fields,
            "confidence": (ocr.field_confidence if ocr else {}) or {},
            "candidates": candidates,
            "same_image": same_image,
            "warnings": warnings,
        },
    )


@router.post("/imports/items/{item_id}/register")
async def register_item(item_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.get(ImportItem, item_id)
    if item is None:
        raise HTTPException(status_code=404)

    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    action = form.get("action") or "new_person"

    if action == "cancel":
        item.chosen_action = "cancel"
        item.status = ITEM_ERROR
        item.error_code = "cancelled"
        item.error_message = "利用者が登録を中止しました。"
        log_audit(db, request, user, "import_cancel", target_type="import_item", target_id=item_id)
        db.commit()
        return RedirectResponse("/imports?msg=登録を中止しました。", status_code=303)

    fields = {
        key: (form.get(key) or "").strip()
        for key in (
            "last_name", "first_name", "last_name_kana", "first_name_kana",
            "company_name", "department_name", "title", "card_type",
            "postal_code", "address", "tel", "mobile", "fax", "email", "url",
            "exchanged_on", "note",
        )
    }
    person_id = (form.get("person_id") or "").strip() or None
    target_card_id = (form.get("target_card_id") or "").strip() or None

    if action in ("add_to_person", "overwrite", "replace", "keep_history") and not person_id:
        return RedirectResponse(f"/imports/items/{item_id}?err=対象の人物を選択してください。", status_code=303)
    if action in ("overwrite", "replace") and not target_card_id:
        return RedirectResponse(f"/imports/items/{item_id}?err=対象の名刺を選択してください。", status_code=303)

    image_ids = [
        image.card_image_id
        for image in db.query(CardImage).filter(CardImage.import_item_id == item_id).all()
    ]
    ocr = latest_ocr(db, item)

    try:
        card = register_card(
            db, request, user,
            fields=fields,
            action=action,
            person_id=person_id,
            target_card_id=target_card_id,
            image_ids=image_ids,
            source=form.get("source") or "file_upload",
            reason=(form.get("reason") or "").strip() or None,
            ocr_confidence=(ocr.field_confidence or {}).get("_overall") if ocr else None,
        )
    except ValueError as exc:
        return RedirectResponse(f"/imports/items/{item_id}?err={exc}", status_code=303)

    item.status = ITEM_REGISTERED
    item.card_id = card.card_id
    item.chosen_action = action
    db.commit()
    return RedirectResponse(f"/cards/{card.card_id}?msg=名刺を登録しました。", status_code=303)


@router.post("/imports/items/{item_id}/retry")
async def retry(item_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.get(ImportItem, item_id)
    if item is None:
        raise HTTPException(status_code=404)
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    retry_item(db, item)
    log_audit(db, request, user, "import_retry", target_type="import_item", target_id=item_id)
    db.commit()
    return RedirectResponse(f"/imports/items/{item_id}?msg=再処理しました。", status_code=303)


@router.post("/imports/items/{item_id}/swap-side")
async def swap_side(item_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """表裏判定の手動修正（要件§4）。"""
    item = db.get(ImportItem, item_id)
    if item is None:
        raise HTTPException(status_code=404)
    form = dict(await request.form())
    verify_csrf(request, form.get("csrf_token"))
    for image in db.query(CardImage).filter(CardImage.import_item_id == item_id).all():
        image.side = "back" if image.side == "front" else "front"
    db.commit()
    return RedirectResponse(f"/imports/items/{item_id}?msg=表裏を入れ替えました。", status_code=303)


@router.get("/imports/items/{item_id}/candidates")
def candidate_cards(item_id: str, request: Request, person_id: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    """既存人物の名刺一覧（上書き・置換の対象選択用）。"""
    person = db.get(Person, person_id) if person_id else None
    cards = (
        db.query(BusinessCard)
        .filter(BusinessCard.person_id == person_id, BusinessCard.deleted_at.is_(None))
        .order_by(BusinessCard.is_latest.desc(), BusinessCard.created_at.desc())
        .all()
        if person
        else []
    )
    return render(
        request,
        "candidate_cards.html",
        {"title": "対象名刺の選択", "person": person, "cards": cards, "item_id": item_id},
    )

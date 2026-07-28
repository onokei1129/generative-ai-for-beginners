"""CSV出力（要件§9）。一般利用者・管理者ともに実行できる。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user, verify_csrf
from ..models import BusinessCard, Company, CsvExportLog, User
from ..services import csv_export
from ..services.search import build_query, describe_conditions
from ..settings_store import get_setting
from ..web import render

router = APIRouter()


@router.get("/export")
def export_form(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    params = dict(request.query_params)
    companies = db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.name).all()
    users = db.query(User).order_by(User.display_name).all()
    preview_count = build_query(db, params).count() if params.get("preview") else None
    return render(
        request,
        "export.html",
        {
            "title": "CSV出力",
            "columns": csv_export.COLUMNS,
            "default_columns": csv_export.DEFAULT_COLUMNS,
            "companies": companies,
            "users": users,
            "params": params,
            "preview_count": preview_count,
            "threshold": int(get_setting(db, "csv_large_export_threshold") or 500),
        },
    )


@router.post("/export")
async def export_csv(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    data = dict(form)
    verify_csrf(request, data.get("csrf_token"))

    columns = form.getlist("columns") or csv_export.DEFAULT_COLUMNS
    scope = data.get("scope") or "search_result"
    card_ids = [cid for cid in form.getlist("card_ids") if cid]

    params: dict = {
        "q": data.get("q"),
        "company_id": data.get("company_id"),
        "created_by": data.get("created_by"),
        "from": data.get("from"),
        "to": data.get("to"),
        "latest_only": data.get("latest_only"),
        "sort": data.get("sort"),
    }
    if scope == "selected":
        # 未選択のまま送信された場合に全件出力になってしまわないよう、ここで止める
        if not card_ids:
            return RedirectResponse(
                "/cards?err=出力する名刺が選択されていません。チェックを付けてから実行してください。",
                status_code=303,
            )
        params["card_ids"] = card_ids
    elif scope == "all":
        params = {"sort": data.get("sort")}

    query = build_query(db, params)
    total = query.count()
    threshold = int(get_setting(db, "csv_large_export_threshold") or 500)
    confirmed = data.get("confirmed") == "1"

    # 要件§9：一定件数以上の場合は確認画面を表示する
    if total >= threshold and not confirmed:
        return render(
            request,
            "export_confirm.html",
            {
                "title": "大量出力の確認",
                "total": total,
                "threshold": threshold,
                "columns": columns,
                "scope": scope,
                "params": params,
                "card_ids": card_ids,
                "all_columns": csv_export.COLUMNS,
            },
        )

    # 連絡先はCSVの列（電話・携帯・FAX・メール・URL）で必ず参照する。
    # まとめて読まないと1名刺につき1クエリ発行され、1万件で10秒以上かかる
    cards = query.options(selectinload(BusinessCard.contacts)).all()
    content, file_name, _log = csv_export.export(
        db, request, user, cards, columns,
        scope=scope,
        conditions=describe_conditions(params) | ({"card_ids": len(card_ids)} if card_ids else {}),
        confirmed_large=confirmed,
    )
    db.commit()

    # Excel での文字化けを避けるため UTF-8 BOM 付きで出力する
    payload = content.encode("utf-8-sig")
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/export/history")
def export_history(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """自分のCSV出力履歴。"""
    from ..models import AuditLog

    logs = (
        db.query(CsvExportLog, AuditLog)
        .join(AuditLog, AuditLog.audit_log_id == CsvExportLog.audit_log_id)
        .filter(AuditLog.user_id == user.user_id)
        .order_by(AuditLog.occurred_at.desc())
        .limit(100)
        .all()
    )
    return render(request, "export_history.html", {"title": "CSV出力履歴", "logs": logs})

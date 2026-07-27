"""テンプレート描画のヘルパー。"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .config import BASE_DIR
from .models import CARD_TYPES, CONTACT_TYPES, ITEM_STATUS_LABELS, REGISTER_ACTIONS, SOURCES

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals.update(
    {
        "CARD_TYPES": CARD_TYPES,
        "CONTACT_TYPES": CONTACT_TYPES,
        "ITEM_STATUS_LABELS": ITEM_STATUS_LABELS,
        "REGISTER_ACTIONS": REGISTER_ACTIONS,
        "SOURCES": SOURCES,
        "APP_NAME": "名刺一元管理システム",
    }
)


def render(request: Request, template: str, context: dict[str, Any] | None = None, status_code: int = 200):
    payload: dict[str, Any] = {
        "user": getattr(request.state, "user", None),
        "csrf_token": (getattr(request.state, "session", {}) or {}).get("csrf", ""),
        "flash": request.query_params.get("msg"),
        "error": request.query_params.get("err"),
    }
    payload.update(context or {})
    return templates.TemplateResponse(request, template, payload, status_code=status_code)


def datetime_format(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return value.strftime(fmt) if value else ""


templates.env.filters["dt"] = datetime_format

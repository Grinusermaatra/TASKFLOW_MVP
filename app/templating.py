"""Jinja rendering and small presentation helpers."""

from datetime import date, datetime, timezone

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import ROOT, settings
from app.constants import ROLE_LABELS, STATUS_LABELS, TABS, URGENCY_LABELS
from app.security import CSRF_COOKIE, CSRF_MAX_AGE, new_csrf_token

env = Environment(
    loader=FileSystemLoader(ROOT / "app" / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


def status_label(value: str | None) -> str:
    if value is None:
        return "Nueva"
    return STATUS_LABELS.get(value, value)


def urgency_label(value: str | None) -> str:
    if not value:
        return ""
    return URGENCY_LABELS.get(value, value)


def role_label(value: str | None) -> str:
    if not value:
        return ""
    return ROLE_LABELS.get(value, value)


def format_dt(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def sorted_history(rows):
    return sorted(rows, key=lambda row: (row.created_at, row.id or 0))


def sorted_evidence(rows):
    return sorted(rows, key=lambda row: (row.uploaded_at, row.id or 0))


env.globals["status_label"] = status_label
env.globals["urgency_label"] = urgency_label
env.globals["role_label"] = role_label
env.globals["tabs"] = TABS
env.filters["format_dt"] = format_dt
env.filters["sorted_history"] = sorted_history
env.filters["sorted_evidence"] = sorted_evidence


def current_csrf(request: Request) -> tuple[str, bool]:
    token = request.cookies.get(CSRF_COOKIE)
    if not token or len(token) < 32:
        return new_csrf_token(), True
    return token, False


def _cookie_flags() -> dict:
    return {
        "httponly": False,
        "samesite": "lax",
        "secure": settings.cookie_secure,
        "path": "/",
        "max_age": CSRF_MAX_AGE,
    }


def apply_csrf_cookie(response, request: Request, token: str, is_new: bool):
    if is_new or request.cookies.get(CSRF_COOKIE) != token:
        response.set_cookie(CSRF_COOKIE, token, **_cookie_flags())
    return response


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    token, is_new = current_csrf(request)
    ctx = dict(context or {})
    user = ctx.get("user")
    path = request.url.path
    if path.startswith("/notificaciones"):
        nav = "notificaciones"
    elif path.startswith("/perfil"):
        nav = "perfil"
    else:
        nav = "inicio"
    ctx.setdefault("request", request)
    ctx.setdefault("user", None)
    ctx.setdefault("unread_count", 0)
    ctx.setdefault("flash", request.cookies.get("flash"))
    ctx.setdefault("show_fab", bool(user and user.role == "supervisor"))
    ctx["nav"] = nav
    ctx["csrf_token"] = token
    html = env.get_template(name).render(**ctx)
    response = HTMLResponse(html, status_code=status_code)
    apply_csrf_cookie(response, request, token, is_new)
    if ctx.get("flash"):
        response.delete_cookie("flash", path="/", samesite="lax", secure=settings.cookie_secure)
    response.headers["Cache-Control"] = "no-store"
    return response


def redirect_with_flash(url: str, message: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        "flash",
        message,
        max_age=30,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def wants_json(request: Request) -> bool:
    if request.url.path.startswith("/api"):
        return True
    if request.headers.get("x-requested-with") == "fetch":
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept

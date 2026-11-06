"""Login, logout, and invite registration."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import enforce_csrf, get_current_user, get_db, require_user
from app.models import User
from app.schemas import LoginIn, RegisterIn
from app.security import SESSION_COOKIE, SESSION_MAX_AGE, dump_session, load_invite
from app.services import authenticate, register_from_invite, shell_context
from app.templating import redirect_with_flash, render

router = APIRouter(tags=["auth"])


def set_session(response, user_id: int):
    response.set_cookie(
        SESSION_COOKIE,
        dump_session(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


def clear_session(response):
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        samesite="lax",
        secure=settings.cookie_secure,
        httponly=True,
    )
    return response


def _messages(exc: ValidationError) -> list[str]:
    messages = []
    for error in exc.errors():
        message = error.get("msg", "Dato inválido")
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        messages.append(message)
    return messages or ["Datos inválidos"]


@router.get("/login")
async def login_page(request: Request, user: User | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse("/tareas", status_code=303)
    return render(request, "login.html", {"error": None, "username": ""})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    try:
        data = LoginIn.model_validate({"username": username, "password": password})
    except ValidationError as exc:
        return render(
            request,
            "login.html",
            {"error": _messages(exc)[0], "username": username},
            status_code=422,
        )
    user = await authenticate(db, data.username, data.password)
    if user is None:
        return render(
            request,
            "login.html",
            {"error": "Usuario o contraseña incorrectos", "username": data.username},
            status_code=400,
        )
    response = RedirectResponse("/tareas", status_code=303)
    set_session(response, user.id)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/logout")
async def logout(
    request: Request,
    csrf_token: str = Form(""),
    _: User = Depends(require_user),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    response = RedirectResponse("/login", status_code=303)
    clear_session(response)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/registro/{token}")
async def register_page(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    org_id = load_invite(token)
    if org_id is None:
        return render(
            request,
            "error.html",
            {"status_code": 400, "message": "La invitación no es válida o venció."},
            status_code=400,
        )
    return render(
        request,
        "register.html",
        {"token": token, "errors": [], "form": {"name": "", "username": "", "email": ""}},
    )


@router.post("/registro")
async def register_submit(
    request: Request,
    token: str = Form(""),
    name: str = Form(""),
    username: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    form = {"name": name, "username": username, "email": email}
    org_id = load_invite(token)
    if org_id is None:
        return render(
            request,
            "error.html",
            {"status_code": 400, "message": "La invitación no es válida o venció."},
            status_code=400,
        )
    try:
        data = RegisterIn.model_validate({**form, "password": password})
    except ValidationError as exc:
        return render(
            request,
            "register.html",
            {"token": token, "errors": _messages(exc), "form": form},
            status_code=422,
        )
    user = await register_from_invite(db, org_id, data)
    response = redirect_with_flash("/tareas", "Cuenta creada. Ya puedes trabajar en tus tareas.")
    set_session(response, user.id)
    return response

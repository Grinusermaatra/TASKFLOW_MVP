"""TaskFlow ASGI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import ROOT, settings
from app.database import engine, init_db
from app.routers import api, auth, pages
from app.templating import render, wants_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("taskflow")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.secret_key == "dev-only-change-me":
        logger.warning("SECRET_KEY is the development default. Set SECRET_KEY before deploying.")
    if not settings.smtp_configured:
        logger.info("SMTP is not configured. TaskFlow will keep in-app notifications and skip email.")
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    await init_db()
    logger.info("Database ready (%s)", settings.database_url_normalized.split("://", 1)[0])
    yield
    await engine.dispose()


app = FastAPI(
    title="TaskFlow",
    summary="Asignación de tareas para supervisores y colaboradores.",
    version="1.0.0",
    description=(
        "API multi-tenant de TaskFlow. Las mutaciones exigen la cookie taskflow_csrf "
        "y la cabecera X-CSRF-Token con el mismo valor. La sesión viaja en la cookie "
        "httpOnly taskflow_session."
    ),
    lifespan=lifespan,
)


def _validation_message(exc: RequestValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        message = str(error.get("msg", "Dato inválido"))
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        parts.append(message)
    return " ".join(parts) or "Datos inválidos"


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Ocurrió un error"
    if wants_json(request):
        return JSONResponse({"ok": False, "detail": detail}, status_code=exc.status_code)
    if exc.status_code == 401:
        return _login_redirect()
    return render(
        request,
        "error.html",
        {"status_code": exc.status_code, "message": detail, "user": None},
        status_code=exc.status_code,
    )


def _login_redirect():
    from fastapi.responses import RedirectResponse

    response = RedirectResponse("/login", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    message = _validation_message(exc)
    if wants_json(request) or request.url.path.startswith("/api"):
        return JSONResponse({"ok": False, "detail": message}, status_code=422)
    return render(
        request,
        "error.html",
        {"status_code": 422, "message": message, "user": None},
        status_code=422,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, StarletteHTTPException):
        return await http_exception_handler(request, exc)
    logger.exception("Unhandled error on %s", request.url.path)
    if wants_json(request):
        return JSONResponse({"ok": False, "detail": "Error interno del servidor"}, status_code=500)
    return render(
        request,
        "error.html",
        {"status_code": 500, "message": "Error interno del servidor", "user": None},
        status_code=500,
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/static"):
        response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(api.router)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

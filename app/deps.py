"""Request dependencies: database session, authenticated user, CSRF."""

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import ROLE_SUPERVISOR
from app.database import SessionLocal
from app.models import User
from app.security import CSRF_COOKIE, load_session, tokens_match
import logging

logger = logging.getLogger("taskflow.auth")


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    token = request.cookies.get("taskflow_session")
    if not token:
        return None
    user_id = load_session(token)
    if user_id is None:
        return None
    stmt = select(User).where(User.id == user_id).options(selectinload(User.organization))
    user = (await db.execute(stmt)).scalar_one_or_none()
    return user


async def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


def require_supervisor(user: User) -> None:
    if user.role != ROLE_SUPERVISOR:
        logger.warning(
            "Denied supervisor action user_id=%s org_id=%s role=%s",
            user.id,
            user.org_id,
            user.role,
        )
        raise HTTPException(status_code=403, detail="No tienes permiso para modificar tareas")


async def require_supervisor_user(user: User = Depends(require_user)) -> User:
    require_supervisor(user)
    return user


def enforce_csrf(request: Request, sent: str | None) -> None:
    expected = request.cookies.get(CSRF_COOKIE)
    if not tokens_match(expected, sent):
        raise HTTPException(status_code=403, detail="Token CSRF inválido o ausente")


async def require_csrf_header(request: Request) -> None:
    enforce_csrf(request, request.headers.get("x-csrf-token"))

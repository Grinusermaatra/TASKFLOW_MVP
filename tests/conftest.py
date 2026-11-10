"""Isolated SQLite database for permission tests.

Environment variables are set before the app is imported. The engine and
settings are created at import time, so this file must stay first.
"""

import asyncio
import os
import secrets
import shutil
from pathlib import Path

_TMP = Path("/tmp/taskflow-pytest-8069")
_TMP.mkdir(parents=True, exist_ok=True)
(_TMP / "uploads").mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["SECRET_KEY"] = "pytest-secret-key-not-the-dev-default-value"
os.environ["TASKFLOW_ENV"] = "development"
os.environ["COOKIE_SECURE"] = "false"
os.environ["SEED_ON_STARTUP"] = "0"
os.environ.pop("RENDER", None)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.constants import ROLE_COLABORADOR, ROLE_SUPERVISOR, STATUS_PENDIENTE
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Notification, Organization, Task, TaskEvidence, TaskStatusHistory, User, utcnow
from app.security import hash_password


async def _build_world() -> dict:
    upload = Path(os.environ["UPLOAD_DIR"])
    if upload.exists():
        shutil.rmtree(upload)
    upload.mkdir(parents=True)
    await init_db()
    async with SessionLocal() as session:
        for model in (Notification, TaskEvidence, TaskStatusHistory, Task, User, Organization):
            await session.execute(delete(model))
        await session.commit()

        passwords = {
            "ana": secrets.token_urlsafe(18),
            "luis": secrets.token_urlsafe(18),
            "maria": secrets.token_urlsafe(18),
            "other_supervisor": secrets.token_urlsafe(18),
            "other_collab": secrets.token_urlsafe(18),
        }
        now = utcnow()
        org = Organization(name="Org A", created_at=now)
        other = Organization(name="Org B", created_at=now)
        session.add_all([org, other])
        await session.flush()

        def add_user(org_id, name, username, email, password, role):
            user = User(
                org_id=org_id,
                name=name,
                username=username,
                email=email,
                password_hash=hash_password(password),
                role=role,
                session_version=0,
                created_at=now,
            )
            session.add(user)
            return user

        ana = add_user(org.id, "Ana Ruiz", "ana.supervisor", "ana@example.test", passwords["ana"], ROLE_SUPERVISOR)
        luis = add_user(
            org.id, "Luis Gómez", "luis.colaborador", "luis@example.test", passwords["luis"], ROLE_COLABORADOR
        )
        maria = add_user(
            org.id, "María Pérez", "maria.colaborador", "maria@example.test", passwords["maria"], ROLE_COLABORADOR
        )
        other_supervisor = add_user(
            other.id,
            "Otra Supervisora",
            "otra.supervisor",
            "otra-supervisor@example.test",
            passwords["other_supervisor"],
            ROLE_SUPERVISOR,
        )
        other_collab = add_user(
            other.id,
            "Otro Colaborador",
            "otra.colaborador",
            "otra-colaborador@example.test",
            passwords["other_collab"],
            ROLE_COLABORADOR,
        )
        await session.flush()
        luis_task = Task(
            org_id=org.id,
            title="Inventario original",
            description="Contar cajas",
            urgency="alta",
            assigned_to=luis.id,
            created_by=ana.id,
            status=STATUS_PENDIENTE,
            created_at=now,
        )
        maria_task = Task(
            org_id=org.id,
            title="Tarea de Maria",
            description="Solo Maria",
            urgency="media",
            assigned_to=maria.id,
            created_by=ana.id,
            status=STATUS_PENDIENTE,
            created_at=now,
        )
        other_task = Task(
            org_id=other.id,
            title="Tarea ajena",
            description="Otra organizacion",
            urgency="baja",
            assigned_to=other_collab.id,
            created_by=other_supervisor.id,
            status=STATUS_PENDIENTE,
            created_at=now,
        )
        session.add_all([luis_task, maria_task, other_task])
        await session.commit()
        return {
            "passwords": passwords,
            "ana_id": ana.id,
            "luis_id": luis.id,
            "maria_id": maria.id,
            "luis_task_id": luis_task.id,
            "maria_task_id": maria_task.id,
            "other_task_id": other_task.id,
        }


@pytest.fixture
def world():
    data = asyncio.run(_build_world())
    with TestClient(app) as client:
        data["client"] = client
        yield data

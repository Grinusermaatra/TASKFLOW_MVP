"""Seed one demo organization, three users, and four tasks.

Run from the repository root: python seed.py
The command is idempotent: if the demo supervisor already exists, it exits.
"""

import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.constants import (
    ROLE_COLABORADOR,
    ROLE_SUPERVISOR,
    STATUS_APROBADA,
    STATUS_EN_REVISION,
    STATUS_PENDIENTE,
    STATUS_RECHAZADA,
    TYPE_ASSIGNED,
    TYPE_REJECTED,
    TYPE_REVIEW,
)
from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Notification, Organization, Task, TaskEvidence, TaskStatusHistory, User, utcnow
from app.security import hash_password
from app.uploads import validate_image

SUPERVISOR = {
    "name": "Ana Ruiz",
    "username": "ana.supervisor",
    "email": "ana.supervisor@taskflow.demo",
    "password": "Supervisor123!",
}
LUIS = {
    "name": "Luis Gómez",
    "username": "luis.colaborador",
    "email": "luis.colaborador@taskflow.demo",
    "password": "Colaborador123!",
}
MARIA = {
    "name": "María Pérez",
    "username": "maria.colaborador",
    "email": "maria.colaborador@taskflow.demo",
    "password": "Colaborador123!",
}


def print_credentials() -> None:
    print("Organización: TaskFlow Demo")
    print("Supervisor")
    print(f"  usuario:    {SUPERVISOR['username']}")
    print(f"  contraseña: {SUPERVISOR['password']}")
    print("Colaboradores")
    print(f"  usuario:    {LUIS['username']}")
    print(f"  contraseña: {LUIS['password']}")
    print(f"  usuario:    {MARIA['username']}")
    print(f"  contraseña: {MARIA['password']}")


def write_sample(path: Path, title: str, color: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (640, 480), color)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, 612, 452), radius=28, outline=(255, 255, 255), width=8)
    draw.rectangle((56, 180, 584, 300), fill=(255, 255, 255))
    draw.text((72, 200), "TaskFlow", fill=color)
    draw.text((72, 230), title, fill=(15, 23, 42))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


async def run() -> None:
    await init_db()
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.username == SUPERVISOR["username"]))
        if existing is not None:
            print("La semilla ya existe. No se duplicaron datos.")
            print_credentials()
            return

        now = utcnow()
        org = Organization(name="TaskFlow Demo", created_at=now - timedelta(days=10))
        session.add(org)
        await session.flush()

        ana = User(
            org_id=org.id,
            name=SUPERVISOR["name"],
            username=SUPERVISOR["username"],
            email=SUPERVISOR["email"],
            password_hash=hash_password(SUPERVISOR["password"]),
            role=ROLE_SUPERVISOR,
            created_at=now - timedelta(days=10),
        )
        luis = User(
            org_id=org.id,
            name=LUIS["name"],
            username=LUIS["username"],
            email=LUIS["email"],
            password_hash=hash_password(LUIS["password"]),
            role=ROLE_COLABORADOR,
            created_at=now - timedelta(days=9),
        )
        maria = User(
            org_id=org.id,
            name=MARIA["name"],
            username=MARIA["username"],
            email=MARIA["email"],
            password_hash=hash_password(MARIA["password"]),
            role=ROLE_COLABORADOR,
            created_at=now - timedelta(days=9),
        )
        session.add_all([ana, luis, maria])
        await session.flush()

        folder = settings.upload_path / str(org.id)
        review_name = f"{uuid4().hex}.png"
        approved_name = f"{uuid4().hex}.png"
        rejected_name = f"{uuid4().hex}.png"
        write_sample(folder / review_name, "Vitrina principal", (79, 70, 229))
        write_sample(folder / approved_name, "Precios actualizados", (16, 185, 129))
        write_sample(folder / rejected_name, "Camara incompleta", (225, 29, 72))
        for name in (review_name, approved_name, rejected_name):
            payload = (folder / name).read_bytes()
            validate_image(payload, name, org_id=org.id, user_id=ana.id)

        inventory = Task(
            org_id=org.id,
            title="Revisar inventario de bodega",
            description="Cuenta las cajas de la bodega norte y reporta los faltantes del turno.",
            urgency="alta",
            assigned_to=luis.id,
            created_by=ana.id,
            status=STATUS_PENDIENTE,
            created_at=now - timedelta(days=1),
            due_date=(now + timedelta(days=2)).date(),
        )
        showcase = Task(
            org_id=org.id,
            title="Fotografiar vitrina principal",
            description="Toma una foto de la vitrina ya montada para validar la exhibición de la semana.",
            urgency="media",
            assigned_to=maria.id,
            created_by=ana.id,
            status=STATUS_EN_REVISION,
            created_at=now - timedelta(days=2),
            due_date=(now + timedelta(days=1)).date(),
        )
        prices = Task(
            org_id=org.id,
            title="Actualizar precios de góndola",
            description="Reemplaza las etiquetas de la góndola de lácteos con la lista nueva.",
            urgency="baja",
            assigned_to=luis.id,
            created_by=ana.id,
            status=STATUS_APROBADA,
            created_at=now - timedelta(days=5),
            due_date=(now - timedelta(days=1)).date(),
        )
        cold_room = Task(
            org_id=org.id,
            title="Limpiar cámara de frío",
            description="Deja la cámara de frío sanitizada y fotografía el interior al terminar.",
            urgency="crítica",
            assigned_to=maria.id,
            created_by=ana.id,
            status=STATUS_PENDIENTE,
            created_at=now - timedelta(days=4),
            due_date=now.date(),
        )
        session.add_all([inventory, showcase, prices, cold_room])
        await session.flush()

        def history(task, when, from_status, to_status, actor, comment=None):
            session.add(
                TaskStatusHistory(
                    org_id=org.id,
                    task_id=task.id,
                    from_status=from_status,
                    to_status=to_status,
                    comment=comment,
                    changed_by=actor.id if actor else None,
                    created_at=when,
                )
            )

        history(inventory, inventory.created_at, None, STATUS_PENDIENTE, ana)
        history(showcase, showcase.created_at, None, STATUS_PENDIENTE, ana)
        history(showcase, now - timedelta(hours=20), STATUS_PENDIENTE, STATUS_EN_REVISION, maria, "Vitrina lista para revisión.")
        history(prices, prices.created_at, None, STATUS_PENDIENTE, ana)
        history(prices, now - timedelta(days=4), STATUS_PENDIENTE, STATUS_EN_REVISION, luis)
        history(prices, now - timedelta(days=3), STATUS_EN_REVISION, STATUS_APROBADA, ana)
        history(cold_room, cold_room.created_at, None, STATUS_PENDIENTE, ana)
        history(cold_room, now - timedelta(days=2), STATUS_PENDIENTE, STATUS_EN_REVISION, maria)
        history(
            cold_room,
            now - timedelta(days=1, hours=2),
            STATUS_EN_REVISION,
            STATUS_RECHAZADA,
            ana,
            "La foto no muestra el interior completo de la cámara.",
        )
        history(
            cold_room,
            now - timedelta(days=1),
            STATUS_RECHAZADA,
            STATUS_PENDIENTE,
            ana,
            "La tarea volvió a pendiente para corrección. La evidencia se conserva.",
        )

        session.add_all(
            [
                TaskEvidence(
                    org_id=org.id,
                    task_id=showcase.id,
                    photo_path=f"{org.id}/{review_name}",
                    comment="Vitrina lista para revisión.",
                    uploaded_at=now - timedelta(hours=20),
                    uploaded_by=maria.id,
                ),
                TaskEvidence(
                    org_id=org.id,
                    task_id=prices.id,
                    photo_path=f"{org.id}/{approved_name}",
                    comment="Etiquetas de lácteos reemplazadas.",
                    uploaded_at=now - timedelta(days=4),
                    uploaded_by=luis.id,
                ),
                TaskEvidence(
                    org_id=org.id,
                    task_id=cold_room.id,
                    photo_path=f"{org.id}/{rejected_name}",
                    comment="Foto del pasillo, faltó el fondo.",
                    uploaded_at=now - timedelta(days=2),
                    uploaded_by=maria.id,
                ),
                Notification(
                    org_id=org.id,
                    user_id=luis.id,
                    task_id=inventory.id,
                    type=TYPE_ASSIGNED,
                    message=f"Se te asignó la tarea «{inventory.title}».",
                    is_read=False,
                    created_at=inventory.created_at,
                ),
                Notification(
                    org_id=org.id,
                    user_id=ana.id,
                    task_id=showcase.id,
                    type=TYPE_REVIEW,
                    message=f"{maria.name} envió «{showcase.title}» a revisión.",
                    is_read=False,
                    created_at=now - timedelta(hours=20),
                ),
                Notification(
                    org_id=org.id,
                    user_id=maria.id,
                    task_id=cold_room.id,
                    type=TYPE_REJECTED,
                    message=(
                        f"Tu tarea «{cold_room.title}» fue rechazada y volvió a pendiente. "
                        "Comentario: La foto no muestra el interior completo de la cámara."
                    ),
                    is_read=False,
                    created_at=now - timedelta(days=1),
                ),
            ]
        )
        await session.commit()
        print("Semilla creada.")
        print_credentials()


if __name__ == "__main__":
    asyncio.run(run())

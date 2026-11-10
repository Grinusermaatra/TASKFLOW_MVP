"""Task state machine, notifications, and tenant-scoped queries."""

import logging
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.constants import (
    ROLE_COLABORADOR,
    ROLE_SUPERVISOR,
    STATUS_APROBADA,
    STATUS_EN_REVISION,
    STATUS_PENDIENTE,
    STATUS_RECHAZADA,
    TYPE_APPROVED,
    TYPE_ASSIGNED,
    TYPE_REJECTED,
    TYPE_REVIEW,
)
from app.deps import require_supervisor
from app.emailer import send_email
from app.models import Notification, Organization, Task, TaskEvidence, TaskStatusHistory, User, utcnow
from app.schemas import CreateUserIn, EvidenceOut, HistoryOut, RegisterIn, TaskCreate, TaskDetailOut, TaskOut, TaskUpdate
from app.security import hash_password
from app.uploads import delete_photo, read_limited, resolve_photo, store_image, validate_image

logger = logging.getLogger("taskflow.services")

_TASK_LOAD = (
    selectinload(Task.assignee),
    selectinload(Task.creator),
    selectinload(Task.evidence),
    selectinload(Task.history).selectinload(TaskStatusHistory.actor),
)


def _ordered_history(task: Task) -> list[TaskStatusHistory]:
    return sorted(task.history, key=lambda row: (row.created_at, row.id or 0))


def is_awaiting_rework(task: Task) -> bool:
    """True when a rejection sent the task back to PENDIENTE and it was not resubmitted."""

    if task.status != STATUS_PENDIENTE:
        return False
    awaiting = False
    for row in _ordered_history(task):
        if row.to_status == STATUS_RECHAZADA:
            awaiting = True
        elif row.to_status in {STATUS_EN_REVISION, STATUS_APROBADA}:
            awaiting = False
    return awaiting


def latest_rejection(task: Task) -> TaskStatusHistory | None:
    if not is_awaiting_rework(task):
        return None
    found = None
    for row in _ordered_history(task):
        if row.to_status == STATUS_RECHAZADA:
            found = row
    return found


def task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description,
        urgency=task.urgency,
        status=task.status,
        assigned_to=task.assigned_to,
        assignee_name=task.assignee.name,
        created_by=task.created_by,
        due_date=task.due_date,
        created_at=task.created_at,
        awaiting_rework=is_awaiting_rework(task),
    )


def task_detail_out(task: Task) -> TaskDetailOut:
    base = task_out(task)
    rejection = latest_rejection(task)
    evidence = [
        EvidenceOut(
            id=item.id,
            photo_url=f"/evidencias/{item.id}",
            comment=item.comment,
            uploaded_at=item.uploaded_at,
        )
        for item in sorted(task.evidence, key=lambda row: (row.uploaded_at, row.id or 0))
    ]
    history = [
        HistoryOut(
            id=item.id,
            from_status=item.from_status,
            to_status=item.to_status,
            comment=item.comment,
            changed_by_name=item.actor.name if item.actor else None,
            created_at=item.created_at,
        )
        for item in _ordered_history(task)
    ]
    return TaskDetailOut(
        **base.model_dump(),
        creator_name=task.creator.name,
        evidence=evidence,
        history=history,
        latest_rejection_comment=rejection.comment if rejection else None,
    )


async def unread_count(db: AsyncSession, user: User) -> int:
    value = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.org_id == user.org_id,
            Notification.is_read.is_(False),
        )
    )
    return int(value or 0)


async def shell_context(db: AsyncSession, user: User | None, **extra) -> dict:
    count = await unread_count(db, user) if user is not None else 0
    ctx = {
        "user": user,
        "unread_count": count,
        "today": datetime.now(timezone.utc).date(),
    }
    ctx.update(extra)
    return ctx


def _scoped_tasks(user: User):
    stmt = select(Task).where(Task.org_id == user.org_id)
    if user.role == ROLE_COLABORADOR:
        stmt = stmt.where(Task.assigned_to == user.id)
    return stmt


async def list_tasks(db: AsyncSession, user: User, tab: str, query: str) -> tuple[list[Task], dict[str, int], str]:
    stmt = _scoped_tasks(user).options(selectinload(Task.assignee), selectinload(Task.history))
    text = query.strip()
    if text:
        like = f"%{text}%"
        stmt = stmt.where(or_(Task.title.ilike(like), Task.description.ilike(like)))
    stmt = stmt.order_by(Task.created_at.desc(), Task.id.desc())
    tasks = list((await db.execute(stmt)).scalars().all())
    for task in tasks:
        task.awaiting_rework = is_awaiting_rework(task)
    counts = {
        "pendientes": sum(1 for task in tasks if task.status == STATUS_PENDIENTE),
        "revision": sum(1 for task in tasks if task.status == STATUS_EN_REVISION),
        "aprobadas": sum(1 for task in tasks if task.status == STATUS_APROBADA),
        "rechazadas": sum(1 for task in tasks if task.awaiting_rework),
    }
    if tab in {"", "todas"}:
        return tasks, counts, "todas"
    if tab not in counts:
        tab = "pendientes"
    if tab == "pendientes":
        filtered = [task for task in tasks if task.status == STATUS_PENDIENTE]
    elif tab == "revision":
        filtered = [task for task in tasks if task.status == STATUS_EN_REVISION]
    elif tab == "aprobadas":
        filtered = [task for task in tasks if task.status == STATUS_APROBADA]
    else:
        filtered = [task for task in tasks if task.awaiting_rework]
    return filtered, counts, tab


async def get_task(db: AsyncSession, user: User, task_id: int) -> Task:
    stmt = _scoped_tasks(user).where(Task.id == task_id).options(*_TASK_LOAD)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


async def reload_task(db: AsyncSession, org_id: int, task_id: int, *, viewer: User | None = None) -> Task:
    current = await db.get(Task, task_id)
    if current is not None:
        db.expire(current, ["history", "evidence", "assignee", "creator"])
    if viewer is not None and viewer.role == ROLE_COLABORADOR:
        return await get_task(db, viewer, task_id)
    return await get_task_in_org(db, org_id, task_id)


async def get_task_in_org(db: AsyncSession, org_id: int, task_id: int) -> Task:
    stmt = select(Task).where(Task.id == task_id, Task.org_id == org_id).options(*_TASK_LOAD)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


async def list_collaborators(db: AsyncSession, user: User) -> list[User]:
    stmt = (
        select(User)
        .where(User.org_id == user.org_id, User.role == ROLE_COLABORADOR)
        .order_by(User.name)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_members(db: AsyncSession, user: User) -> list[User]:
    stmt = select(User).where(User.org_id == user.org_id).order_by(User.role.desc(), User.name)
    return list((await db.execute(stmt)).scalars().all())


async def _assignee_for(db: AsyncSession, user: User, assignee_id: int) -> User:
    assignee = await db.get(User, assignee_id)
    if assignee is None or assignee.org_id != user.org_id:
        raise HTTPException(status_code=400, detail="El asignado no pertenece a tu organización")
    if assignee.role != ROLE_COLABORADOR:
        raise HTTPException(status_code=400, detail="Solo puedes asignar tareas a colaboradores")
    return assignee


async def _record(
    db: AsyncSession,
    task: Task,
    from_status: str | None,
    to_status: str,
    user: User | None,
    comment: str | None = None,
) -> None:
    db.add(
        TaskStatusHistory(
            org_id=task.org_id,
            task_id=task.id,
            from_status=from_status,
            to_status=to_status,
            comment=comment,
            changed_by=user.id if user else None,
            created_at=utcnow(),
        )
    )


def _task_link(task_id: int) -> str:
    path = f"/tareas/{task_id}"
    base = settings.app_base_url.rstrip("/")
    return f"{base}{path}" if base else path


async def _notify(
    db: AsyncSession,
    *,
    recipient: User,
    task: Task,
    type_: str,
    message: str,
    email_subject: str | None = None,
) -> None:
    if recipient.org_id != task.org_id:
        logger.error(
            "Blocked cross-organization notification recipient_org=%s task_org=%s",
            recipient.org_id,
            task.org_id,
        )
        return
    db.add(
        Notification(
            org_id=recipient.org_id,
            user_id=recipient.id,
            task_id=task.id,
            type=type_,
            message=message,
            is_read=False,
            created_at=utcnow(),
        )
    )
    if email_subject:
        body = f"{message}\n\nVer tarea: {_task_link(task.id)}\n"
        await send_email(recipient.email, email_subject, body)


async def _supervisors(db: AsyncSession, org_id: int) -> list[User]:
    stmt = select(User).where(User.org_id == org_id, User.role == ROLE_SUPERVISOR)
    return list((await db.execute(stmt)).scalars().all())


async def create_task(db: AsyncSession, user: User, data: TaskCreate) -> Task:
    require_supervisor(user)
    assignee = await _assignee_for(db, user, data.assigned_to)
    task = Task(
        org_id=user.org_id,
        title=data.title,
        description=data.description,
        urgency=data.urgency,
        assigned_to=assignee.id,
        created_by=user.id,
        status=STATUS_PENDIENTE,
        due_date=data.due_date,
        created_at=utcnow(),
    )
    db.add(task)
    await db.flush()
    await _record(db, task, None, STATUS_PENDIENTE, user, None)
    await _notify(
        db,
        recipient=assignee,
        task=task,
        type_=TYPE_ASSIGNED,
        message=f"Se te asignó la tarea «{task.title}».",
    )
    await db.flush()
    logger.info("Task created id=%s org_id=%s by=%s assignee=%s", task.id, task.org_id, user.id, assignee.id)
    return await reload_task(db, user.org_id, task.id)


async def update_task(db: AsyncSession, user: User, task_id: int, data: TaskUpdate) -> Task:
    require_supervisor(user)
    task = await get_task_in_org(db, user.org_id, task_id)
    assignee = await _assignee_for(db, user, data.assigned_to)
    previous_assignee = task.assigned_to
    task.title = data.title
    task.description = data.description
    task.urgency = data.urgency
    task.assigned_to = assignee.id
    task.due_date = data.due_date
    await db.flush()
    if assignee.id != previous_assignee:
        await _notify(
            db,
            recipient=assignee,
            task=task,
            type_=TYPE_ASSIGNED,
            message=f"Se te asignó la tarea «{task.title}».",
        )
    logger.info("Task updated id=%s org_id=%s by=%s", task.id, task.org_id, user.id)
    return await reload_task(db, user.org_id, task.id)


async def delete_task(db: AsyncSession, user: User, task_id: int) -> None:
    require_supervisor(user)
    task = await get_task_in_org(db, user.org_id, task_id)
    paths = [item.photo_path for item in task.evidence]
    org_id = user.org_id
    await db.execute(delete(Notification).where(Notification.task_id == task.id, Notification.org_id == org_id))
    await db.execute(delete(TaskEvidence).where(TaskEvidence.task_id == task.id, TaskEvidence.org_id == org_id))
    await db.execute(
        delete(TaskStatusHistory).where(TaskStatusHistory.task_id == task.id, TaskStatusHistory.org_id == org_id)
    )
    result = await db.execute(delete(Task).where(Task.id == task.id, Task.org_id == org_id))
    if result.rowcount != 1:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    for path in paths:
        delete_photo(path, org_id)
    logger.info("Task deleted id=%s org_id=%s by=%s", task_id, org_id, user.id)


async def submit_evidence(db: AsyncSession, user: User, task_id: int, upload, comment: str | None) -> Task:
    if user.role != ROLE_COLABORADOR:
        logger.warning("Non-collaborator tried to submit evidence user_id=%s org_id=%s", user.id, user.org_id)
        raise HTTPException(status_code=403, detail="Solo el colaborador asignado puede enviar la tarea a revisión")
    task = await get_task(db, user, task_id)
    if task.assigned_to != user.id or task.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="Solo el colaborador asignado puede enviar la tarea a revisión")
    if task.status != STATUS_PENDIENTE:
        raise HTTPException(status_code=409, detail="Solo puedes enviar a revisión una tarea pendiente")
    claimed = (upload.content_type or "").lower()
    if claimed and claimed not in {"image/jpeg", "image/jpg", "image/png", "application/octet-stream"}:
        logger.warning(
            "Upload content-type %s is not a JPG/PNG hint org_id=%s user_id=%s filename=%s",
            claimed,
            user.org_id,
            user.id,
            upload.filename,
        )
    data = await read_limited(upload, org_id=user.org_id, user_id=user.id)
    ext = validate_image(data, upload.filename, org_id=user.org_id, user_id=user.id)
    relative = store_image(user.org_id, user.id, data, ext, upload.filename)
    try:
        db.add(
            TaskEvidence(
                org_id=user.org_id,
                task_id=task.id,
                photo_path=relative,
                comment=comment,
                uploaded_at=utcnow(),
                uploaded_by=user.id,
            )
        )
        previous = task.status
        task.status = STATUS_EN_REVISION
        await _record(db, task, previous, STATUS_EN_REVISION, user, comment)
        supervisors = await _supervisors(db, user.org_id)
        message = f"{user.name} envió «{task.title}» a revisión."
        for supervisor in supervisors:
            await _notify(
                db,
                recipient=supervisor,
                task=task,
                type_=TYPE_REVIEW,
                message=message,
                email_subject=f"Tarea en revisión: {task.title}",
            )
        await db.flush()
    except Exception:
        delete_photo(relative, user.org_id)
        logger.exception("Failed to persist evidence task_id=%s org_id=%s", task_id, user.org_id)
        raise
    logger.info("Task submitted for review id=%s org_id=%s by=%s", task.id, task.org_id, user.id)
    return await reload_task(db, user.org_id, task.id, viewer=user)


async def approve_task(db: AsyncSession, user: User, task_id: int) -> Task:
    require_supervisor(user)
    task = await get_task_in_org(db, user.org_id, task_id)
    if task.status != STATUS_EN_REVISION:
        raise HTTPException(status_code=409, detail="Solo puedes aprobar una tarea en revisión")
    previous = task.status
    task.status = STATUS_APROBADA
    await _record(db, task, previous, STATUS_APROBADA, user, None)
    assignee = task.assignee
    await _notify(
        db,
        recipient=assignee,
        task=task,
        type_=TYPE_APPROVED,
        message=f"Tu tarea «{task.title}» fue aprobada.",
        email_subject=f"Tarea aprobada: {task.title}",
    )
    await db.flush()
    logger.info("Task approved id=%s org_id=%s by=%s", task.id, task.org_id, user.id)
    return await reload_task(db, user.org_id, task.id)


async def reject_task(db: AsyncSession, user: User, task_id: int, comment: str | None) -> Task:
    require_supervisor(user)
    task = await get_task_in_org(db, user.org_id, task_id)
    if task.status != STATUS_EN_REVISION:
        raise HTTPException(status_code=409, detail="Solo puedes rechazar una tarea en revisión")
    previous = task.status
    await _record(db, task, previous, STATUS_RECHAZADA, user, comment)
    task.status = STATUS_PENDIENTE
    await _record(
        db,
        task,
        STATUS_RECHAZADA,
        STATUS_PENDIENTE,
        user,
        "La tarea volvió a pendiente para corrección. La evidencia se conserva.",
    )
    note = f"Tu tarea «{task.title}» fue rechazada y volvió a pendiente."
    if comment:
        note = f"{note} Comentario: {comment}"
    await _notify(
        db,
        recipient=task.assignee,
        task=task,
        type_=TYPE_REJECTED,
        message=note,
        email_subject=f"Tarea rechazada: {task.title}",
    )
    await db.flush()
    logger.info("Task rejected id=%s org_id=%s by=%s", task.id, task.org_id, user.id)
    return await reload_task(db, user.org_id, task.id)


async def authenticate(db: AsyncSession, username: str, password: str) -> User | None:
    from app.security import dummy_verify, verify_password

    stmt = select(User).where(User.username == username).options(selectinload(User.organization))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        dummy_verify(password)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def change_password(db: AsyncSession, user: User, current_password: str, new_password: str) -> User:
    from app.security import verify_password

    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")
    user.password_hash = hash_password(new_password)
    user.session_version = int(user.session_version or 0) + 1
    await db.flush()
    logger.info("Password changed user_id=%s org_id=%s", user.id, user.org_id)
    return user


async def _insert_collaborator(db: AsyncSession, *, org_id: int, data: RegisterIn | CreateUserIn, password: str) -> User:
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=400, detail="La organización no existe")
    user = User(
        org_id=org_id,
        name=data.name,
        username=data.username,
        email=str(data.email),
        password_hash=hash_password(password),
        role=ROLE_COLABORADOR,
        created_at=utcnow(),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        logger.info("Duplicate user rejected username=%s email=%s org_id=%s", data.username, data.email, org_id)
        raise HTTPException(status_code=409, detail="Ese usuario o correo ya existe") from None
    return user


async def create_collaborator(db: AsyncSession, actor: User, data: CreateUserIn) -> tuple[User, str]:
    require_supervisor(actor)
    password = data.password or secrets.token_urlsafe(9)
    user = await _insert_collaborator(db, org_id=actor.org_id, data=data, password=password)
    logger.info("Collaborator created id=%s org_id=%s by=%s", user.id, actor.org_id, actor.id)
    return user, password


async def register_from_invite(db: AsyncSession, org_id: int, data: RegisterIn) -> User:
    return await _insert_collaborator(db, org_id=org_id, data=data, password=data.password)


async def list_notifications(db: AsyncSession, user: User) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id, Notification.org_id == user.org_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def mark_notification_read(db: AsyncSession, user: User, notification_id: int) -> Notification:
    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user.id,
        Notification.org_id == user.org_id,
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    item.is_read = True
    await db.flush()
    return item


async def mark_all_read(db: AsyncSession, user: User) -> None:
    items = await list_notifications(db, user)
    for item in items:
        item.is_read = True
    await db.flush()


def evidence_file(photo_path: str, org_id: int):
    return resolve_photo(photo_path, org_id)

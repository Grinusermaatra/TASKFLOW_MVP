"""JSON API used by the browser and documented at /docs."""

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_csrf, get_db, require_csrf_header, require_supervisor_user, require_user
from app.models import TaskEvidence, User
from app.models import Task
from app.schemas import (
    CreateUserIn,
    EvidenceCommentIn,
    InviteOut,
    LoginIn,
    MessageOut,
    PasswordChangeIn,
    NotificationOut,
    RejectIn,
    TaskActionOut,
    TaskCreate,
    TaskDetailOut,
    TaskOut,
    TaskUpdate,
    UserCreatedOut,
    UserOut,
)
from app.security import dump_invite
from app.services import (
    approve_task,
    authenticate,
    change_password,
    create_collaborator,
    create_task,
    delete_task,
    get_task,
    list_notifications,
    list_tasks,
    mark_all_read,
    mark_notification_read,
    reject_task,
    submit_evidence,
    task_detail_out,
    task_out,
    update_task,
)
from app.uploads import resolve_photo

router = APIRouter(prefix="/api", tags=["api"])


@router.post("/login", response_model=MessageOut)
async def api_login(
    data: LoginIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    user = await authenticate(db, data.username, data.password)
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Usuario o contraseña incorrectos")
    from app.routers.auth import set_session
    from fastapi.responses import JSONResponse

    response = JSONResponse({"ok": True, "message": "Sesión iniciada", "redirect": "/tareas"})
    set_session(response, user.id, user.session_version)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(require_user)):
    return user


@router.post("/perfil/contrasena", response_model=MessageOut)
async def api_change_password(
    data: PasswordChangeIn,
    response: Response,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    from app.routers.auth import set_session

    await change_password(db, user, data.current_password, data.new_password)
    set_session(response, user.id, user.session_version)
    response.headers["Cache-Control"] = "no-store"
    return MessageOut(
        message="Contraseña actualizada. Las otras sesiones quedaron cerradas.",
        redirect="/perfil",
    )


@router.get("/tareas", response_model=list[TaskOut])
async def api_list_tasks(
    tab: str = "todas",
    q: str = "",
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    tasks, _counts, _tab = await list_tasks(db, user, tab, q)
    return [task_out(task) for task in tasks]


def _action(message: str, task) -> TaskActionOut:
    detail = task_detail_out(task)
    return TaskActionOut(message=message, redirect=f"/tareas/{detail.id}", task=detail)


@router.post("/tareas", response_model=TaskActionOut)
async def api_create_task(
    data: TaskCreate,
    user: User = Depends(require_supervisor_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    task = await create_task(db, user, data)
    return _action("Tarea creada", task)


@router.get("/tareas/{task_id}", response_model=TaskDetailOut)
async def api_get_task(
    task_id: int,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    task = await get_task(db, user, task_id)
    return task_detail_out(task)


@router.put("/tareas/{task_id}", response_model=TaskActionOut)
async def api_update_task(
    task_id: int,
    data: TaskUpdate,
    user: User = Depends(require_supervisor_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    task = await update_task(db, user, task_id, data)
    return _action("Tarea actualizada", task)


@router.delete("/tareas/{task_id}", response_model=MessageOut)
async def api_delete_task(
    task_id: int,
    user: User = Depends(require_supervisor_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    await delete_task(db, user, task_id)
    return MessageOut(message="Tarea eliminada", redirect="/tareas")


@router.post("/tareas/{task_id}/completar", response_model=TaskActionOut)
async def api_complete_task(
    task_id: int,
    request: Request,
    photo: UploadFile = File(...),
    comment: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token or None)
    parsed = EvidenceCommentIn.model_validate({"comment": comment})
    task = await submit_evidence(db, user, task_id, photo, parsed.comment)
    return _action("Tarea enviada a revisión", task)


@router.post("/tareas/{task_id}/aprobar", response_model=TaskActionOut)
async def api_approve_task(
    task_id: int,
    user: User = Depends(require_supervisor_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    task = await approve_task(db, user, task_id)
    return _action("Tarea aprobada", task)


@router.post("/tareas/{task_id}/rechazar", response_model=TaskActionOut)
async def api_reject_task(
    task_id: int,
    data: RejectIn,
    user: User = Depends(require_supervisor_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    task = await reject_task(db, user, task_id, data.comment)
    return _action("Tarea rechazada. Volvió a pendiente y la evidencia se conserva.", task)


@router.get("/notificaciones", response_model=list[NotificationOut])
async def api_notifications(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    items = await list_notifications(db, user)
    return [
        NotificationOut(
            id=item.id,
            task_id=item.task_id,
            type=item.type,
            message=item.message,
            is_read=item.is_read,
            created_at=item.created_at,
        )
        for item in items
    ]


@router.post("/notificaciones/{notification_id}/leida", response_model=MessageOut)
async def api_mark_read(
    notification_id: int,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    await mark_notification_read(db, user, notification_id)
    return MessageOut(message="Notificación marcada como leída", redirect="/notificaciones")


@router.post("/notificaciones/leer-todas", response_model=MessageOut)
async def api_mark_all(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    await mark_all_read(db, user)
    return MessageOut(message="Notificaciones marcadas como leídas", redirect="/notificaciones")


@router.post("/usuarios", response_model=UserCreatedOut)
async def api_create_user(
    data: CreateUserIn,
    user: User = Depends(require_supervisor_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
):
    created, password = await create_collaborator(db, user, data)
    return UserCreatedOut(
        id=created.id,
        name=created.name,
        username=created.username,
        email=created.email,
        role=created.role,
        org_id=created.org_id,
        temporary_password=password,
        message="Colaborador creado. Comparte la contraseña; solo se muestra ahora.",
    )


@router.post("/invitaciones", response_model=InviteOut)
async def api_invite(
    user: User = Depends(require_supervisor_user),
    _: None = Depends(require_csrf_header),
):
    token = dump_invite(user.org_id)
    return InviteOut(
        message="Enlace de invitación listo. Vence en 7 días.",
        invite_url=f"/registro/{token}",
    )


@router.get("/evidencias/{evidence_id}")
async def api_evidence(
    evidence_id: int,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(TaskEvidence)
        .join(Task, Task.id == TaskEvidence.task_id)
        .where(
            TaskEvidence.id == evidence_id,
            TaskEvidence.org_id == user.org_id,
            Task.org_id == user.org_id,
        )
    )
    if user.role == "colaborador":
        stmt = stmt.where(Task.assigned_to == user.id)
    evidence = (await db.execute(stmt)).scalar_one_or_none()
    if evidence is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    path = resolve_photo(evidence.photo_path, user.org_id)
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media, filename=path.name, content_disposition_type="inline")

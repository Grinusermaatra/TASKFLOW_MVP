"""Server-rendered pages and form posts."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import ROLE_SUPERVISOR
from app.deps import enforce_csrf, get_current_user, get_db, require_supervisor, require_user
from app.models import Task, TaskEvidence, User
from app.schemas import CreateUserIn, EvidenceCommentIn, PasswordChangeIn, RejectIn, TaskCreate, TaskUpdate
from app.security import dump_invite
from app.services import (
    approve_task,
    change_password,
    create_collaborator,
    create_task,
    delete_task,
    get_task,
    latest_rejection,
    list_collaborators,
    list_members,
    list_notifications,
    list_tasks,
    mark_all_read,
    mark_notification_read,
    reject_task,
    shell_context,
    submit_evidence,
    update_task,
)
from app.templating import redirect_with_flash, render
from app.uploads import resolve_photo

router = APIRouter(tags=["pages"])


def _messages(exc: ValidationError) -> list[str]:
    messages = []
    for error in exc.errors():
        message = error.get("msg", "Dato inválido")
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        messages.append(message)
    return messages or ["Datos inválidos"]


def _task_form(form) -> dict:
    assignee_raw = form.get("assigned_to") or ""
    try:
        assignee = int(assignee_raw)
    except (TypeError, ValueError):
        assignee = 0
    due = form.get("due_date") or None
    if due == "":
        due = None
    return {
        "title": form.get("title") or "",
        "description": form.get("description") or "",
        "urgency": form.get("urgency") or "",
        "assigned_to": assignee,
        "due_date": due,
    }


def _prefill(task: Task) -> dict:
    return {
        "title": task.title,
        "description": task.description,
        "urgency": task.urgency,
        "assigned_to": task.assigned_to,
        "due_date": task.due_date.isoformat() if task.due_date else "",
    }


@router.get("/")
async def root(user: User | None = Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/tareas", status_code=303)


@router.get("/tareas")
async def tasks_page(
    request: Request,
    tab: str = "pendientes",
    q: str = "",
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if tab not in {"pendientes", "revision", "aprobadas", "rechazadas"}:
        tab = "pendientes"
    tasks, _counts, selected = await list_tasks(db, user, tab, q)
    all_tasks, full_counts, _all_tab = await list_tasks(db, user, "todas", q)
    ctx = await shell_context(
        db,
        user,
        tasks=tasks,
        counts=full_counts,
        tab=selected,
        q=q.strip(),
        total=len(all_tasks),
    )
    return render(request, "tasks.html", ctx)


@router.get("/tareas/nueva")
async def new_task_page(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    require_supervisor(user)
    ctx = await shell_context(
        db,
        user,
        assignees=await list_collaborators(db, user),
        form={"title": "", "description": "", "urgency": "media", "assigned_to": "", "due_date": ""},
        errors=[],
        mode="create",
        task=None,
        show_fab=False,
    )
    return render(request, "task_form.html", ctx)


@router.post("/tareas")
async def create_task_form(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    require_supervisor(user)
    form = await request.form()
    enforce_csrf(request, request.headers.get("x-csrf-token") or _text(form.get("csrf_token")))
    raw = _task_form(form)
    try:
        data = TaskCreate.model_validate(raw)
    except ValidationError as exc:
        ctx = await shell_context(
            db,
            user,
            assignees=await list_collaborators(db, user),
            form={**raw, "due_date": raw["due_date"] or ""},
            errors=_messages(exc),
            mode="create",
            task=None,
            show_fab=False,
        )
        return render(request, "task_form.html", ctx, status_code=422)
    task = await create_task(db, user, data)
    return redirect_with_flash(f"/tareas/{task.id}", "Tarea creada")


@router.get("/tareas/{task_id}")
async def task_detail(
    task_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    task = await get_task(db, user, task_id)
    rejection = latest_rejection(task)
    ctx = await shell_context(db, user, task=task, rejection=rejection)
    return render(request, "task_detail.html", ctx)


@router.get("/tareas/{task_id}/editar")
async def edit_task_page(
    task_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    require_supervisor(user)
    task = await get_task(db, user, task_id)
    ctx = await shell_context(
        db,
        user,
        assignees=await list_collaborators(db, user),
        form=_prefill(task),
        errors=[],
        mode="edit",
        task=task,
        show_fab=False,
    )
    return render(request, "task_form.html", ctx)


@router.post("/tareas/{task_id}/editar")
async def edit_task_form(
    task_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    require_supervisor(user)
    form = await request.form()
    enforce_csrf(request, request.headers.get("x-csrf-token") or _text(form.get("csrf_token")))
    raw = _task_form(form)
    task = await get_task(db, user, task_id)
    try:
        data = TaskUpdate.model_validate(raw)
    except ValidationError as exc:
        ctx = await shell_context(
            db,
            user,
            assignees=await list_collaborators(db, user),
            form={**raw, "due_date": raw["due_date"] or ""},
            errors=_messages(exc),
            mode="edit",
            task=task,
            show_fab=False,
        )
        return render(request, "task_form.html", ctx, status_code=422)
    updated = await update_task(db, user, task_id, data)
    return redirect_with_flash(f"/tareas/{updated.id}", "Tarea actualizada")


@router.post("/tareas/{task_id}/eliminar")
async def delete_task_form(
    task_id: int,
    request: Request,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    require_supervisor(user)
    await delete_task(db, user, task_id)
    return redirect_with_flash("/tareas", "Tarea eliminada")


@router.post("/tareas/{task_id}/completar")
async def complete_task_form(
    task_id: int,
    request: Request,
    photo: UploadFile = File(...),
    comment: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    parsed = EvidenceCommentIn.model_validate({"comment": comment})
    task = await submit_evidence(db, user, task_id, photo, parsed.comment)
    return redirect_with_flash(f"/tareas/{task.id}", "Tarea enviada a revisión")


@router.post("/tareas/{task_id}/aprobar")
async def approve_task_form(
    task_id: int,
    request: Request,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    task = await approve_task(db, user, task_id)
    return redirect_with_flash(f"/tareas/{task.id}", "Tarea aprobada")


@router.post("/tareas/{task_id}/rechazar")
async def reject_task_form(
    task_id: int,
    request: Request,
    comment: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    parsed = RejectIn.model_validate({"comment": comment})
    task = await reject_task(db, user, task_id, parsed.comment)
    return redirect_with_flash(f"/tareas/{task.id}", "Tarea rechazada. Volvió a pendiente.")


@router.get("/notificaciones")
async def notifications_page(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    items = await list_notifications(db, user)
    ctx = await shell_context(db, user, notifications=items)
    return render(request, "notifications.html", ctx)


@router.get("/notificaciones/{notification_id}/abrir")
async def open_notification(
    notification_id: int,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    item = await mark_notification_read(db, user, notification_id)
    if item.task_id:
        return RedirectResponse(f"/tareas/{item.task_id}", status_code=303)
    return RedirectResponse("/notificaciones", status_code=303)


@router.post("/notificaciones/leer-todas")
async def read_all_form(
    request: Request,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    await mark_all_read(db, user)
    return redirect_with_flash("/notificaciones", "Notificaciones marcadas como leídas")


@router.get("/perfil")
async def profile_page(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    members = await list_members(db, user) if user.role == ROLE_SUPERVISOR else []
    ctx = await shell_context(
        db,
        user,
        members=members,
        created=None,
        invite_url=None,
        form_errors=[],
        password_errors=[],
    )
    return render(request, "profile.html", ctx)


@router.post("/perfil/contrasena")
async def change_password_form(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    from app.routers.auth import set_session

    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)

    async def _again(errors: list[str], status_code: int):
        members = await list_members(db, user) if user.role == ROLE_SUPERVISOR else []
        ctx = await shell_context(
            db,
            user,
            members=members,
            created=None,
            invite_url=None,
            form_errors=[],
            password_errors=errors,
        )
        return render(request, "profile.html", ctx, status_code=status_code)

    try:
        data = PasswordChangeIn.model_validate(
            {"current_password": current_password, "new_password": new_password}
        )
    except ValidationError as exc:
        return await _again(_messages(exc), 422)
    try:
        await change_password(db, user, data.current_password, data.new_password)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "No se pudo cambiar la contraseña"
        return await _again([detail], exc.status_code)
    response = redirect_with_flash(
        "/perfil",
        "Contraseña actualizada. Las otras sesiones quedaron cerradas.",
    )
    set_session(response, user.id, user.session_version)
    return response


@router.post("/usuarios")
async def create_user_form(
    request: Request,
    name: str = Form(""),
    username: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    require_supervisor(user)
    raw = {"name": name, "username": username, "email": email, "password": password or None}
    try:
        data = CreateUserIn.model_validate(raw)
    except ValidationError as exc:
        ctx = await shell_context(
            db,
            user,
            members=await list_members(db, user),
            created=None,
            invite_url=None,
            form_errors=_messages(exc),
        )
        return render(request, "profile.html", ctx, status_code=422)
    created, temporary = await create_collaborator(db, user, data)
    ctx = await shell_context(
        db,
        user,
        members=await list_members(db, user),
        created={"username": created.username, "password": temporary, "name": created.name},
        invite_url=None,
        form_errors=[],
    )
    return render(request, "profile.html", ctx)


@router.post("/invitaciones")
async def invite_form(
    request: Request,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    enforce_csrf(request, request.headers.get("x-csrf-token") or csrf_token)
    require_supervisor(user)
    token = dump_invite(user.org_id)
    ctx = await shell_context(
        db,
        user,
        members=await list_members(db, user),
        created=None,
        invite_url=f"/registro/{token}",
        form_errors=[],
    )
    return render(request, "profile.html", ctx)


@router.get("/evidencias/{evidence_id}")
async def evidence_file(
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
    if user.role != ROLE_SUPERVISOR:
        stmt = stmt.where(Task.assigned_to == user.id)
    evidence = (await db.execute(stmt)).scalar_one_or_none()
    if evidence is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    path = resolve_photo(evidence.photo_path, user.org_id)
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media, content_disposition_type="inline", filename=path.name)


def _text(value) -> str | None:
    if isinstance(value, str):
        return value
    return None

"""Pydantic input and output models."""

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.constants import URGENCIES

_USERNAME = re.compile(r"[a-z0-9._-]{3,80}")


def _strip_required(value: str, message: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(message)
    return cleaned


def _password_ok(value: str) -> str:
    if len(value) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("La contraseña no puede superar 72 bytes")
    return value


def _username_ok(value: str) -> str:
    cleaned = value.strip().lower()
    if not _USERNAME.fullmatch(cleaned):
        raise ValueError("El usuario debe tener de 3 a 80 caracteres: letras, números, punto o guion")
    return cleaned


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str

    @field_validator("current_password")
    @classmethod
    def current_password_present(cls, value: str) -> str:
        if not value:
            raise ValueError("La contraseña actual es obligatoria")
        return value

    @field_validator("new_password")
    @classmethod
    def new_password_ok(cls, value: str) -> str:
        return _password_ok(value)


class LoginIn(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("El usuario es obligatorio")
        return cleaned

    @field_validator("password")
    @classmethod
    def password(cls, value: str) -> str:
        if not value:
            raise ValueError("La contraseña es obligatoria")
        return value


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    username: str
    email: EmailStr
    password: str

    @field_validator("name")
    @classmethod
    def name_clean(cls, value: str) -> str:
        return _strip_required(" ".join(value.split()), "El nombre es obligatorio")

    @field_validator("username")
    @classmethod
    def username_clean(cls, value: str) -> str:
        return _username_ok(value)

    @field_validator("email")
    @classmethod
    def email_clean(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def password_clean(cls, value: str) -> str:
        return _password_ok(value)


class CreateUserIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    username: str
    email: EmailStr
    password: str | None = None

    @field_validator("name")
    @classmethod
    def name_clean(cls, value: str) -> str:
        return _strip_required(" ".join(value.split()), "El nombre es obligatorio")

    @field_validator("username")
    @classmethod
    def username_clean(cls, value: str) -> str:
        return _username_ok(value)

    @field_validator("email")
    @classmethod
    def email_clean(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def password_clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            return None
        return _password_ok(value)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    urgency: str
    assigned_to: int
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def title_clean(cls, value: str) -> str:
        cleaned = _strip_required(value, "El título es obligatorio")
        if len(cleaned) > 200:
            raise ValueError("El título no puede superar 200 caracteres")
        return cleaned

    @field_validator("description")
    @classmethod
    def description_clean(cls, value: str) -> str:
        cleaned = _strip_required(value, "La descripción es obligatoria")
        if len(cleaned) > 5000:
            raise ValueError("La descripción no puede superar 5000 caracteres")
        return cleaned

    @field_validator("urgency")
    @classmethod
    def urgency_clean(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in URGENCIES:
            raise ValueError("La urgencia debe ser baja, media, alta o crítica")
        return cleaned

    @field_validator("assigned_to")
    @classmethod
    def assignee_clean(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Selecciona un colaborador")
        return value


class TaskUpdate(TaskCreate):
    pass


class RejectIn(BaseModel):
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def comment_clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > 2000:
            raise ValueError("El comentario no puede superar 2000 caracteres")
        return cleaned


class EvidenceCommentIn(BaseModel):
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def comment_clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > 2000:
            raise ValueError("El comentario no puede superar 2000 caracteres")
        return cleaned


class MessageOut(BaseModel):
    ok: bool = True
    message: str
    redirect: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    username: str
    email: str
    role: str
    org_id: int


class UserCreatedOut(UserOut):
    temporary_password: str
    message: str
    ok: bool = True


class InviteOut(BaseModel):
    ok: bool = True
    message: str
    invite_url: str
    expires_in_days: int = 7


class TaskOut(BaseModel):
    id: int
    title: str
    description: str
    urgency: str
    status: str
    assigned_to: int
    assignee_name: str
    created_by: int
    due_date: date | None
    created_at: datetime
    awaiting_rework: bool


class EvidenceOut(BaseModel):
    id: int
    photo_url: str
    comment: str | None
    uploaded_at: datetime


class HistoryOut(BaseModel):
    id: int
    from_status: str | None
    to_status: str
    comment: str | None
    changed_by_name: str | None
    created_at: datetime


class TaskDetailOut(TaskOut):
    creator_name: str
    evidence: list[EvidenceOut]
    history: list[HistoryOut]
    latest_rejection_comment: str | None = None


class TaskActionOut(BaseModel):
    ok: bool = True
    message: str
    redirect: str
    task: TaskDetailOut


class NotificationOut(BaseModel):
    id: int
    task_id: int | None
    type: str
    message: str
    is_read: bool
    created_at: datetime

"""Passwords, signed sessions, CSRF, and invite tokens."""

import logging
import secrets

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

logger = logging.getLogger("taskflow.security")

SESSION_COOKIE = "taskflow_session"
CSRF_COOKIE = "taskflow_csrf"
SESSION_MAX_AGE = 60 * 60 * 24 * 14
CSRF_MAX_AGE = SESSION_MAX_AGE
INVITE_MAX_AGE = 60 * 60 * 24 * 7

# Hashed once so a missing user still pays the bcrypt cost.
_DUMMY_HASH = bcrypt.hashpw(b"taskflow-dummy-password", bcrypt.gensalt()).decode("utf-8")


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("La contraseña no puede superar 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        logger.warning("Password verification rejected a malformed hash or password")
        return False


def dummy_verify(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=salt)


def dump_session(user_id: int) -> str:
    return _serializer("taskflow-session-v1").dumps({"uid": user_id})


def load_session(token: str) -> int | None:
    try:
        data = _serializer("taskflow-session-v1").loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    if isinstance(uid, bool) or not isinstance(uid, int):
        return None
    return uid


def dump_invite(org_id: int) -> str:
    return _serializer("taskflow-invite-v1").dumps({"org_id": org_id, "role": "colaborador"})


def load_invite(token: str) -> int | None:
    try:
        data = _serializer("taskflow-invite-v1").loads(token, max_age=INVITE_MAX_AGE)
    except SignatureExpired:
        logger.info("Invite token expired")
        return None
    except BadSignature:
        logger.info("Invite token signature rejected")
        return None
    if not isinstance(data, dict) or data.get("role") != "colaborador":
        return None
    org_id = data.get("org_id")
    if isinstance(org_id, bool) or not isinstance(org_id, int):
        return None
    return org_id


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def tokens_match(expected: str | None, sent: str | None) -> bool:
    if not expected or not sent:
        return False
    expected_s = str(expected)
    sent_s = str(sent)
    if len(expected_s) != len(sent_s):
        return False
    return secrets.compare_digest(expected_s, sent_s)

"""Shared domain constants."""

ROLE_SUPERVISOR = "supervisor"
ROLE_COLABORADOR = "colaborador"
ROLES = (ROLE_SUPERVISOR, ROLE_COLABORADOR)

STATUS_PENDIENTE = "PENDIENTE"
STATUS_EN_REVISION = "EN_REVISION"
STATUS_APROBADA = "APROBADA"
STATUS_RECHAZADA = "RECHAZADA"
STATUSES = (
    STATUS_PENDIENTE,
    STATUS_EN_REVISION,
    STATUS_APROBADA,
    STATUS_RECHAZADA,
)

URGENCIES = ("baja", "media", "alta", "crítica")

TABS = (
    ("pendientes", "Pendientes"),
    ("revision", "En revisión"),
    ("aprobadas", "Aprobadas"),
    ("rechazadas", "Rechazadas"),
)

STATUS_LABELS = {
    STATUS_PENDIENTE: "Pendiente",
    STATUS_EN_REVISION: "En revisión",
    STATUS_APROBADA: "Aprobada",
    STATUS_RECHAZADA: "Rechazada",
}

URGENCY_LABELS = {
    "baja": "Baja",
    "media": "Media",
    "alta": "Alta",
    "crítica": "Crítica",
}

ROLE_LABELS = {
    ROLE_SUPERVISOR: "Supervisor",
    ROLE_COLABORADOR: "Colaborador",
}

TYPE_ASSIGNED = "asignacion"
TYPE_REVIEW = "en_revision"
TYPE_APPROVED = "aprobada"
TYPE_REJECTED = "rechazada"

"""Auth and permission checks from the roles audit."""

import copy
from io import BytesIO

from itsdangerous import URLSafeTimedSerializer
from PIL import Image

from app.config import settings


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (12, 80, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def _login(client, username: str, password: str) -> str:
    page = client.get("/login")
    assert page.status_code == 200
    token = client.cookies.get("taskflow_csrf")
    assert token
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return token


def _session_cookie(client):
    matches = [cookie for cookie in client.cookies.jar if cookie.name == "taskflow_session"]
    assert len(matches) == 1
    return matches[0]


def _replace_session(client, value: str):
    _session_cookie(client).value = value


def _task_body(assigned_to: int) -> dict:
    return {
        "title": "Cambio no permitido",
        "description": "Un colaborador no puede guardar esto.",
        "urgency": "baja",
        "assigned_to": assigned_to,
    }


def test_requests_without_a_session_are_401(world):
    client = world["client"]
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/tareas").status_code == 401
    assert client.get(f"/api/tareas/{world['luis_task_id']}").status_code == 401
    assert client.get("/api/notificaciones").status_code == 401
    page = client.get("/tareas", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/login"

    token = client.get("/login").cookies.get("taskflow_csrf")
    created = client.post(
        "/api/tareas",
        json=_task_body(world["luis_id"]),
        headers={"X-CSRF-Token": token},
    )
    assert created.status_code == 401


def test_collaborator_cannot_edit_delete_approve_reject_or_create(world):
    client = world["client"]
    token = _login(client, "luis.colaborador", world["passwords"]["luis"])
    headers = {"X-CSRF-Token": token}
    task_id = world["luis_task_id"]
    body = _task_body(world["maria_id"])

    assert client.post("/api/tareas", json=body, headers=headers).status_code == 403
    assert client.put(f"/api/tareas/{task_id}", json=body, headers=headers).status_code == 403
    assert client.delete(f"/api/tareas/{task_id}", headers=headers).status_code == 403
    assert client.post(f"/api/tareas/{task_id}/aprobar", headers=headers).status_code == 403
    assert client.post(
        f"/api/tareas/{task_id}/rechazar",
        json={"comment": "No deberia poder"},
        headers=headers,
    ).status_code == 403

    client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    ana = _login(client, "ana.supervisor", world["passwords"]["ana"])
    detail = client.get(f"/api/tareas/{task_id}", headers={"X-CSRF-Token": ana})
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["title"] == "Inventario original"
    assert payload["status"] == "PENDIENTE"
    assert payload["assigned_to"] == world["luis_id"]


def test_tasks_are_hidden_across_collaborators_and_organizations(world):
    client = world["client"]
    luis = _login(client, "luis.colaborador", world["passwords"]["luis"])
    assert client.get(f"/api/tareas/{world['maria_task_id']}").status_code == 404
    assert client.get(f"/api/tareas/{world['other_task_id']}").status_code == 404
    assert client.get(f"/tareas/{world['maria_task_id']}", follow_redirects=False).status_code == 404

    client.post("/logout", data={"csrf_token": luis}, follow_redirects=False)
    _login(client, "otra.supervisor", world["passwords"]["other_supervisor"])
    assert client.get(f"/api/tareas/{world['luis_task_id']}").status_code == 404
    assert client.get(f"/api/tareas/{world['maria_task_id']}").status_code == 404

    client.cookies.clear()
    _login(client, "otra.colaborador", world["passwords"]["other_collab"])
    assert client.get(f"/api/tareas/{world['luis_task_id']}").status_code == 404


def test_evidence_submit_does_not_change_protected_fields(world):
    client = world["client"]
    token = _login(client, "luis.colaborador", world["passwords"]["luis"])
    response = client.post(
        f"/api/tareas/{world['luis_task_id']}/completar",
        data={
            "comment": "Foto del inventario",
            "csrf_token": token,
            "title": "Titulo robado",
            "description": "Descripcion robada",
            "urgency": "baja",
            "assigned_to": str(world["maria_id"]),
            "status": "APROBADA",
            "org_id": "999",
        },
        files={"photo": ("evidencia.png", _png(), "image/png")},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200, response.text
    task = response.json()["task"]
    assert task["title"] == "Inventario original"
    assert task["description"] == "Contar cajas"
    assert task["urgency"] == "alta"
    assert task["assigned_to"] == world["luis_id"]
    assert task["created_by"] == world["ana_id"]
    assert task["status"] == "EN_REVISION"
    assert len(task["evidence"]) == 1


def test_reject_keeps_the_photo_and_other_people_cannot_read_it(world):
    client = world["client"]
    luis = _login(client, "luis.colaborador", world["passwords"]["luis"])
    submitted = client.post(
        f"/api/tareas/{world['luis_task_id']}/completar",
        data={"comment": "Listo para revision", "csrf_token": luis},
        files={"photo": ("evidencia.png", _png(), "image/png")},
        headers={"X-CSRF-Token": luis},
    )
    assert submitted.status_code == 200, submitted.text
    evidence_id = submitted.json()["task"]["evidence"][0]["id"]
    photo_url = submitted.json()["task"]["evidence"][0]["photo_url"]

    client.post("/logout", data={"csrf_token": luis}, follow_redirects=False)
    maria = _login(client, "maria.colaborador", world["passwords"]["maria"])
    assert client.get(f"/api/evidencias/{evidence_id}").status_code == 404
    client.post("/logout", data={"csrf_token": maria}, follow_redirects=False)

    other = _login(client, "otra.supervisor", world["passwords"]["other_supervisor"])
    assert client.get(f"/api/evidencias/{evidence_id}").status_code == 404
    client.post("/logout", data={"csrf_token": other}, follow_redirects=False)

    ana = _login(client, "ana.supervisor", world["passwords"]["ana"])
    rejected = client.post(
        f"/api/tareas/{world['luis_task_id']}/rechazar",
        json={"comment": "Falta el fondo de la bodega"},
        headers={"X-CSRF-Token": ana},
    )
    assert rejected.status_code == 200, rejected.text
    task = rejected.json()["task"]
    assert task["status"] == "PENDIENTE"
    assert len(task["evidence"]) == 1
    assert task["evidence"][0]["id"] == evidence_id
    assert task["evidence"][0]["photo_url"] == photo_url
    assert any(item["to_status"] == "RECHAZADA" for item in task["history"])
    photo = client.get(photo_url)
    assert photo.status_code == 200
    assert photo.headers["content-type"].startswith("image/")


def test_old_cookie_and_password_change_lose_the_session(world):
    client = world["client"]
    token = _login(client, "luis.colaborador", world["passwords"]["luis"])
    stolen = client.cookies.get("taskflow_session")
    unsigned = URLSafeTimedSerializer(settings.secret_key, salt="taskflow-session-v1").dumps(
        {"uid": world["luis_id"]}
    )
    _replace_session(client, unsigned)
    assert client.get("/api/me").status_code == 401

    _replace_session(client, stolen)
    assert client.get("/api/me").status_code == 200
    new_password = "nueva-clave-de-prueba"
    changed = client.post(
        "/api/perfil/contrasena",
        json={"current_password": world["passwords"]["luis"], "new_password": new_password},
        headers={"X-CSRF-Token": token},
    )
    assert changed.status_code == 200, changed.text
    assert client.get("/api/me").status_code == 200
    _replace_session(client, stolen)
    assert client.get("/api/me").status_code == 401

    _login(client, "luis.colaborador", new_password)
    current = copy.copy(_session_cookie(client))
    logged_out = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert logged_out.status_code == 303
    client.cookies.jar.set_cookie(current)
    assert client.get("/api/me").status_code == 401

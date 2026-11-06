# TaskFlow

Mobile-first task assignment for one organization at a time. Supervisors assign work. Collaborators finish it by attaching a photo. A supervisor approves the evidence or sends the task back to pending without deleting the photos.

The interface is in Spanish. The API is served by FastAPI (`/docs`).

## Local install

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and sign in with a demo account.

## Demo credentials

Organization: **TaskFlow Demo**

| Role | Name | Username | Password |
| --- | --- | --- | --- |
| Supervisor | Ana Ruiz | `ana.supervisor` | `Supervisor123!` |
| Colaborador | Luis Gómez | `luis.colaborador` | `Colaborador123!` |
| Colaborador | María Pérez | `maria.colaborador` | `Colaborador123!` |

`python seed.py` is safe to run again. If Ana already exists, it prints these credentials and does not insert duplicates.

The seed creates four tasks:

- **Pendiente:** Revisar inventario de bodega (Luis)
- **En revisión:** Fotografiar vitrina principal (María), with a sample PNG
- **Aprobada:** Actualizar precios de góndola (Luis), with evidence
- **Devuelta:** Limpiar cámara de frío (María). A supervisor rejected it, so the status is `PENDIENTE` again and the photo is still on the task. It shows under **Rechazadas** and under **Pendientes**.

## End-to-end check

1. Sign in as `ana.supervisor`.
2. Open **+** and assign a task to Luis (title, description, urgency, optional due date).
3. Sign out. Sign in as `luis.colaborador`.
4. Open the task, take or choose a JPG/PNG, preview it, and send it to review.
5. Sign in as Ana. The bell shows a notification. Open the task and choose **Aprobar** or **Rechazar**.
6. A rejection stores `RECHAZADA` in the history, sets the task back to `PENDIENTE`, and keeps every photo. Luis can submit a new photo.

A collaborator who sends `PUT` or `DELETE` for a task receives **403**, including forged ids.

## How the pieces fit

- Sessions are an httpOnly cookie signed with itsdangerous (`taskflow_session`).
- Forms and `fetch` send a CSRF token that must match the `taskflow_csrf` cookie.
- Passwords are bcrypt hashes.
- Every task, evidence row, notification, and history row is stored with `org_id`. Queries filter by the signed-in user's organization. Collaborators also only see tasks assigned to them. Any supervisor in that organization can approve or reject.
- Photos go to `uploads/{org_id}/{uuid}.jpg|png`. The server checks size (5 MB), filename characters, magic bytes, and that Pillow can decode a real JPEG or PNG. Upload failures are written to the log. `uploads/` contents are gitignored; the folder stays.
- State changes are rows in `task_status_history`.
- In-app notifications always exist. Email is sent only when SMTP is configured: supervisors when a task enters `EN_REVISION`, and the assignee on approve or reject.

There is no public signup. Ana (or any supervisor) creates a collaborator with a temporary password, or generates an invite link that expires in 7 days.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./taskflow.db`, `postgres://...`, or `postgresql://...` | `sqlite+aiosqlite:///./taskflow.db` |
| `SECRET_KEY` | Signs session and invite cookies | development default, change it in production |
| `COOKIE_SECURE` | `true` behind HTTPS | `false` |
| `SEED_ON_STARTUP` | Run `seed.py` before uvicorn (`1` / `0`) | `0` |
| `APP_BASE_URL` | Absolute link used in emails | empty |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Optional FastAPI-Mail | email skipped when host or from is empty |
| `SMTP_STARTTLS`, `SMTP_SSL` | Transport | STARTTLS on, SSL off |
| `UPLOAD_DIR` | Photo directory | `uploads` |
| `PORT` | Listen port in Docker | `8000` |

`postgres://` and `postgresql://` URLs are normalized to `postgresql+asyncpg://`. `sslmode=` is rewritten to `ssl=` for asyncpg. Moving from SQLite to Postgres does not require an application change.

## Render

`render.yaml` defines a Docker web service on the free plan. It generates `SECRET_KEY`, turns on secure cookies, and seeds the database on boot.

The free instance disk is ephemeral. The default SQLite file disappears when the service restarts or is redeployed, and `SEED_ON_STARTUP=1` loads the demo again. Do not treat that disk as durable storage.

For a database that survives restarts, create a Render Postgres instance and set `DATABASE_URL` to its connection string (`postgres://...` is enough). Run `python seed.py` once against that URL, then set `SEED_ON_STARTUP` to `0` if you do not want the demo users recreated on later boots. The seed still refuses to duplicate Ana if she is already there.

Deploy: push this repo, create a Blueprint from `render.yaml` (or a new Web Service with the Dockerfile), and open the service URL.

## Fly.io

```bash
fly launch --no-deploy
fly secrets set SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" COOKIE_SECURE=true
fly volumes create taskflow_data --size 1
```

Mount the volume at `/data` and set `DATABASE_URL=sqlite+aiosqlite:////data/taskflow.db`. `fly deploy` uses the Dockerfile. Set `SEED_ON_STARTUP=1` for the first boot. A Fly Postgres cluster works the same way: set `DATABASE_URL` and leave the app code unchanged.

## Railway

Create a project from this repo. Railway detects the Dockerfile. Set `SECRET_KEY`, `COOKIE_SECURE=true`, and `SEED_ON_STARTUP=1`. Add the Postgres plugin if you need durable data and put its URL in `DATABASE_URL`. The container listens on Railway's `PORT`.

## API

Interactive reference: http://127.0.0.1:8000/docs

Mutations need the CSRF cookie and the `X-CSRF-Token` header. Sign in with `POST /login` (HTML form) or `POST /api/login` (JSON) to receive the session cookie.

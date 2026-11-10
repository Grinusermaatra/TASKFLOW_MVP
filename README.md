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

Open http://127.0.0.1:8000. `python seed.py` prints a random password for each demo account once in that terminal. Those passwords are not stored in the repository.

## Demo accounts

Organization: **TaskFlow Demo**

| Role | Name | Username |
| --- | --- | --- |
| Supervisor | Ana Ruiz | `ana.supervisor` |
| Colaborador | Luis Gómez | `luis.colaborador` |
| Colaborador | María Pérez | `maria.colaborador` |

Running `python seed.py` again does not insert duplicates and does not print the passwords a second time. To replace them and sign out existing sessions:

```bash
python seed.py --rotate
```

The new passwords are printed once on that command's stdout. Anyone signed in with the previous password has to sign in again. Each person can also change their own password from **Perfil**; that closes every other session for the account.

The seed creates four tasks:

- **Pendiente:** Revisar inventario de bodega (Luis)
- **En revisión:** Fotografiar vitrina principal (María), with a sample PNG
- **Aprobada:** Actualizar precios de góndola (Luis), with evidence
- **Devuelta:** Limpiar cámara de frío (María). A supervisor rejected it, so the status is `PENDIENTE` again and the photo is still on the task. It shows under **Rechazadas** and under **Pendientes**.

## End-to-end check

1. Sign in as `ana.supervisor` with the password printed by `python seed.py`.
2. Open **+** and assign a task to Luis (title, description, urgency, optional due date).
3. Sign out. Sign in as `luis.colaborador` with the password printed by the same command.
4. Open the task, take or choose a JPG/PNG, preview it, and send it to review.
5. Sign in as Ana. The bell shows a notification. Open the task and choose **Aprobar** or **Rechazar**.
6. A rejection stores `RECHAZADA` in the history, sets the task back to `PENDIENTE`, and keeps every photo. Luis can submit a new photo.

A collaborator who sends `PUT` or `DELETE` for a task receives **403**, including forged ids.

## How the pieces fit

- Sessions are an httpOnly cookie signed with itsdangerous (`taskflow_session`). The cookie carries a session version. Changing a password, rotating the demo passwords, or signing out increments that version, so a copied cookie stops working.
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
| `SECRET_KEY` | Signs session and invite cookies | development default |
| `TASKFLOW_ENV` | `production` refuses a missing or development `SECRET_KEY` and requires `COOKIE_SECURE=true` | `development` |
| `COOKIE_SECURE` | `true` behind HTTPS. Required when `TASKFLOW_ENV` is `production` or when Render sets `RENDER=true` | `false` |
| `SEED_ON_STARTUP` | Run `seed.py` before uvicorn (`1` / `0`). The generated password is printed once to the process log and is not committed | `0` |
| `APP_BASE_URL` | Absolute link used in emails | empty |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Optional FastAPI-Mail | email skipped when host or from is empty |
| `SMTP_STARTTLS`, `SMTP_SSL` | Transport | STARTTLS on, SSL off |
| `UPLOAD_DIR` | Photo directory | `uploads` |
| `PORT` | Listen port in Docker | `8000` |

`postgres://` and `postgresql://` URLs are normalized to `postgresql+asyncpg://`. `sslmode=` is rewritten to `ssl=` for asyncpg. Moving from SQLite to Postgres does not require an application change.

## Render

`render.yaml` defines a Docker web service on the free plan. It generates `SECRET_KEY`, sets `TASKFLOW_ENV=production` and `COOKIE_SECURE=true`, and seeds the database on boot. This demo does not add a paid database or a paid plan.

The free instance disk is ephemeral. A restart or redeploy can delete the SQLite file. `SEED_ON_STARTUP=1` then loads the demo again and prints new random passwords once in the deploy logs. Those passwords are not written into git. Do not treat that disk as durable storage. If you already have a Postgres URL, set `DATABASE_URL` (`postgres://...` is enough); the application code stays the same.

Deploy: push this repo, create a Blueprint from `render.yaml` (or a new Web Service with the Dockerfile), and open the service URL. Read the one-time passwords from that deploy's logs.

## Fly.io

```bash
fly launch --no-deploy
fly secrets set SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" COOKIE_SECURE=true TASKFLOW_ENV=production
fly volumes create taskflow_data --size 1
```

Mount the volume at `/data` and set `DATABASE_URL=sqlite+aiosqlite:////data/taskflow.db`. `fly deploy` uses the Dockerfile. Set `SEED_ON_STARTUP=1` for the first boot if you want the demo accounts. The password is printed once in the machine logs. An existing `DATABASE_URL` for Postgres works without an application change. This repository does not provision a paid database.

## Railway

Create a project from this repo. Railway detects the Dockerfile. Set `SECRET_KEY`, `COOKIE_SECURE=true`, `TASKFLOW_ENV=production`, and `SEED_ON_STARTUP=1` only for a disposable demo. The container listens on Railway's `PORT`. A restart of the free disk can wipe SQLite and reseed; the new password appears once in the logs.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

GitHub Actions runs the same command on every push and pull request. The workflow uses the free GitHub-hosted runner and does not start a database service.

## API

Interactive reference: http://127.0.0.1:8000/docs

Mutations need the CSRF cookie and the `X-CSRF-Token` header. Sign in with `POST /login` (HTML form) or `POST /api/login` (JSON) to receive the session cookie.

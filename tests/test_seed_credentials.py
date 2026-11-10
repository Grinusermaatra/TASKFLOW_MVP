"""Demo passwords are generated at seed time and are not stored in the repo."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Split so the old demo secrets are not stored as a single string in git.
FIXED = ("Supervisor" + "123!", "Colaborador" + "123!")
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".html", ".txt", ".sh", ".js", ".css"}
SKIP_DIRS = {".venv", ".git", "uploads", "__pycache__", ".pytest_cache"}


def _passwords(stdout: str) -> dict[str, str]:
    found: dict[str, str] = {}
    username = None
    for line in stdout.splitlines():
        if "usuario:" in line:
            username = line.split("usuario:", 1)[1].strip()
        elif "contraseña:" in line and username:
            found[username] = line.split("contraseña:", 1)[1].strip()
            username = None
    return found


def _text_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS and not name.startswith(".git")]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix in TEXT_SUFFIXES:
                yield path


def test_repository_does_not_contain_fixed_demo_passwords():
    for path in _text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for secret in FIXED:
            assert secret not in text, f"{path} still contains a fixed demo password"


def test_seed_prints_a_password_once_and_rotate_replaces_it(tmp_path):
    database = tmp_path / "seed.db"
    uploads = tmp_path / "uploads"
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{database}",
            "UPLOAD_DIR": str(uploads),
            "SECRET_KEY": "seed-test-secret-not-the-development-default",
            "TASKFLOW_ENV": "development",
            "COOKIE_SECURE": "false",
            "SEED_ON_STARTUP": "0",
        }
    )
    env.pop("RENDER", None)

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "seed.py", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    first = run()
    assert first.returncode == 0, first.stderr
    passwords = _passwords(first.stdout)
    assert set(passwords) == {"ana.supervisor", "luis.colaborador", "maria.colaborador"}
    assert len(set(passwords.values())) == 3
    for value in passwords.values():
        assert value not in FIXED
        assert len(value) >= 16

    second = run()
    assert second.returncode == 0, second.stderr
    assert "no se vuelven a mostrar" in second.stdout.lower()
    assert _passwords(second.stdout) == {}
    for value in passwords.values():
        assert value not in second.stdout

    rotated = run("--rotate")
    assert rotated.returncode == 0, rotated.stderr
    replacement = _passwords(rotated.stdout)
    assert set(replacement) == set(passwords)
    for username, value in replacement.items():
        assert value != passwords[username]
        assert value not in first.stdout


def test_existing_database_gains_session_version(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    connection.commit()
    connection.close()
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{database}",
            "UPLOAD_DIR": str(tmp_path / "uploads"),
            "SECRET_KEY": "migration-test-secret-not-the-development-default",
            "TASKFLOW_ENV": "development",
            "COOKIE_SECURE": "false",
        }
    )
    env.pop("RENDER", None)
    code = "import asyncio\nfrom app.database import init_db\nasyncio.run(init_db())\n"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    connection = sqlite3.connect(database)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(users)")]
    connection.close()
    assert "session_version" in columns

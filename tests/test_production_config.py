"""Production refuses the development signing key and insecure cookies."""

import pytest

from app.config import INSECURE_SECRET, enforce_runtime_safety


def test_default_secret_refused_in_production():
    with pytest.raises(SystemExit, match="SECRET_KEY"):
        enforce_runtime_safety(
            secret_key=INSECURE_SECRET,
            cookie_secure=True,
            taskflow_env="production",
            render="false",
        )


def test_missing_secret_refused_in_production():
    with pytest.raises(SystemExit, match="SECRET_KEY"):
        enforce_runtime_safety(
            secret_key="  ",
            cookie_secure=True,
            taskflow_env="prod",
            render="",
        )


def test_render_flag_refuses_the_default_secret():
    with pytest.raises(SystemExit, match="SECRET_KEY"):
        enforce_runtime_safety(
            secret_key=INSECURE_SECRET,
            cookie_secure=True,
            taskflow_env="development",
            render="true",
        )


def test_cookie_secure_must_be_on_in_production():
    with pytest.raises(SystemExit, match="COOKIE_SECURE"):
        enforce_runtime_safety(
            secret_key="a-real-production-secret-value",
            cookie_secure=False,
            taskflow_env="production",
            render="false",
        )


def test_development_still_starts_with_the_default_secret():
    enforce_runtime_safety(
        secret_key=INSECURE_SECRET,
        cookie_secure=False,
        taskflow_env="development",
        render="false",
    )

"""Local seeding cannot accidentally target a configured application database."""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock
import subprocess
import sys

import pytest
from fastapi import FastAPI
from app.core.config import settings
from app.main import lifespan

spec = importlib.util.spec_from_file_location(
    "local_test_setup", Path(__file__).parents[1] / "scripts/local_test_setup.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def laboratory():
    url = "postgresql://local_test:synthetic@test-db:5432/test_delivery360_manual"
    return {
        "APP_ENV": "testing",
        "ENVIRONMENT": "testing",
        "DATABASE_URL": url,
        "DATABASE_URL_SYNC": url,
        "LOCAL_TEST_ID": "a" * 16,
        "LOCAL_TEST_PASSWORD": "x" * 32,
        **{
            key: "false"
            for key in (
                "EMAILS_ENABLED",
                "NOTIFICATIONS_ENABLED",
                "ENABLE_ELECTRONIC_INVOICING",
                "TRACKING_SCHEDULER_ENABLED",
            )
        },
    }


def test_explicit_lab_environment_is_accepted():
    module.validate_environment(laboratory())


def test_standalone_initializer_registers_relationships_in_a_fresh_interpreter():
    # Importing app.main in pytest otherwise hides missing model registrations.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.local_test_setup import load_models; load_models()",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "key,value",
    [
        ("ENVIRONMENT", "production"),
        ("APP_ENV", "production"),
        ("LOCAL_TEST_ID", ""),
        ("LOCAL_TEST_PASSWORD", "admin123"),
        (
            "DATABASE_URL",
            "postgresql://local_test:secret@production/test_delivery360_manual",
        ),
        ("DATABASE_URL", "postgresql://local_test:secret@test-db:5432/delivery360"),
        ("DATABASE_URL_SYNC", "postgresql://admin:secret@production:5432/production"),
        ("EMAILS_ENABLED", "true"),
        ("NOTIFICATIONS_ENABLED", "true"),
        ("TRACKING_SCHEDULER_ENABLED", "true"),
        ("ENABLE_ELECTRONIC_INVOICING", "true"),
    ],
)
def test_non_laboratory_or_external_operations_are_refused(key, value):
    env = laboratory()
    env[key] = value
    with pytest.raises(RuntimeError, match="isolated"):
        module.validate_environment(env)


@pytest.mark.parametrize("enabled", [True, False])
async def test_tracking_background_jobs_can_be_disabled_without_affecting_readiness(
    monkeypatch, enabled
):
    from app.services.tracking_scheduler import tracking_scheduler
    import app.main as main_module
    from types import SimpleNamespace

    start, stop, dispose = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(settings, "TRACKING_SCHEDULER_ENABLED", enabled)
    monkeypatch.setattr(tracking_scheduler, "start", start)
    monkeypatch.setattr(tracking_scheduler, "shutdown", stop)
    monkeypatch.setattr(main_module, "engine", SimpleNamespace(dispose=dispose))
    async with lifespan(FastAPI()):
        assert start.await_count == int(enabled)
    assert stop.await_count == int(enabled)
    dispose.assert_awaited_once()

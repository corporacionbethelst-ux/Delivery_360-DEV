"""Sentry wiring must work without sending test events to an external service."""

from unittest.mock import MagicMock

import pytest

from app.monitoring import sentry_config


def test_no_dsn_does_not_initialize_sdk(monkeypatch):
    monkeypatch.setattr(sentry_config.settings, "SENTRY_DSN", None)
    init = MagicMock()
    monkeypatch.setattr(sentry_config.sentry_sdk, "init", init)
    sentry_config.setup_sentry()
    init.assert_not_called()


def test_configured_sentry_uses_real_integration_classes(monkeypatch):
    init = MagicMock()
    monkeypatch.setattr(sentry_config.sentry_sdk, "init", init)
    sentry_config.setup_sentry(
        dsn="https://public@example.invalid/1", environment="testing"
    )
    options = init.call_args.kwargs
    assert options["environment"] == "testing"
    assert options["send_default_pii"] is False
    assert {type(integration) for integration in options["integrations"]} == {
        sentry_config.FastApiIntegration,
        sentry_config.SqlalchemyIntegration,
        sentry_config.RedisIntegration,
        sentry_config.CeleryIntegration,
    }


@pytest.mark.parametrize(
    "level", ["fatal", "critical", "error", "warning", "info", "debug"]
)
def test_message_level_is_forwarded_to_sdk(monkeypatch, level):
    capture = MagicMock()
    monkeypatch.setattr(sentry_config.sentry_sdk, "capture_message", capture)
    sentry_config.capture_message("Test event", level=level)
    capture.assert_called_once_with("Test event", level=level)

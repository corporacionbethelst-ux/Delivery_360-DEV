"""Optional installed SDK contracts; HTTP transports replaced, no external I/O."""

import json
from unittest.mock import Mock

import pytest
from app.core.config import settings
from app.services import notification_providers as providers


async def test_installed_firebase_current_api_and_timeout_offline(monkeypatch):
    firebase = pytest.importorskip("firebase_admin")
    from firebase_admin import credentials, _http_client
    from google.auth.credentials import AnonymousCredentials

    class Credential(credentials.Base):
        def get_credential(self):
            return AnonymousCredentials()

    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "FCM_PROJECT_ID", "offline-test-project")
    monkeypatch.setattr(
        settings, "FCM_CREDENTIALS_JSON_PATH", "not-read-offline-test.json"
    )
    monkeypatch.setattr(settings, "NOTIFICATION_PROVIDER_TIMEOUT_SECONDS", 7.0)
    monkeypatch.setattr(credentials, "Certificate", lambda path: Credential())
    calls = []

    def body(client, method, **kw):
        assert client.timeout == 7.0
        assert (
            method == "post"
            and "/v1/projects/offline-test-project/messages:send" in kw["url"]
        )
        calls.append(kw["json"]["message"]["token"])
        return {"name": "projects/offline-test-project/messages/offline"}

    monkeypatch.setattr(_http_client.JsonHttpClient, "body", body)
    app = providers._fcm_app(firebase, credentials, 7.0)
    try:
        result = await providers.send_push(
            ["device-one", "device-two"], "Title", "Body", {"id": "1"}
        )
        assert result.accepted and not result.invalid_tokens
        assert set(result.accepted_tokens) == {"device-one", "device-two"}
        assert set(calls) == {"device-one", "device-two"}
    finally:
        firebase.delete_app(app)


async def test_installed_twilio_request_and_timeout_offline(monkeypatch):
    pytest.importorskip("twilio")
    from twilio.http.http_client import TwilioHttpClient
    from twilio.http.response import Response

    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC" + "0" * 32)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "offline-test-token")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "+15551234567")
    monkeypatch.setattr(settings, "NOTIFICATION_PROVIDER_TIMEOUT_SECONDS", 7.0)
    calls = Mock()

    def request(client, method, url, **kw):
        assert client.timeout == 7.0 and method == "POST"
        assert kw["data"]["From"] == "+15551234567"
        assert kw["data"]["To"] == "+15557654321"
        assert kw["data"]["Body"] == "Offline body"
        calls()
        return Response(201, json.dumps({"sid": "SM" + "0" * 32, "status": "queued"}))

    monkeypatch.setattr(TwilioHttpClient, "request", request)
    assert await providers.send_sms("+15557654321", "Offline body")
    calls.assert_called_once()

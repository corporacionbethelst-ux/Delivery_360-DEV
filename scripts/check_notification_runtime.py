"""Exercise installed provider SDKs offline; never use runtime credentials.

Run from outside the source directory with PYTHONPATH pointing to backend.
The container check also runs with --network none and a read-only filesystem.
"""

import argparse
import asyncio
from contextlib import ExitStack
from importlib.util import find_spec
import json
from types import SimpleNamespace
from unittest.mock import patch


def check_base():
    for name in ("firebase_admin", "twilio"):
        if find_spec(name) is not None:
            raise RuntimeError("Unexpected optional provider in base runtime")


async def check_providers():
    from app.services import notification_providers as providers
    import firebase_admin as firebase
    from firebase_admin import credentials, _http_client
    from google.auth.credentials import AnonymousCredentials
    from twilio.http.http_client import TwilioHttpClient
    from twilio.http.response import Response

    class OfflineCredential(credentials.Base):
        def get_credential(self):
            return AnonymousCredentials()

    config = SimpleNamespace(
        NOTIFICATIONS_ENABLED=True,
        FCM_CREDENTIALS_JSON_PATH="offline-not-a-credential-file.json",
        FCM_PROJECT_ID="offline-project",
        NOTIFICATION_PROVIDER_TIMEOUT_SECONDS=7.0,
        NOTIFICATION_PROVIDER_CONCURRENCY=1,
        TWILIO_ACCOUNT_SID="AC" + "0" * 32,
        TWILIO_AUTH_TOKEN="offline-synthetic-token",
        TWILIO_FROM_NUMBER="+15551234567",
    )
    push_calls = []
    sms_calls = []

    def push_body(client, method, **kwargs):
        assert client.timeout == 7.0 and method == "post"
        assert kwargs["url"].endswith("/v1/projects/offline-project/messages:send")
        push_calls.append(kwargs["json"]["message"]["token"])
        return {"name": "projects/offline-project/messages/offline"}

    def sms_request(client, method, url, **kwargs):
        assert client.timeout == 7.0 and method == "POST"
        assert url.endswith("/Accounts/" + config.TWILIO_ACCOUNT_SID + "/Messages.json")
        assert kwargs["data"]["From"] == config.TWILIO_FROM_NUMBER
        assert kwargs["data"]["To"] == "+15557654321"
        assert kwargs["data"]["Body"] == "Offline body"
        sms_calls.append(True)
        return Response(201, json.dumps({"sid": "SM" + "0" * 32, "status": "queued"}))

    with patch.object(providers, "settings", config), patch.object(
        credentials, "Certificate", return_value=OfflineCredential()
    ) as certificate, patch.object(
        _http_client.JsonHttpClient, "body", push_body
    ), patch.object(
        TwilioHttpClient, "request", sms_request
    ):
        app = providers._fcm_app(firebase, credentials, 7.0)
        try:
            result = await providers.send_push(
                ["offline-one", "offline-two"], "Offline", "Body", {"id": "offline"}
            )
            assert result.accepted and not result.invalid_tokens
            assert set(result.accepted_tokens) == {"offline-one", "offline-two"}
            assert sorted(push_calls) == ["offline-one", "offline-two"]
            assert await providers.send_sms("+15557654321", "Offline body")
            assert len(sms_calls) == 1
            certificate.assert_called_once_with(config.FCM_CREDENTIALS_JSON_PATH)
            config.NOTIFICATIONS_ENABLED = False
            assert not await providers.send_sms("+15557654321", "Offline body")
            assert not (
                await providers.send_push(["offline-one"], "T", "B", {})
            ).accepted
            assert len(push_calls) == 2 and len(sms_calls) == 1
        finally:
            firebase.delete_app(app)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", choices=("base", "providers"), required=True)
    args = parser.parse_args()
    with ExitStack() as stack:
        guards = [
            stack.enter_context(
                patch(name, side_effect=RuntimeError("Network forbidden"))
            )
            for name in (
                "socket.create_connection",
                "socket.socket.connect",
                "socket.getaddrinfo",
            )
        ]
        if args.expected == "base":
            check_base()
        else:
            asyncio.run(check_providers())
        for guard in guards:
            guard.assert_not_called()
    print(
        json.dumps(
            {
                "runtime": args.expected,
                "offline_contract": "passed",
                "external_delivery_verified": False,
            }
        )
    )


if __name__ == "__main__":
    main()

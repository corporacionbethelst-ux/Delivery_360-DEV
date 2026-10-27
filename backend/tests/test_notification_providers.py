"""Provider acceptance, bounded offloading and cancellation without external I/O."""

import asyncio
import threading
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import settings
from app.services import notification_providers as providers
from app.services.omnichannel_service import OmnichannelNotificationService as Service
from app.models.notification import (
    NotificationLog,
    NotificationChannel,
    OmnichannelStatus,
)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "FCM_CREDENTIALS_JSON_PATH", "test-only.json")
    monkeypatch.setattr(settings, "FCM_PROJECT_ID", "test-project")
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "test-sid")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "+15551234567")
    monkeypatch.setattr(settings, "NOTIFICATION_PROVIDER_TIMEOUT_SECONDS", 7.0)
    monkeypatch.setattr(settings, "NOTIFICATION_PROVIDER_CONCURRENCY", 2)


@pytest.mark.parametrize("channel", ["push", "sms"])
@pytest.mark.parametrize("condition", ["disabled", "recipient", "credentials", "sdk"])
async def test_unavailable_provider_never_claims_success(
    configured, monkeypatch, channel, condition, caplog
):
    if condition == "disabled":
        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    if condition == "credentials":
        monkeypatch.setattr(settings, "FCM_CREDENTIALS_JSON_PATH", None)
        monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", None)
    loader = Mock(side_effect=ImportError("secret-address private-token"))
    monkeypatch.setattr(providers, "import_module", loader)
    svc = Service(None, redis_client=False)
    if channel == "push":
        assert not await svc.dispatch_push(
            [] if condition == "recipient" else ["device"], "T", "B"
        )
    else:
        assert not await svc.dispatch_sms(
            None if condition == "recipient" else "+15557654321", "B"
        )
    if condition != "sdk":
        loader.assert_not_called()
    assert "secret-address" not in caplog.text and "private-token" not in caplog.text


@pytest.mark.parametrize(
    "field,value",
    [
        ("TWILIO_ACCOUNT_SID", None),
        ("TWILIO_FROM_NUMBER", None),
        ("TWILIO_FROM_NUMBER", "local-number"),
    ],
)
async def test_sms_requires_complete_sender_configuration(
    configured, monkeypatch, field, value
):
    monkeypatch.setattr(settings, field, value)
    worker = Mock()
    monkeypatch.setattr(providers, "_sms_sync", worker)
    assert not await Service(None, redis_client=False).dispatch_sms(
        "+15557654321", "Body"
    )
    worker.assert_not_called()


@pytest.mark.parametrize(
    "phone", ["04121234567", "+01234567", "+12", "+1234567890123456"]
)
async def test_sms_rejects_invalid_e164_without_call(configured, monkeypatch, phone):
    worker = Mock()
    monkeypatch.setattr(providers, "_sms_sync", worker)
    assert not await providers.send_sms(phone, "Body")
    worker.assert_not_called()


@pytest.mark.parametrize("value", [0, 61, float("inf"), float("nan"), True])
async def test_invalid_http_timeout_fails_safely(configured, monkeypatch, value):
    monkeypatch.setattr(settings, "NOTIFICATION_PROVIDER_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError):
        providers.provider_timeout()


@pytest.mark.parametrize("value", [0, 17, True, 1.5])
async def test_invalid_concurrency_never_starts_thread(configured, monkeypatch, value):
    monkeypatch.setattr(settings, "NOTIFICATION_PROVIDER_CONCURRENCY", value)
    call = Mock()
    with pytest.raises(ValueError):
        await providers.run_provider(call)
    call.assert_not_called()


def fake_fcm(monkeypatch, responses):
    class UnregisteredError(Exception):
        pass

    apps = {}
    firebase = NS(
        get_app=Mock(side_effect=lambda name: apps[name] if name in apps else missing())
    )

    def init(credential, options, name):
        apps[name] = NS(options=options)
        return apps[name]

    firebase.initialize_app = Mock(side_effect=init)
    credentials = NS(Certificate=Mock(return_value=object()))
    messaging = NS(
        UnregisteredError=UnregisteredError,
        MulticastMessage=lambda **kw: NS(**kw),
        Notification=lambda **kw: NS(**kw),
        send_each_for_multicast=Mock(side_effect=responses),
    )
    modules = {
        "firebase_admin": firebase,
        "firebase_admin.credentials": credentials,
        "firebase_admin.messaging": messaging,
    }
    monkeypatch.setattr(providers, "import_module", modules.__getitem__)
    return firebase, credentials, messaging


def missing():
    raise ValueError("No app")


async def test_fcm_uses_current_api_initializes_named_app_and_reuses_it(
    configured, monkeypatch
):
    firebase, credentials, messaging = fake_fcm(
        monkeypatch,
        lambda message, **kw: NS(responses=[NS(success=True)] * len(message.tokens)),
    )
    assert (
        await providers.send_push(["one", "one", "two"], "Title", "Body", {"id": "1"})
    ).accepted
    assert (await providers.send_push(["one"], "Title", "Body", {})).accepted
    firebase.initialize_app.assert_called_once()
    credentials.Certificate.assert_called_once_with("test-only.json")
    assert firebase.initialize_app.call_args.args[1] == {
        "httpTimeout": 7.0,
        "projectId": "test-project",
    }
    first = messaging.send_each_for_multicast.call_args_list[0].args[0]
    assert first.tokens == ["one", "two"] and first.data == {"id": "1"}


@pytest.mark.parametrize("failure", ["exception", "malformed"])
async def test_fcm_chunks_large_multicasts_and_keeps_partial_acceptance(
    configured, monkeypatch, failure
):
    def send(message, **kw):
        if "device-50" in message.tokens:
            if failure == "malformed":
                return NS(responses=[])
            raise RuntimeError("transient failure")
        return NS(responses=[NS(success=True)] * len(message.tokens))

    _, _, messaging = fake_fcm(monkeypatch, send)
    result = await providers.send_push(
        [f"device-{i}" for i in range(501)], "T", "B", {}
    )
    assert result.accepted and not result.invalid_tokens
    assert messaging.send_each_for_multicast.call_count == 11
    assert all(
        len(call.args[0].tokens) <= 50
        for call in messaging.send_each_for_multicast.call_args_list
    )


async def test_only_unregistered_devices_count_as_invalid(configured, monkeypatch):
    _, _, messaging = fake_fcm(monkeypatch, None)
    messaging.send_each_for_multicast.side_effect = lambda *a, **kw: NS(
        responses=[
            NS(success=False, exception=messaging.UnregisteredError()),
            NS(success=False, exception=RuntimeError("quota unavailable")),
            NS(success=True),
        ]
    )
    result = await providers.send_push(["invalid", "temporary", "valid"], "T", "B", {})
    assert result.accepted and result.invalid_tokens == ("invalid",)
    assert result.accepted_tokens == ("valid",)


@pytest.mark.parametrize("tokens,data", [([], {}), ([""], {}), (["one"], {"id": 1})])
async def test_invalid_push_input_does_not_start_sdk(
    configured, monkeypatch, tokens, data
):
    worker = Mock()
    monkeypatch.setattr(providers, "_push_sync", worker)
    assert not (await providers.send_push(tokens, "T", "B", data)).accepted
    worker.assert_not_called()


@pytest.mark.parametrize("failure", ["outage", "malformed"])
async def test_fcm_failure_never_invalidates_every_device(
    configured, monkeypatch, failure
):
    _, _, messaging = fake_fcm(monkeypatch, None)
    messaging.send_each_for_multicast.side_effect = (
        RuntimeError("private-provider-data") if failure == "outage" else None
    )
    if failure == "malformed":
        messaging.send_each_for_multicast.return_value = NS(responses=[])
    svc = Service(None, redis_client=False)
    svc._mark_token_failures = AsyncMock()
    assert not await svc.dispatch_push(["one"], "T", "B")
    svc._mark_token_failures.assert_not_awaited()


@pytest.mark.parametrize(
    "status,sid,accepted",
    [
        ("queued", "SM-test", True),
        ("failed", "SM-test", False),
        ("undelivered", "SM-test", False),
        ("canceled", "SM-test", False),
        ("queued", "", False),
    ],
)
async def test_twilio_timeout_acceptance_and_cleanup(
    configured, monkeypatch, status, sid, accepted
):
    http = NS(session=NS(close=Mock()))
    http_type = Mock(return_value=http)
    create = Mock(return_value=NS(sid=sid, status=status))
    client_type = Mock(return_value=NS(messages=NS(create=create)))
    modules = {
        "twilio.rest": NS(Client=client_type),
        "twilio.http.http_client": NS(TwilioHttpClient=http_type),
    }
    monkeypatch.setattr(providers, "import_module", modules.__getitem__)
    assert await providers.send_sms("+15557654321", "B" * 1800) is accepted
    http_type.assert_called_once_with(timeout=7.0, max_retries=0)
    client_type.assert_called_once_with("test-sid", "test-token", http_client=http)
    assert create.call_args.kwargs == {
        "body": "B" * 1600,
        "from_": "+15551234567",
        "to": "+15557654321",
    }
    http.session.close.assert_called_once()


@pytest.mark.parametrize("failure", ["send", "close"])
async def test_twilio_errors_are_private_and_cleanup_preserves_acceptance(
    configured, monkeypatch, caplog, failure
):
    close = Mock(
        side_effect=(
            RuntimeError("private-number secret-token") if failure == "close" else None
        )
    )
    http = NS(session=NS(close=close))
    create = Mock(
        return_value=NS(sid="SM-test", status="queued"),
        side_effect=(
            RuntimeError("private-number secret-token") if failure == "send" else None
        ),
    )
    modules = {
        "twilio.rest": NS(Client=Mock(return_value=NS(messages=NS(create=create)))),
        "twilio.http.http_client": NS(TwilioHttpClient=Mock(return_value=http)),
    }
    monkeypatch.setattr(providers, "import_module", modules.__getitem__)
    assert await Service(None, redis_client=False).dispatch_sms(
        "+15557654321", "Body"
    ) is (failure == "close")
    close.assert_called_once()
    assert "private-number" not in caplog.text and "secret-token" not in caplog.text


@pytest.mark.parametrize("channel", [NotificationChannel.PUSH, NotificationChannel.SMS])
async def test_initial_external_exception_never_persists_private_diagnostics(
    channel, caplog
):
    db = NS(commit=AsyncMock(), execute=AsyncMock())
    db.execute.return_value.scalars = lambda: NS(all=lambda: [])
    svc = Service(db, redis_client=False)
    worker = AsyncMock(
        side_effect=RuntimeError("private-address secret-provider-value")
    )
    setattr(
        svc,
        "dispatch_push" if channel == NotificationChannel.PUSH else "dispatch_sms",
        worker,
    )
    log = NotificationLog(channel=channel, retry_count=0)
    await svc._dispatch_one(
        log, NS(id="user", phone="+15557654321"), NS(code="test"), "Body"
    )
    assert log.status == OmnichannelStatus.PENDIENTE and log.retry_count == 1
    assert log.error_message == "External dispatch failed"
    assert (
        "private-address" not in caplog.text
        and "secret-provider-value" not in caplog.text
    )


async def test_concurrency_limit_bounds_started_sdk_calls(configured):
    loop = asyncio.get_running_loop()
    ready, finish = asyncio.Event(), threading.Event()
    guard = threading.Lock()
    active = maximum = started = 0

    def call():
        nonlocal active, maximum, started
        with guard:
            active += 1
            started += 1
            maximum = max(maximum, active)
            if started == 2:
                loop.call_soon_threadsafe(ready.set)
        try:
            assert finish.wait(5)
            return True
        finally:
            with guard:
                active -= 1

    tasks = [asyncio.create_task(providers.run_provider(call)) for _ in range(4)]
    try:
        await asyncio.wait_for(ready.wait(), 3)
        assert started == 2
        finish.set()
        assert all(await asyncio.wait_for(asyncio.gather(*tasks), 3))
        assert started == 4 and maximum == 2
    finally:
        finish.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_sdk_thread_does_not_block_loop_and_cancellation_drains(configured):
    entered, finish = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    notified = asyncio.Event()

    def call():
        entered.set()
        loop.call_soon_threadsafe(notified.set)
        assert finish.wait(5)
        return True

    task = asyncio.create_task(providers.run_provider(call))
    try:
        await asyncio.wait_for(notified.wait(), 3)
        assert entered.is_set()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # repeated cancellation must not abandon the running SDK
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        finish.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancelled_gate_waiter_never_starts_sdk(configured, monkeypatch):
    monkeypatch.setattr(settings, "NOTIFICATION_PROVIDER_CONCURRENCY", 1)
    entered, finish = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def call():
        loop.call_soon_threadsafe(entered.set)
        assert finish.wait(5)

    first = asyncio.create_task(providers.run_provider(call))
    second = None
    worker = Mock()
    try:
        await asyncio.wait_for(entered.wait(), 3)
        second = asyncio.create_task(providers.run_provider(worker))
        await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        worker.assert_not_called()
    finally:
        finish.set()
        await asyncio.gather(
            first, *([second] if second else []), return_exceptions=True
        )


@pytest.mark.parametrize(
    "statuses,counts",
    [
        (["PENDIENTE"], (0, 1, 0)),
        (["ENVIADO"], (1, 0, 0)),
        (["FALLIDO"], (0, 0, 1)),
        (["ENVIADO", "ENTREGADO", "LEIDO", "PENDIENTE", "FALLIDO"], (3, 1, 1)),
    ],
)
async def test_test_send_counts_acceptance_separately_from_queue_and_failure(
    statuses, counts
):
    from uuid import uuid4
    from app.api.v1.notifications import test_send, TestSendRequest

    logs = [
        NS(
            id=uuid4(),
            channel=NotificationChannel.PUSH,
            status=OmnichannelStatus(status),
        )
        for status in statuses
    ]
    response = await test_send(
        TestSendRequest(template_code="test"),
        service=NS(send=AsyncMock(return_value=logs)),
        current_user=NS(id=uuid4()),
    )
    assert response["created"] == len(logs)
    assert (response["sent"], response["queued"], response["failed"]) == counts

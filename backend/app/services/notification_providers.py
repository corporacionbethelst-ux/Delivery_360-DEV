"""Optional synchronous SDKs isolated from the event loop and SQL sessions."""

import asyncio
import hashlib
from importlib import import_module
import math
import logging
import re
import threading
import weakref
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, TypeVar

from app.core.config import settings

T = TypeVar("T")
logger = logging.getLogger(__name__)
_app_lock = threading.Lock()
_gates: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, weakref.WeakValueDictionary[int, asyncio.Semaphore]
] = weakref.WeakKeyDictionary()
_phone = re.compile(r"\+[1-9][0-9]{6,14}\Z")


@dataclass(frozen=True)
class PushResult:
    accepted: bool
    invalid_tokens: tuple[str, ...] = ()


def provider_timeout() -> float:
    value = settings.NOTIFICATION_PROVIDER_TIMEOUT_SECONDS
    if isinstance(value, bool) or not math.isfinite(value) or not 1 <= value <= 60:
        raise ValueError("Invalid notification provider timeout")
    return float(value)


async def run_provider(call: Callable[[], T]) -> T:
    """Bound concurrent calls and drain a started SDK call before cancellation.

    SDK HTTP timeouts apply per request, not to the entire multicast operation.
    Normal task cancellation retains the slot/SQL owner until the thread ends.
    Process/connection loss cannot provide external fencing or exactly-once I/O.
    """
    limit = settings.NOTIFICATION_PROVIDER_CONCURRENCY
    if type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError("Invalid notification provider concurrency")
    gates = _gates.setdefault(asyncio.get_running_loop(), weakref.WeakValueDictionary())
    gate = gates.get(limit)
    if gate is None:
        gate = asyncio.Semaphore(limit)
        gates[limit] = gate
    async with gate:
        task = asyncio.create_task(asyncio.to_thread(call))
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancelled = True
            except Exception:
                if cancelled:
                    raise asyncio.CancelledError from None
                raise
        if cancelled:
            raise asyncio.CancelledError
        return result


def _fcm_app(firebase: Any, credentials: Any, timeout: float) -> Any:
    path = settings.FCM_CREDENTIALS_JSON_PATH
    key = f"{path}|{settings.FCM_PROJECT_ID}|{timeout}"
    name = "delivery360-" + hashlib.sha256(key.encode()).hexdigest()[:24]
    with _app_lock:
        try:
            return firebase.get_app(name)
        except ValueError:
            options: dict[str, Any] = {"httpTimeout": timeout}
            if settings.FCM_PROJECT_ID:
                options["projectId"] = settings.FCM_PROJECT_ID
            return firebase.initialize_app(
                credentials.Certificate(path), options, name=name
            )


def _push_sync(
    tokens: list[str], title: str, body: str, data: dict[str, str]
) -> PushResult:
    firebase = import_module("firebase_admin")
    credentials = import_module("firebase_admin.credentials")
    messaging = import_module("firebase_admin.messaging")
    app = _fcm_app(firebase, credentials, provider_timeout())
    accepted = False
    invalid: list[str] = []
    # FCM permits 500; smaller chunks also bound the SDK's own thread fan-out.
    for offset in range(0, len(tokens), 50):
        batch = tokens[offset : offset + 50]
        message = messaging.MulticastMessage(
            tokens=batch,
            notification=messaging.Notification(title=title, body=body),
            data=data,
        )
        try:
            response = messaging.send_each_for_multicast(message, app=app)
        except Exception:
            # An outage or ambiguous request failure does not invalidate devices.
            continue
        if len(response.responses) != len(batch):
            continue
        for token, item in zip(batch, response.responses):
            if item.success:
                accepted = True
            elif isinstance(item.exception, messaging.UnregisteredError):
                invalid.append(token)
    return PushResult(accepted, tuple(invalid))


async def send_push(
    tokens: list[str], title: str, body: str, data: dict[str, Any]
) -> PushResult:
    if not settings.NOTIFICATIONS_ENABLED or not settings.FCM_CREDENTIALS_JSON_PATH:
        return PushResult(False)
    if not tokens or any(not isinstance(t, str) or not t.strip() for t in tokens):
        return PushResult(False)
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()):
        return PushResult(False)
    unique = list(dict.fromkeys(tokens))
    return await run_provider(partial(_push_sync, unique, title, body, dict(data)))


def _sms_sync(phone: str, message: str) -> bool:
    client_type = import_module("twilio.rest").Client
    http_type = import_module("twilio.http.http_client").TwilioHttpClient
    http = http_type(timeout=provider_timeout(), max_retries=0)
    try:
        client = client_type(
            settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, http_client=http
        )
        result = client.messages.create(
            body=message[:1600], from_=settings.TWILIO_FROM_NUMBER, to=phone
        )
        return (
            isinstance(result.sid, str)
            and bool(result.sid.strip())
            and result.status not in {"failed", "undelivered", "canceled"}
        )
    finally:
        if http.session is not None:
            try:
                http.session.close()
            except Exception:
                # Cleanup cannot erase an acknowledgement already received.
                logger.warning("Notification SMS transport cleanup failed")


async def send_sms(phone: str | None, message: str) -> bool:
    if not (
        settings.NOTIFICATIONS_ENABLED
        and settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and settings.TWILIO_FROM_NUMBER
        and phone
    ):
        return False
    if not _phone.fullmatch(phone) or not _phone.fullmatch(settings.TWILIO_FROM_NUMBER):
        return False
    return await run_provider(partial(_sms_sync, phone, message))

"""Signed read positions, not access tokens or database snapshots."""

import base64
from datetime import datetime
import hashlib
import hmac
import json
import re
from uuid import UUID

from fastapi import HTTPException

from app.core.config import settings


def encode_cursor(scope: list, requested_at: datetime | None, payout_id: UUID) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "scope": scope,
            "at": requested_at.isoformat() if requested_at is not None else None,
            "id": str(payout_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    data = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    signature = hmac.new(
        settings.SECRET_KEY.encode(),
        b"payout-page-v1:" + data.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{data}.{signature}"


def decode_cursor(cursor: str, scope: list) -> tuple[datetime | None, UUID]:
    try:
        if len(cursor) > 2048 or not re.fullmatch(
            r"[A-Za-z0-9_-]+\.[0-9a-f]{64}", cursor
        ):
            raise ValueError("Invalid cursor shape")
        data, signature = cursor.split(".")
        expected = hmac.new(
            settings.SECRET_KEY.encode(),
            b"payout-page-v1:" + data.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid cursor signature")
        payload = json.loads(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "scope", "at", "id"}
            or type(payload["v"]) is not int
            or payload["v"] != 1
            or payload["scope"] != scope
        ):
            raise ValueError("Cursor belongs to another query")
        payout_id = UUID(payload["id"])
        at = payload["at"]
        requested_at = None
        if at is not None:
            requested_at = datetime.fromisoformat(at)
            if requested_at.tzinfo is not None or requested_at.isoformat() != at:
                raise ValueError("Invalid database timestamp")
        return requested_at, payout_id
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail="La continuación no corresponde a esta consulta. Vuelve al inicio.",
        ) from None

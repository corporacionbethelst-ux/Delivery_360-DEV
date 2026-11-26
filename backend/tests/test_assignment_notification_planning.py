"""SQL-only channel planning, immutable event keys and safe assignment text."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.notification import (
    NotificationChannel as Channel,
    OmnichannelStatus as Status,
)
from app.services.assignment_notifications import enqueue_assignment_notice
from app.services.omnichannel_service import OmnichannelNotificationService as Service


@pytest.fixture
def context(monkeypatch):
    order = SimpleNamespace(
        id=uuid4(),
        external_id="ORD-1",
        customer_name="<script>Cliente</script>",
        pickup_address="Origen",
        delivery_address="Destino",
    )
    delivery = SimpleNamespace(id=uuid4(), rider_id=uuid4())
    user = SimpleNamespace(id=uuid4(), is_active=True)
    template = SimpleNamespace(
        channel=Channel.PUSH,
        body_template="Orden {{delivery_code}} para {{customer_name}}",
        subject="Asignación {{delivery_code}}",
    )
    db = MagicMock()
    db.flush = AsyncMock()
    db.scalar = AsyncMock(return_value=template)
    db.commit = AsyncMock()
    channels = AsyncMock(return_value=[Channel.PUSH, Channel.PUSH, Channel.IN_APP])
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(Service, "resolve_channels", channels)
    return SimpleNamespace(
        db=db,
        order=order,
        delivery=delivery,
        user=user,
        template=template,
        channels=channels,
    )


@pytest.mark.asyncio
async def test_plans_internal_and_deduplicated_external_work_without_sending(
    context, monkeypatch
):
    c = context
    send = AsyncMock(side_effect=AssertionError("No dispatch during assignment"))
    monkeypatch.setattr(Service, "send", send)
    event = uuid4()
    await enqueue_assignment_notice(
        c.db, c.order, c.delivery, c.user, event, "order_manual"
    )
    rows = [call.args[0] for call in c.db.add.call_args_list]
    assert len(rows) == 2
    internal, external = rows
    assert internal.channel == Channel.IN_APP and internal.status == Status.ENVIADO
    assert external.channel == Channel.PUSH and external.status == Status.PENDIENTE
    assert external.next_retry_at is not None
    # Stored text remains text; email escapes it at the transport boundary.
    assert c.order.customer_name in external.body
    assert len({row.dedupe_key for row in rows}) == 2
    assert json.loads(internal.payload_json)["assignment_event_id"] == str(event)
    c.db.commit.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variable",
    [
        "payment_cents",
        "amount_cents",
        "amount",
        "total",
        "bonus",
        "currency",
        "currency_code",
    ],
)
@pytest.mark.parametrize("field", ["subject", "body_template"])
async def test_legacy_money_templates_require_review_without_inventing_earnings(
    context, variable, field
):
    c = context
    setattr(c.template, field, "{{ " + variable + " }}")
    await enqueue_assignment_notice(
        c.db, c.order, c.delivery, c.user, uuid4(), "order_manual"
    )
    rows = [call.args[0] for call in c.db.add.call_args_list]
    assert rows[0].status == Status.ENVIADO
    assert rows[1].status == Status.FALLIDO and rows[1].next_retry_at is None
    assert "revisión" in rows[1].error_message
    assert "payment_cents" not in json.loads(rows[1].payload_json)


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["disabled", "missing_template", "no_channels"])
async def test_internal_receipt_survives_external_policy_conditions(
    context, monkeypatch, condition
):
    c = context
    if condition == "disabled":
        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    if condition == "missing_template":
        c.db.scalar.return_value = None
    if condition == "no_channels":
        c.channels.return_value = []
    await enqueue_assignment_notice(
        c.db, c.order, c.delivery, c.user, uuid4(), "order_manual"
    )
    assert c.db.add.call_count == 1
    assert c.db.add.call_args.args[0].channel == Channel.IN_APP

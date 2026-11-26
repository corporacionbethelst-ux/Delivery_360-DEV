"""Technical closure preserves original evidence and cannot attest a payment."""

import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, func, update, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.test_managed_external_postgresql import (  # noqa: F401
    payment_db,
    cancel_db,
    sla_db,
    runtime_db,
    assignment_db,
    managed_db,
    enqueue,
)
from tests.test_terminal_external_postgresql import headers, worker
from app.models.audit_log import AuditLog, ActionType
from app.models.notification import (
    NotificationLog,
    NotificationChannel as C,
    OmnichannelStatus as S,
    utc_now_naive,
)
from app.models.financial import Financial
from app.models.user import User, UserRole
from app.services.omnichannel_service import OmnichannelNotificationService as Service
from app.services.audit_service import AuditService
from app.services import technical_notification_resolution as technical
from app.services.terminal_notifications import MANAGED_EVENTS


async def historical(ctx, code="nuevo_pedido_asignado", *, due=False):
    _, sessions, ids = ctx
    async with sessions() as db:
        log = NotificationLog(
            id=uuid4(),
            user_id=ids["owner"],
            delivery_id=ids["delivery"],
            template_code=code,
            channel=C.EMAIL,
            status=S.PENDIENTE if due else S.FALLIDO,
            payload_json="{invalid historical payload",
            title="Título original",
            body="Cuerpo original",
            error_message="Error original",
            retry_count=2,
            next_retry_at=utc_now_naive() - timedelta(seconds=10) if due else None,
        )
        db.add(log)
        await db.commit()
        return log


def listing(ctx, view="pending", **params):
    client, _, ids = ctx
    return client.get(
        "/api/v1/notifications/terminal-dispatch/review",
        params={"view": view, **params},
        headers=headers(ids),
    )


def body(log):
    return dict(
        resolution_id=str(uuid4()),
        revision=technical.revision(log),
        action="close_without_resend",
        reference="Caso técnico-126",
        note="Seguimiento conservado sin reenvío",
    )


def post(ctx, log, payload, actor="staff"):
    client, _, ids = ctx
    return client.post(
        f"/api/v1/notifications/terminal-dispatch/{log.id}/resolve",
        json=payload,
        headers=headers(ids, actor),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("code", MANAGED_EVENTS)
async def test_each_event_closes_with_receipt_preserving_evidence_and_money(
    managed_db, code
):
    _, sessions, _ = managed_db
    log = await historical(managed_db, code)
    data = listing(managed_db).json()["items"][0]
    assert data["state"] == "invalid" and data["revision"] == technical.revision(log)
    assert data["diagnostic"] == "unverifiable_record"
    async with sessions() as db:
        before = await db.scalar(select(func.count()).select_from(Financial))
    payload = body(log)
    result = post(managed_db, log, payload)
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert (
        receipt["state"] == "resolved" and receipt["action"] == "close_without_resend"
    )
    assert receipt["resolution_id"] == payload["resolution_id"] and receipt[
        "resolved_at"
    ].endswith("+00:00")
    assert listing(managed_db).json()["items"] == []
    closed = listing(managed_db, "resolved").json()["items"]
    assert (
        len(closed) == 1
        and closed[0]["state"] == "resolved"
        and closed[0]["resolution"] == receipt
    )
    assert closed[0]["delivery_id"] == str(log.delivery_id)
    async with sessions() as db:
        saved = await db.get(NotificationLog, log.id)
        for field in (
            "payload_json",
            "title",
            "body",
            "error_message",
            "retry_count",
            "sent_at",
        ):
            assert getattr(saved, field) == getattr(log, field)
        assert saved.status == S.FALLIDO and saved.next_retry_at is None
        assert await db.scalar(select(func.count()).select_from(Financial)) == before
        audit = await db.get(AuditLog, receipt["audit_id"])
        assert audit.old_values["revision"] == payload["revision"]
        assert audit.new_values["action"] == "close_without_resend"
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [None, "reference", "note", "resolution_id", "revision", "actor"]
)
async def test_replay_requires_same_actor_key_and_frozen_decision(managed_db, change):
    log = await historical(managed_db)
    payload = body(log)
    first = post(managed_db, log, payload)
    assert first.status_code == 200
    repeated = dict(payload)
    if change in ("reference", "note"):
        repeated[change] += " diferente"
    if change == "resolution_id":
        repeated[change] = str(uuid4())
    if change == "revision":
        repeated[change] = "f" * 64
    if change == "actor":
        async with managed_db[1]() as db:
            await db.execute(
                update(User)
                .where(User.id == managed_db[2]["owner"])
                .values(role=UserRole.GERENTE)
            )
            await db.commit()
    result = post(managed_db, log, repeated, "owner" if change == "actor" else "staff")
    assert result.status_code == (200 if change is None else 409), result.text
    if change is None:
        assert result.json() == first.json()
    async with managed_db[1]() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type == technical.RESOURCE)
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    ["body", "payload_json", "error_message", "retry_count", "next_retry_at", "status"],
)
async def test_changed_record_rejects_a_stale_resolution(managed_db, field):
    log = await historical(managed_db)
    payload = body(log)
    async with managed_db[1]() as db:
        saved = await db.get(NotificationLog, log.id)
        value = (
            S.ENVIADO
            if field == "status"
            else (
                utc_now_naive()
                if field == "next_retry_at"
                else 3 if field == "retry_count" else "Modificado"
            )
        )
        setattr(saved, field, value)
        await db.commit()
    result = post(managed_db, log, payload)
    assert result.status_code == 409 and "cambió" in result.json()["detail"]
    assert not listing(managed_db, "resolved").json()["items"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["queued", "uncertain", "accepted"])
async def test_live_attempts_are_not_administratively_closed(managed_db, state):
    log = await enqueue(managed_db, "assignment")
    if state != "queued":
        Service.dispatch_email.return_value = state == "accepted"
        assert await worker(managed_db[1]) == 1
    async with managed_db[1]() as db:
        log = await db.get(NotificationLog, log.id)
    assert post(managed_db, log, body(log)).status_code == 409
    assert listing(managed_db, "resolved").json()["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", ["SUPERADMIN", "GERENTE", "OPERADOR", "REPARTIDOR", "CLIENTE", "AUDITOR"]
)
async def test_resolution_and_history_require_management(managed_db, role):
    log = await historical(managed_db)
    async with managed_db[1]() as db:
        await db.execute(
            update(User)
            .where(User.id == managed_db[2]["staff"])
            .values(role=UserRole(role))
        )
        await db.commit()
    allowed = role in ("SUPERADMIN", "GERENTE")
    assert listing(managed_db).status_code == (200 if allowed else 403)
    assert listing(managed_db, "resolved").status_code == (200 if allowed else 403)
    assert post(managed_db, log, body(log)).status_code == (200 if allowed else 403)


@pytest.mark.asyncio
async def test_role_revocation_after_authentication_is_rechecked(
    managed_db, monkeypatch
):
    log = await historical(managed_db)
    original = technical.resolve

    async def revoked(db, *args):
        await db.execute(
            update(User)
            .where(User.id == managed_db[2]["staff"])
            .values(role=UserRole.CLIENTE)
        )
        await db.commit()
        return await original(db, *args)

    monkeypatch.setattr(technical, "resolve", revoked)
    assert post(managed_db, log, body(log)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"reference": "bad"},
        {"reference": "        "},
        {"reference": "Valid\nreference"},
        {"revision": "A" * 64},
        {"resolution_id": "bad"},
        {"action": "resend"},
        {"attempt_id": str(uuid4())},
        {"note": "x" * 501},
    ],
)
async def test_invalid_requests_do_not_write_a_resolution(managed_db, changes):
    log = await historical(managed_db)
    assert post(managed_db, log, {**body(log), **changes}).status_code == 422
    assert listing(managed_db, "resolved").json()["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["internal", "generic", "missing"])
async def test_other_records_cannot_enter_the_technical_closure_protocol(
    managed_db, scope
):
    log = await historical(managed_db)
    async with managed_db[1]() as db:
        saved = await db.get(NotificationLog, log.id)
        if scope == "internal":
            saved.channel = C.IN_APP
        if scope == "generic":
            saved.template_code = "generic_test"
        await db.commit()
    if scope == "missing":
        log.id = uuid4()
    assert post(managed_db, log, body(log)).status_code == (
        404 if scope == "missing" else 409
    )


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_closure_and_audit_then_same_request_recovers(
    managed_db, monkeypatch
):
    log = await historical(managed_db, due=True)
    payload = body(log)
    original = AsyncSession.commit

    async def commit(db):
        if any(
            isinstance(obj, AuditLog) and obj.resource_type == technical.RESOURCE
            for obj in db.new
        ):
            raise RuntimeError("resolution commit failed")
        await original(db)

    monkeypatch.setattr(AsyncSession, "commit", commit)
    assert post(managed_db, log, payload).status_code == 500
    async with managed_db[1]() as db:
        saved = await db.get(NotificationLog, log.id)
        assert saved.status == S.PENDIENTE and saved.next_retry_at == log.next_retry_at
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type == technical.RESOURCE)
            )
            == 0
        )
    monkeypatch.setattr(AsyncSession, "commit", original)
    assert post(managed_db, log, payload).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("same_key", [True, False])
async def test_two_managers_cannot_create_two_closures(managed_db, same_key):
    log = await historical(managed_db)
    first = body(log)
    second = first if same_key else body(log)
    results = await asyncio.gather(
        asyncio.to_thread(post, managed_db, log, first),
        asyncio.to_thread(post, managed_db, log, second),
    )
    assert sorted(r.status_code for r in results) == (
        [200, 200] if same_key else [200, 409]
    )
    async with managed_db[1]() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type == technical.RESOURCE)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_worker_cannot_claim_technical_record_while_closure_commits(
    managed_db, monkeypatch
):
    _, sessions, ids = managed_db
    log = await historical(managed_db, due=True)
    started, release = asyncio.Event(), asyncio.Event()
    async with sessions() as db:
        original = db.commit

        async def commit():
            started.set()
            await release.wait()
            await original()

        monkeypatch.setattr(db, "commit", commit)
        task = asyncio.create_task(
            technical.resolve(
                db,
                log.id,
                ids["staff"],
                uuid4(),
                technical.revision(log),
                technical.ACTION,
                "Caso técnico-126",
                "",
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 5)
            assert await asyncio.wait_for(worker(sessions), 5) == 0
        finally:
            release.set()
            await task
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_changes_force_a_fresh_technical_read(managed_db):
    log = await historical(managed_db, due=True)
    payload = body(log)
    assert await worker(managed_db[1]) == 1
    assert post(managed_db, log, payload).status_code == 409
    async with managed_db[1]() as db:
        fresh = await db.get(NotificationLog, log.id)
    assert post(managed_db, fresh, body(fresh)).status_code == 200
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_retention_keeps_notice_and_its_resolution_but_purges_unrelated_audits(
    managed_db,
):
    log = await historical(managed_db)
    receipt = post(managed_db, log, body(log)).json()
    old = utc_now_naive() - timedelta(days=1000)
    async with managed_db[1]() as db:
        saved = await db.get(NotificationLog, log.id)
        saved.created_at = old
        audit = await db.get(AuditLog, receipt["audit_id"])
        audit.created_at = old
        db.add(
            AuditLog(
                user_id=managed_db[2]["staff"],
                action_type=ActionType.READ,
                resource_type=None,
                created_at=old,
            )
        )
        await db.commit()
        assert await AuditService(db).cleanup_old_logs() == 1
        await Service(db, redis_client=False).purge_old_logs()
    closed = listing(managed_db, "resolved").json()["items"]
    assert (
        len(closed) == 1 and closed[0]["resolution"]["audit_id"] == receipt["audit_id"]
    )
    assert listing(managed_db).json()["items"] == []


@pytest.mark.asyncio
async def test_resolved_view_pagination_is_separate_from_pending(managed_db):
    logs = [await historical(managed_db) for _ in range(3)]
    for log in logs[:2]:
        assert post(managed_db, log, body(log)).status_code == 200
    first = listing(managed_db, "resolved", limit=1).json()
    second = listing(managed_db, "resolved", limit=1, offset=1).json()
    assert first["next_offset"] == 1 and second["next_offset"] is None
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert [row["id"] for row in listing(managed_db).json()["items"]] == [
        str(logs[2].id)
    ]


@pytest.mark.asyncio
async def test_canonical_audit_reference_also_matches_sqlite_compact_uuids():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    first, second = uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("CREATE TABLE notification_logs (id CHAR(32) PRIMARY KEY)")
            )
            await connection.execute(
                text(
                    "CREATE TABLE audit_logs (id CHAR(32), resource_type TEXT, resource_id TEXT, success BOOLEAN)"
                )
            )
            await connection.execute(
                text("INSERT INTO notification_logs VALUES (:id)"),
                [{"id": first.hex}, {"id": second.hex}],
            )
            await connection.execute(
                text("INSERT INTO audit_logs VALUES (:id,:resource,:subject,1)"),
                {
                    "id": uuid4().hex,
                    "resource": technical.RESOURCE,
                    "subject": str(first),
                },
            )
            rows = (
                (
                    await connection.execute(
                        select(NotificationLog.id).where(technical.resolution_exists())
                    )
                )
                .scalars()
                .all()
            )
            assert rows == [first]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_closed_receipt_blocks_dispatch_even_if_a_maintenance_job_requeues_it(
    managed_db,
):
    log = await historical(managed_db)
    result = post(managed_db, log, body(log))
    assert result.status_code == 200
    async with managed_db[1]() as db:
        saved = await db.get(NotificationLog, log.id)
        saved.status = S.PENDIENTE
        saved.next_retry_at = utc_now_naive() - timedelta(seconds=1)
        await db.commit()
    assert await worker(managed_db[1]) == 1
    Service.dispatch_email.assert_not_awaited()
    closed = listing(managed_db, "resolved").json()["items"]
    assert (
        len(closed) == 1
        and closed[0]["resolution"]["audit_id"] == result.json()["audit_id"]
    )

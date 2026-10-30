"""Native PostgreSQL registry transactions and real mounted authorization."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4, UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaError
from sqlalchemy import select, update, text, func

from app.main import app
from app.core.database import get_db
from app.core.exceptions import ValidationError, NotFoundError
from app.core.rate_limiter import RateLimiter
from app.core.security import create_access_token
from app.middleware import rate_limit_middleware
from app.models.audit_log import AuditLog, ActionType
from app.models.integration import (
    Integration,
    IntegrationType,
    IntegrationStatus,
    WebhookEvent,
    WebhookEventType,
)
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.schemas.integration import IntegrationCreate, IntegrationPatch
from app.services.integration_service import (
    IntegrationService,
    bounded_json,
    public_statement,
)
from tests.orm_contract import detailed_mapping_contract
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401

SENTINELS = (
    "fixture-only-credential",
    "fixture-only-config",
    "fixture-only-signing",
    "fixture-only-error",
    "fixture-only-header",
    "fixture-only-response",
)


@pytest.fixture
async def registry(pg_wallets, monkeypatch):
    sessions, _, riders = pg_wallets
    monkeypatch.setattr(rate_limit_middleware, "rate_limiter", RateLimiter())

    # A registry request or diagnostic must not construct a transport at all.
    def forbidden_transport(*args, **kwargs):
        raise AssertionError("Registry attempted external HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", forbidden_transport)
    async with sessions() as db:
        conn = await db.connection()
        await conn.run_sync(Rider.__table__.c.status.type.create, checkfirst=True)
        await db.execute(
            text("ALTER TABLE riders ADD COLUMN status riderstatus DEFAULT 'ACTIVO'")
        )
        for model in (Integration, WebhookEvent, AuditLog):
            await conn.run_sync(model.__table__.create)
        ids = {}
        for name, role in {
            "super": UserRole.SUPERADMIN,
            "manager": UserRole.GERENTE,
            "operator": UserRole.OPERADOR,
            "customer": UserRole.CLIENTE,
            "auditor": UserRole.AUDITOR,
            "inactive": UserRole.SUPERADMIN,
            "roleless": UserRole.SUPERADMIN,
        }.items():
            user = User(
                id=uuid4(),
                email=name + "@registry.test",
                hashed_password="unused",
                first_name=name,
                last_name="Test",
                role=role,
                is_active=name != "inactive",
            )
            db.add(user)
            ids[name] = user.id
        await db.flush()
        await db.execute(
            update(User).where(User.id == ids["roleless"]).values(role=None)
        )
        ids["owner"] = await db.scalar(
            select(Rider.user_id).where(Rider.id == riders[0])
        )
        legacy = Integration(
            id=uuid4(),
            name="Legacy",
            integration_type=IntegrationType.POS,
            status=IntegrationStatus.ACTIVE,
            provider="Example",
            api_url="https://provider.invalid/?private=fixture-only-endpoint",
            credentials=SENTINELS[0],
            config=json.dumps({"private": SENTINELS[1]}),
            webhook_secret=SENTINELS[2],
            last_error_message=SENTINELS[3],
            webhook_url="https://provider.invalid/hooks?private=fixture-only-webhook",
            auth_type="bearer",
            sync_enabled=True,
            sync_next_run=datetime(2026, 10, 31),
            last_sync_at=datetime(2026, 10, 30),
            last_error_at=datetime(2026, 10, 29),
            sync_last_run=datetime(2026, 10, 30),
        )
        db.add(legacy)
        await db.flush()
        ids["integration"] = legacy.id
        db.add(
            WebhookEvent(
                integration_id=legacy.id,
                event_type=WebhookEventType.ORDER_CREATED,
                payload={"private": SENTINELS[1]},
                headers={"Authorization": SENTINELS[4]},
                response_body=SENTINELS[5],
                success=False,
            )
        )
        await db.commit()
    old = app.dependency_overrides.copy()

    async def database():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    try:
        yield client, sessions, ids
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)


def auth(ids, who="super"):
    return {"Authorization": "Bearer " + create_access_token(ids[who])}


def safe(response):
    for value in SENTINELS + ("fixture-only-endpoint", "fixture-only-webhook"):
        assert value not in response.text
    return response.json()


def test_typed_integration_models_preserve_every_sql_contract():
    expected = json.loads(
        (Path(__file__).parent / "fixtures/orm_integration_baseline.json").read_text()
    )
    assert detailed_mapping_contract(tuple(expected)) == expected
    assert (
        len(Integration.__table__.columns) + len(WebhookEvent.__table__.columns) == 37
    )


def test_public_projection_excludes_raw_provider_configuration():
    names = set(public_statement().selected_columns.keys())
    assert not names & {
        "credentials",
        "config",
        "api_url",
        "webhook_url",
        "webhook_secret",
        "auth_type",
        "token_expires_at",
        "last_error_message",
    }
    assert {"has_credentials", "has_endpoint", "has_config"} <= names


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "  ", "integration_type": "POS"},
        {"name": "x\ny", "integration_type": "POS"},
        {"name": "x\x00y", "integration_type": "POS"},
        {"name": "x\u200by", "integration_type": "POS"},
        {"name": "x" * 101, "integration_type": "POS"},
        {"name": "x", "integration_type": "UNKNOWN"},
        {"name": "x", "integration_type": "POS", "sync_frequency_minutes": 0},
        {"name": "x", "integration_type": "POS", "sync_frequency_minutes": 1441},
        {"name": "x", "integration_type": "POS", "sync_frequency_minutes": True},
        {"name": "x", "integration_type": "POS", "provider": "x" * 51},
        {"name": "x", "integration_type": "POS", "status": "ACTIVE"},
        {"name": "x", "integration_type": "POS", "credentials": "must-not-be-accepted"},
    ],
)
def test_create_metadata_rejects_invalid_or_unsafe_inputs(payload):
    with pytest.raises(SchemaError):
        IntegrationCreate.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"name": " "},
        {"sync_frequency_minutes": None},
        {"sync_frequency_minutes": False},
        {"status": "ACTIVE"},
        {"api_url": "https://private.invalid"},
        {"config": {}},
        {"integration_type": "ERP"},
    ],
)
def test_patch_is_nonempty_and_cannot_change_connection_configuration(payload):
    with pytest.raises(SchemaError):
        IntegrationPatch.model_validate(payload)


def test_metadata_trims_labels_and_distinguishes_null_from_omission():
    item = IntegrationCreate(
        name="  Example  ", integration_type=IntegrationType.POS, provider="   "
    )
    assert item.name == "Example" and item.provider is None
    assert IntegrationPatch(provider=None).model_dump(exclude_unset=True) == {
        "provider": None
    }
    assert IntegrationPatch(name=" Other ").model_dump(exclude_unset=True) == {
        "name": "Other"
    }


@pytest.mark.parametrize(
    "value",
    [
        {"x": float("nan")},
        {"x": float("inf")},
        {1: "value"},
        {"x": object()},
        {"x": "é" * 40000},
    ],
)
def test_internal_json_refuses_nonfinite_nonjson_or_oversized_config(value):
    with pytest.raises(ValidationError):
        bounded_json(value)


def test_internal_json_handles_cycles_without_exposing_input():
    value = {}
    value["cycle"] = value
    with pytest.raises(ValidationError) as error:
        bounded_json(value)
    assert "cycle" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,read,write",
    [
        ("super", 200, 201),
        ("manager", 200, 403),
        ("operator", 403, 403),
        ("auditor", 403, 403),
        ("customer", 403, 403),
        ("owner", 403, 403),
        ("inactive", 401, 401),
        ("roleless", 401, 401),
    ],
)
async def test_real_mounted_role_matrix_for_reads_writes_and_aliases(
    registry, who, read, write
):
    client, _, ids = registry
    for path in (
        "/api/v1/integrations",
        "/api/v1/integrations/",
        "/api/v1/integrations/integrations",
    ):
        response = client.get(path, headers=auth(ids, who))
        assert response.status_code == read, response.text
        safe(response)
    for suffix in (str(ids["integration"]), str(ids["integration"]) + "/diagnostics"):
        response = client.get("/api/v1/integrations/" + suffix, headers=auth(ids, who))
        assert response.status_code == read
        safe(response)
    response = client.post(
        "/api/v1/integrations",
        headers=auth(ids, who),
        json={"name": "Created", "integration_type": "ERP"},
    )
    assert response.status_code == write, response.text
    safe(response)
    for method, path, body in (
        ("PATCH", str(ids["integration"]), {"name": "Renamed"}),
        ("POST", str(ids["integration"]) + "/pause", None),
    ):
        response = client.request(
            method, "/api/v1/integrations/" + path, headers=auth(ids, who), json=body
        )
        assert response.status_code == (200 if who == "super" else write), response.text


@pytest.mark.asyncio
async def test_private_reads_are_explicit_metadata_and_do_not_load_orm_secrets(
    registry,
):
    client, sessions, ids = registry
    response = client.get(
        f"/api/v1/integrations/{ids['integration']}", headers=auth(ids, "manager")
    )
    data = safe(response)
    assert response.status_code == 200
    assert data["type"] == data["integration_type"] == "POS"
    assert data["is_active"] is True and data["connection_verified"] is False
    assert all(
        data[key]
        for key in (
            "has_credentials",
            "has_endpoint",
            "has_config",
            "has_webhook",
            "has_signing_secret",
            "has_last_error",
        )
    )
    assert data["last_sync_at"] == "2026-10-30T00:00:00Z"
    assert (
        not {
            "credentials",
            "config",
            "webhook_url",
            "webhook_secret",
            "api_url",
            "last_error_message",
            "headers",
            "payload",
        }
        & data.keys()
    )
    async with sessions() as db:
        await IntegrationService(db).get_summary(ids["integration"])
        assert not any(isinstance(row, Integration) for row in db.identity_map.values())
    response = client.get(
        f"/api/v1/integrations/{ids['integration']}/diagnostics", headers=auth(ids)
    )
    data = safe(response)
    assert (
        data["performed"]
        is data["connection_verified"]
        is data["synchronization_available"]
        is False
    )
    assert data["outcome"] == "not_checked"
    assert data["blocking_reasons"] == [
        "verified_adapter_required",
        "legacy_sync_flag_requires_review",
    ]


@pytest.mark.asyncio
async def test_create_is_inactive_audited_and_cannot_provision_secrets(registry):
    client, sessions, ids = registry
    response = client.post(
        "/api/v1/integrations",
        headers=auth(ids),
        json={
            "name": "  New  ",
            "integration_type": "ERP",
            "provider": " Example ",
            "sync_frequency_minutes": 120,
        },
    )
    assert response.status_code == 201, response.text
    data = safe(response)
    identifier = UUID(data["id"])
    assert (
        data["name"] == "New"
        and data["status"] == "INACTIVE"
        and data["sync_enabled"] is False
    )
    assert data["created_by"] == str(ids["super"])
    assert not data["has_credentials"] and not data["has_config"]
    async with sessions() as db:
        row = await db.get(Integration, identifier)
        audit = await db.scalar(
            select(AuditLog).where(AuditLog.resource_id == str(identifier))
        )
        assert (
            row.credentials is row.config is row.webhook_secret is row.api_url is None
        )
        assert audit.action_type is ActionType.CREATE and audit.user_id == ids["super"]
        assert (
            audit.new_values["status"] == "INACTIVE"
            and audit.new_values["sync_enabled"] is False
        )
    response = client.post(
        "/api/v1/integrations",
        headers=auth(ids),
        json={"name": "Unsafe", "integration_type": "POS", "credentials": SENTINELS[0]},
    )
    assert response.status_code == 422 and SENTINELS[0] not in response.text
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Integration)
                .where(Integration.name == "Unsafe")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_patch_preserves_secrets_history_and_audits_only_metadata(registry):
    client, sessions, ids = registry
    response = client.patch(
        f"/api/v1/integrations/{ids['integration']}",
        headers=auth(ids),
        json={"name": "Renamed", "provider": None},
    )
    assert response.status_code == 200, response.text
    data = safe(response)
    assert data["name"] == "Renamed" and data["provider"] is None
    assert data["status"] == "ACTIVE" and data["sync_enabled"] is True
    async with sessions() as db:
        row = await db.get(Integration, ids["integration"])
        assert (
            row.credentials == SENTINELS[0]
            and row.webhook_secret == SENTINELS[2]
            and row.last_error_message == SENTINELS[3]
        )
        assert json.loads(row.config) == {"private": SENTINELS[1]}
        audit = await db.scalar(select(AuditLog))
        assert audit.old_values == {"name": "Legacy", "provider": "Example"}
        assert audit.new_values == {"name": "Renamed", "provider": None}
        assert not any(s in json.dumps(audit.new_values) for s in SENTINELS)
        assert await db.scalar(select(func.count()).select_from(WebhookEvent)) == 1
    # A no-op replay does not invent another change or rewrite updated_at.
    response = client.patch(
        f"/api/v1/integrations/{ids['integration']}",
        headers=auth(ids),
        json={"name": "Renamed", "provider": None},
    )
    assert response.status_code == 200
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1


@pytest.mark.asyncio
async def test_pause_is_idempotent_preserves_history_and_allows_frequency_edit(
    registry,
):
    client, sessions, ids = registry
    path = f"/api/v1/integrations/{ids['integration']}"
    assert (
        client.patch(
            path, headers=auth(ids), json={"sync_frequency_minutes": 120}
        ).status_code
        == 409
    )
    for _ in range(2):
        response = client.post(path + "/pause", headers=auth(ids))
        assert response.status_code == 200
        data = safe(response)
        assert (
            data["status"] == "INACTIVE"
            and data["sync_enabled"] is False
            and data["sync_next_run"] is None
        )
    async with sessions() as db:
        row = await db.get(Integration, ids["integration"])
        assert row.credentials == SENTINELS[0] and row.last_sync_at == datetime(
            2026, 10, 30
        )
        assert row.last_error_message == SENTINELS[3] and row.sync_last_run == datetime(
            2026, 10, 30
        )
        assert await db.scalar(select(func.count()).select_from(WebhookEvent)) == 1
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
    response = client.patch(
        path, headers=auth(ids), json={"sync_frequency_minutes": 120}
    )
    assert (
        response.status_code == 200 and response.json()["sync_frequency_minutes"] == 120
    )
    assert client.delete(path, headers=auth(ids)).status_code == 405
    assert client.post(path + "/activate", headers=auth(ids)).status_code == 404


@pytest.mark.asyncio
async def test_pagination_filters_and_tie_order_are_stable(registry):
    client, sessions, ids = registry
    async with sessions() as db:
        rows = [
            Integration(
                id=uuid4(),
                name="Same",
                integration_type=IntegrationType.ERP,
                status=IntegrationStatus.INACTIVE,
            )
            for _ in range(3)
        ]
        db.add_all(rows)
        await db.commit()
        expected = sorted(str(row.id) for row in rows)
    query = "/api/v1/integrations?integration_type=ERP&status=INACTIVE&limit=1&skip="
    result = [
        safe(client.get(query + str(n), headers=auth(ids)))[0]["id"] for n in range(3)
    ]
    assert result == expected
    assert safe(client.get(query + "3", headers=auth(ids))) == []
    assert safe(
        client.get("/api/v1/integrations?integration_type=POS", headers=auth(ids))
    )[0]["id"] == str(ids["integration"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "skip=-1",
        "skip=10001",
        "integration_type=bad",
        "status=bad",
    ],
)
async def test_invalid_query_is_rejected(registry, query):
    client, _, ids = registry
    assert (
        client.get("/api/v1/integrations?" + query, headers=auth(ids)).status_code
        == 422
    )


@pytest.mark.asyncio
async def test_uuid_missing_records_anonymous_access_and_no_fake_crud(registry):
    client, _, ids = registry
    assert client.get("/api/v1/integrations").status_code == 401
    assert client.get("/api/v1/integrations/123", headers=auth(ids)).status_code == 422
    for method, suffix, body in (
        ("GET", "", None),
        ("GET", "/diagnostics", None),
        ("POST", "/pause", None),
        ("PATCH", "", {"name": "New"}),
    ):
        assert (
            client.request(
                method,
                f"/api/v1/integrations/{uuid4()}" + suffix,
                headers=auth(ids),
                json=body,
            ).status_code
            == 404
        )


@pytest.mark.asyncio
async def test_live_role_and_token_version_are_authoritative(registry):
    client, sessions, ids = registry
    token = auth(ids)
    async with sessions() as db:
        await db.execute(
            update(User).where(User.id == ids["super"]).values(role=UserRole.GERENTE)
        )
        await db.commit()
    assert client.get("/api/v1/integrations", headers=token).status_code == 200
    assert (
        client.post(
            f"/api/v1/integrations/{ids['integration']}/pause", headers=token
        ).status_code
        == 403
    )
    async with sessions() as db:
        await db.execute(
            update(User).where(User.id == ids["super"]).values(token_version=1)
        )
        await db.commit()
    assert client.get("/api/v1/integrations", headers=token).status_code == 401


@pytest.mark.asyncio
async def test_internal_create_serializes_json_text_and_never_activates(registry):
    _, sessions, _ = registry
    async with sessions() as db:
        service = IntegrationService(db)
        row = await service.create_integration(
            "Unicode",
            IntegrationType.ERP,
            {"label": "á", "nested": {"number": 1, "flag": True}},
        )
        assert isinstance(row.id, UUID) and isinstance(row.config, str)
        assert json.loads(row.config) == {
            "label": "á",
            "nested": {"number": 1, "flag": True},
        }
        assert row.status is IntegrationStatus.INACTIVE and row.sync_enabled is False
        assert row.created_at.tzinfo is None
        assert await service.get_integration(row.id) is row
        with pytest.raises(ValidationError):
            await service.get_integration(1)
        with pytest.raises(ValidationError):
            await service.create_integration(
                "Unsafe", IntegrationType.POS, enabled=True
            )
        with pytest.raises(ValidationError):
            await service.create_integration("Unsafe", IntegrationType.POS, config=[])
        with pytest.raises(ValidationError):
            await service.update_integration_status(row.id, IntegrationStatus.ACTIVE)
        assert (
            await service.update_integration_status(uuid4(), IntegrationStatus.INACTIVE)
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(IntegrationType))
async def test_connection_does_not_fabricate_success_for_any_type(registry, kind):
    _, sessions, ids = registry
    async with sessions() as db:
        await db.execute(
            update(Integration)
            .where(Integration.id == ids["integration"])
            .values(integration_type=kind)
        )
        await db.commit()
        service = IntegrationService(db)
        result = await service.test_connection(ids["integration"])
        assert result == {
            "success": False,
            "error": "verified_adapter_required",
            "message": "No se realizó una prueba externa",
            "performed": False,
            "connection_verified": False,
        }
        assert (await service.test_connection(uuid4()))["error"] == "not_found"


@pytest.mark.asyncio
async def test_legacy_sends_return_rejection_without_transport_or_sensitive_errors(
    registry,
):
    _, sessions, _ = registry
    async with sessions() as db:
        service = IntegrationService(db)
        for result in (
            await service.sync_with_pos({"secret": SENTINELS[0]}),
            await service.sync_with_erp({"secret": SENTINELS[0]}),
        ):
            assert result == {
                "success": False,
                "error": "verified_adapter_required",
                "performed": False,
            }
            assert SENTINELS[0] not in json.dumps(result)
        assert (
            await service.trigger_webhook(
                "ORDER_CREATED", {"secret": SENTINELS[0]}, "http://127.0.0.1/private"
            )
            is False
        )


@pytest.mark.asyncio
async def test_failure_event_is_typed_persisted_and_never_claims_delivery(registry):
    _, sessions, ids = registry
    async with sessions() as db:
        service = IntegrationService(db)
        item = await service.register_webhook_event(
            ids["integration"], "ORDER_CREATED", {"id": "external"}, False, 503
        )
        assert isinstance(item.id, UUID) and item.integration_id == ids["integration"]
        assert (
            item.event_type is WebhookEventType.ORDER_CREATED and item.success is False
        )
        assert item.payload == {"id": "external"} and item.headers is None
        assert item.triggered_at.tzinfo is None and item.next_retry_at is None
        for values in (
            ("ORDER_CREATED", {}, True, 200),
            ("unknown", {}, False, None),
            ("ORDER_CREATED", {}, False, 999),
            ("ORDER_CREATED", {}, False, True),
            ("ORDER_CREATED", {"x": float("nan")}, False, 503),
        ):
            with pytest.raises(ValidationError):
                await service.register_webhook_event(ids["integration"], *values)
        with pytest.raises(NotFoundError):
            await service.register_webhook_event(uuid4(), "ORDER_CREATED", {}, False)
        assert await db.scalar(select(func.count()).select_from(WebhookEvent)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "patch", "pause"])
async def test_audit_failure_rolls_back_registry_mutation(
    registry, monkeypatch, operation
):
    _, sessions, ids = registry
    async with sessions() as db:
        service = IntegrationService(db)

        def fail(*args, **kwargs):
            raise RuntimeError("audit failed")

        monkeypatch.setattr(service, "_audit", fail)
        with pytest.raises(RuntimeError, match="audit failed"):
            if operation == "create":
                await service.create_integration("Rollback", IntegrationType.POS)
            elif operation == "patch":
                await service.patch_metadata(
                    ids["integration"], IntegrationPatch(name="Rollback")
                )
            else:
                await service.pause(ids["integration"])
    async with sessions() as db:
        row = await db.get(Integration, ids["integration"])
        assert (
            row.name == "Legacy"
            and row.status is IntegrationStatus.ACTIVE
            and row.sync_enabled is True
        )
        assert await db.scalar(select(func.count()).select_from(Integration)) == 1
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.asyncio
async def test_competing_pauses_produce_one_audited_change(registry):
    _, sessions, ids = registry

    async def pause():
        async with sessions() as db:
            return await IntegrationService(db).pause(ids["integration"])

    results = await asyncio.gather(pause(), pause())
    assert all(
        row.status is IntegrationStatus.INACTIVE and row.sync_enabled is False
        for row in results
    )
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1


@pytest.mark.asyncio
async def test_concurrent_metadata_patches_do_not_lose_unrelated_fields(registry):
    _, sessions, ids = registry

    async def patch(value):
        async with sessions() as db:
            return await IntegrationService(db).patch_metadata(
                ids["integration"], value
            )

    await asyncio.gather(
        patch(IntegrationPatch(name="Concurrent")),
        patch(IntegrationPatch(provider="Updated")),
    )
    async with sessions() as db:
        row = await db.get(Integration, ids["integration"])
        assert row.name == "Concurrent" and row.provider == "Updated"
        assert row.credentials == SENTINELS[0]
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 2


@pytest.mark.asyncio
async def test_legacy_nulls_and_invalid_counters_remain_unknown(registry):
    client, sessions, ids = registry
    async with sessions() as db:
        await db.execute(
            update(Integration)
            .where(Integration.id == ids["integration"])
            .values(
                status=None,
                sync_enabled=None,
                consecutive_failures=-1,
                sync_frequency_minutes=0,
                last_sync_at=None,
                created_at=None,
                updated_at=None,
            )
        )
        await db.commit()
    data = safe(
        client.get(f"/api/v1/integrations/{ids['integration']}", headers=auth(ids))
    )
    assert (
        data["status"]
        is data["sync_enabled"]
        is data["consecutive_failures"]
        is data["sync_frequency_minutes"]
        is data["last_sync_at"]
        is None
    )
    assert data["is_active"] is False and data["connection_verified"] is False


@pytest.mark.asyncio
async def test_missing_configuration_is_reported_without_external_contact(registry):
    _, sessions, _ = registry
    async with sessions() as db:
        row = await IntegrationService(db).create_integration(
            "New", IntegrationType.MAPS
        )
        diagnostic = await IntegrationService(db).diagnostics(row.id)
        assert diagnostic.blocking_reasons == [
            "verified_adapter_required",
            "registry_inactive",
            "endpoint_not_recorded",
            "credentials_not_recorded",
        ]
        assert await db.scalar(select(func.count()).select_from(WebhookEvent)) == 1

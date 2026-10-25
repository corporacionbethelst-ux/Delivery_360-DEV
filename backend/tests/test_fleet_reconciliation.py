"""HTTP catalog alignment and read-only diagnostics on actual SQLite rows."""

from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, update
from tests.test_fleet_assignment import fleet  # noqa: F401
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.api.v1 import vehicles as api
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.rider import Rider
from app.models.vehicle import Vehicle
from app.models.user import User, UserRole
from app.services.fleet_reconciliation import reconcile_fleet, FleetFindingCode


@pytest.fixture
async def catalog(fleet):
    _, db, ctx, first, second = fleet
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")

    async def database():
        yield db

    async def identity():
        return ctx["current"][0]

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = identity
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, db, ctx, first, second


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url", ["/api/v1/vehicles/available", "/api/v1/vehicles?available_only=true"]
)
@pytest.mark.parametrize(
    "state", ["free", "maintenance", "owned", "referenced", "mismatched"]
)
async def test_catalog_requires_active_vehicle_and_both_links_free(catalog, url, state):
    client, db, ctx, first, _ = catalog
    vehicle_id = first.id
    if state == "maintenance":
        first.status = "MANTENIMIENTO"
    if state in ("owned", "mismatched"):
        first.rider_id = ctx["current"][0].id
    if state in ("referenced", "mismatched"):
        await db.execute(
            update(Rider)
            .where(Rider.id != ctx["rider_id"])
            .values(assigned_vehicle_id=first.id)
        )
    await db.commit()
    response = await client.get(url)
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()}
    assert (str(vehicle_id) in ids) is (state == "free")


async def set_company(db, rider_id, vehicle):
    await db.execute(
        update(Rider)
        .where(Rider.id == rider_id)
        .values(
            vehicle_ownership_type="EMPRESA",
            assigned_vehicle_id=vehicle.id,
            vehicle_type=vehicle.type,
            vehicle_plate=vehicle.plate,
            vehicle_model=vehicle.model,
        )
    )
    vehicle.rider_id = await db.scalar(
        select(Rider.user_id).where(Rider.id == rider_id)
    )
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.GERENTE, UserRole.SUPERADMIN])
async def test_healthy_links_have_no_findings(catalog, role):
    client, db, ctx, first, _ = catalog
    ctx["current"][0].role = role
    await set_company(db, ctx["rider_id"], first)
    response = await client.get("/api/v1/vehicles/reconciliation")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["read_only"] is True
    assert data["snapshot_scope"] == "single_statement_per_page"
    assert data["findings"] == [] and data["page_count"] == 0
    assert data["has_more"] is False and data["next_cursor"] is None
    assert set(data["checks"]) == {code.value for code in FleetFindingCode}
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", list(FleetFindingCode))
async def test_detects_each_supported_historical_anomaly(catalog, code):
    client, db, ctx, first, _ = catalog
    rider_id = ctx["rider_id"]
    await set_company(db, rider_id, first)
    if code == FleetFindingCode.COMPANY_WITHOUT_VEHICLE:
        await db.execute(
            update(Rider).where(Rider.id == rider_id).values(assigned_vehicle_id=None)
        )
    elif code == FleetFindingCode.NONCOMPANY_WITH_VEHICLE:
        await db.execute(
            update(Rider)
            .where(Rider.id == rider_id)
            .values(vehicle_ownership_type="PROPIO")
        )
    elif code == FleetFindingCode.MISSING_VEHICLE:
        await db.execute(
            update(Rider)
            .where(Rider.id == rider_id)
            .values(assigned_vehicle_id=uuid4())
        )
    elif code == FleetFindingCode.OWNER_MISMATCH:
        first.rider_id = None
    elif code == FleetFindingCode.MULTIPLE_RIDERS:
        await db.execute(
            update(Rider)
            .where(Rider.id != rider_id)
            .values(assigned_vehicle_id=first.id)
        )
    elif code == FleetFindingCode.METADATA_MISMATCH:
        await db.execute(
            update(Rider).where(Rider.id == rider_id).values(vehicle_model=None)
        )
    elif code == FleetFindingCode.INACTIVE_VEHICLE:
        first.status = "MANTENIMIENTO"
    elif code == FleetFindingCode.OWNER_WITHOUT_PROFILE:
        user = User(
            email="no-profile@example.test",
            first_name="Test",
            last_name="User",
            role=UserRole.GERENTE,
            hashed_password="unused",
        )
        db.add(user)
        await db.flush()
        first.rider_id = user.id
    elif code == FleetFindingCode.OWNER_PROFILE_MISMATCH:
        await db.execute(
            update(Rider).where(Rider.id == rider_id).values(assigned_vehicle_id=None)
        )
    else:
        await db.execute(
            update(Rider)
            .where(Rider.id == rider_id)
            .values(vehicle_ownership_type=None)
        )
    await db.commit()
    response = await client.get(
        "/api/v1/vehicles/reconciliation", params={"code": code.value}
    )
    assert response.status_code == 200, response.text
    findings = response.json()["findings"]
    assert findings and all(item["code"] == code.value for item in findings)
    assert all(
        set(item) == {"code", "entity_type", "entity_id", "related_id", "description"}
        for item in findings
    )


@pytest.mark.asyncio
async def test_report_runs_one_select_without_mutation_or_autoflush(catalog):
    _, db, ctx, first, _ = catalog
    await set_company(db, ctx["rider_id"], first)
    first.notes = "pending local change must not flush"
    with (
        patch.object(db, "execute", wraps=db.execute) as execute,
        patch.object(db, "commit", wraps=db.commit) as commit,
        patch.object(db, "flush", wraps=db.flush) as flush,
        patch.object(db, "delete", wraps=db.delete) as delete,
    ):
        result = await reconcile_fleet(db)
        assert result.findings == []
        execute.assert_awaited_once()
        sql = str(execute.call_args.args[0]).upper()
        assert "FOR UPDATE" not in sql
        commit.assert_not_awaited()
        flush.assert_not_awaited()
        delete.assert_not_awaited()
    assert first in db.dirty
    await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.OPERADOR, UserRole.REPARTIDOR, UserRole.CLIENTE, UserRole.AUDITOR]
)
async def test_report_rejects_other_roles_before_database(catalog, role):
    client, db, ctx, _, _ = catalog
    ctx["current"][0].role = role
    with patch.object(db, "execute", wraps=db.execute) as query:
        response = await client.get("/api/v1/vehicles/reconciliation")
        assert response.status_code == 403
        query.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 501},
        {"code": "UNKNOWN"},
        {"cursor": "bad"},
        {"cursor": "OWNER_MISMATCH:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:invalid"},
        {"cursor": "x" * 121},
    ],
)
async def test_invalid_query_is_rejected(catalog, params):
    client, db, _, _, _ = catalog
    with patch.object(db, "execute", wraps=db.execute) as query:
        response = await client.get("/api/v1/vehicles/reconciliation", params=params)
        assert response.status_code == 422, response.text
        query.assert_not_awaited()


@pytest.mark.asyncio
async def test_cursor_pages_cover_static_findings_once_without_global_counts(catalog):
    client, db, ctx, first, _ = catalog
    await db.execute(
        update(Rider).values(
            vehicle_ownership_type="EMPRESA", assigned_vehicle_id=first.id
        )
    )
    await db.commit()
    expected = await reconcile_fleet(db, limit=500)
    found, cursor = [], None
    for _ in range(30):
        params = {"limit": 1}
        if cursor:
            params["cursor"] = cursor
        response = await client.get("/api/v1/vehicles/reconciliation", params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert "total_count" not in page
        assert page["page_count"] == len(page["findings"])
        found.extend(page["findings"])
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        assert page["next_cursor"] != cursor
        cursor = page["next_cursor"]
    assert found == [item.model_dump(mode="json") for item in expected.findings]


@pytest.mark.asyncio
async def test_report_requires_authentication():
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/vehicles/reconciliation")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"ownership_type": "EMPRESA"}, {"type": "AUTO"}])
async def test_available_filters_preserve_type_and_exclude_maintenance(catalog, params):
    client, db, _, first, second = catalog
    first.status = "MANTENIMIENTO"
    await db.commit()
    response = await client.get("/api/v1/vehicles/available", params=params)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(second.id)]

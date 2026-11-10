"""Persisted audit filtering and exports agree with each event's displayed result."""

import csv
import io
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.api.v1 import audit
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.audit_log import ActionType, AuditLog
from app.models.user import UserRole
from tests.fleet_audit_fixtures import create_sqlite_audit_table


@pytest.fixture
async def audit_client(db_session):
    await create_sqlite_audit_table(db_session)
    actor = SimpleNamespace(role=UserRole.GERENTE)
    app = FastAPI()
    app.include_router(audit.router, prefix="/api/v1/audit")

    async def database():
        yield db_session

    async def identity():
        return actor

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = identity
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, db_session, actor


async def populate(db):
    expected = {"SUCCESS": set(), "WARNING": set(), "FAILURE": set()}
    for action in (ActionType.LOGIN, ActionType.ACCESS_DENIED):
        for success in (True, False, None):
            for code in (None, 200, 399, 400, 499, 500, 503):
                identity = uuid4()
                row = AuditLog(
                    id=identity,
                    action_type=action,
                    success=success,
                    status_code=code,
                    created_at=datetime.utcnow(),
                )
                db.add(row)
                await db.flush()
                # SQLAlchemy applies a default to explicit None on insert: exercise legacy NULL too.
                if success is None:
                    await db.execute(
                        update(AuditLog)
                        .where(AuditLog.id == identity)
                        .values(success=None)
                    )
                    await db.refresh(row)
                expected[audit._audit_status(row)].add(str(identity))
    await db.commit()
    return expected


@pytest.mark.parametrize("result", ["SUCCESS", "WARNING", "FAILURE"])
async def test_list_and_export_use_disjoint_statuses_matching_serialization(
    audit_client, result
):
    client, db, _ = audit_client
    expected = await populate(db)
    response = await client.get(
        "/api/v1/audit", params={"status": result, "limit": 500}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(expected[result])
    assert {row["id"] for row in body["items"]} == expected[result]
    assert all(row["status"] == result for row in body["items"])
    exported = await client.get("/api/v1/audit/export", params={"status": result})
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert {row["id"] for row in rows} == expected[result]
    assert all(row["status"] == result for row in rows)
    assert sum(len(group) for group in expected.values()) == 42


@pytest.mark.parametrize(
    "text",
    [
        "=SUM(1,1)",
        "+584120000000",
        "-2+3",
        "@SUM(A1)",
        ' \t=HYPERLINK("bad")',
        "\r\n+1",
        "\ufeff=1",
    ],
)
async def test_export_neutralizes_formulas_without_changing_persisted_text(
    audit_client, text
):
    client, db, _ = audit_client
    row = AuditLog(
        id=uuid4(),
        action_type=ActionType.UPDATE,
        success=True,
        user_email=text,
        description=text,
        resource_id=text,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.commit()
    response = await client.get("/api/v1/audit/export")
    assert response.status_code == 200
    exported = list(csv.DictReader(io.StringIO(response.text)))[0]
    assert exported["user_email"] == "'" + text
    assert exported["description"] == "'" + text
    assert exported["resource_id"] == "'" + text
    detail = (await client.get(f"/api/v1/audit/{row.id}")).json()
    assert detail["description"] == text
    assert detail["resource_id"] == text


async def test_csv_roundtrips_unicode_quotes_newlines_and_numeric_codes(audit_client):
    client, db, _ = audit_client
    value = 'José, "revisión"\nsegunda línea'
    row = AuditLog(
        id=uuid4(),
        action_type=ActionType.UPDATE,
        description=value,
        status_code=200,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.commit()
    response = await client.get("/api/v1/audit/export")
    exported = list(csv.DictReader(io.StringIO(response.text)))[0]
    assert exported["description"] == value
    assert exported["status_code"] == "200"
    assert "text/csv" in response.headers["content-type"]


@pytest.mark.parametrize(
    "role", [UserRole.OPERADOR, UserRole.REPARTIDOR, UserRole.CLIENTE, UserRole.AUDITOR]
)
@pytest.mark.parametrize(
    "path", ["", "/summary", "/export", "/00000000-0000-0000-0000-000000000083"]
)
async def test_all_administrative_audit_reads_keep_the_existing_role_boundary(
    audit_client, role, path
):
    client, _, actor = audit_client
    actor.role = role
    assert (await client.get("/api/v1/audit" + path)).status_code == 403


@pytest.mark.parametrize("role", [UserRole.GERENTE, UserRole.SUPERADMIN])
async def test_authorized_empty_page_summary_and_header_only_export(audit_client, role):
    client, _, actor = audit_client
    actor.role = role
    page = (await client.get("/api/v1/audit")).json()
    assert page == {"items": [], "total": 0, "limit": 50, "offset": 0}
    summary = (await client.get("/api/v1/audit/summary?days=7")).json()
    assert summary["total"] == 0 and summary["by_success"] == {}
    exported = await client.get("/api/v1/audit/export")
    assert len(exported.text.splitlines()) == 1

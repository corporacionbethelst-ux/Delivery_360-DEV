"""Read-only historical scenarios with explicit bounds, snapshots and rounding."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.api.v1 import settings
from app.models.audit_log import AuditLog
from app.models.platform_setting import PlatformSetting
from app.models.user import UserRole
from app.services.bonus_simulation import historical_bonus_scenario
from tests.test_platform_settings_contract import (
    settings_client,
    read,
    match,
)  # noqa: F401

NOW = datetime(2026, 11, 13, 2, 0, 0)


@pytest.fixture
async def bonus_client(settings_client, monkeypatch):
    client, db, actor = settings_client
    monkeypatch.setattr(settings, "utc_now_naive", lambda: NOW)
    await db.execute(
        text(
            "CREATE TABLE deliveries (id TEXT PRIMARY KEY, status TEXT, completed_at DATETIME, bonus_snapshot_date DATETIME, locked_bonus_amount NUMERIC(10,2), locked_bonus_type TEXT)"
        )
    )
    initial = await read(client)
    configured = await client.patch(
        "/api/v1/settings", json={"rider_delivery_bonus": 10}, headers=match(initial)
    )
    assert configured.status_code == 200
    yield client, db, actor, configured.json()


async def add(db, amount="1.00", status="COMPLETADA", bonus_type="SUCCESS", at=None):
    await db.execute(
        text(
            "INSERT INTO deliveries (id, status, completed_at, locked_bonus_amount, locked_bonus_type) VALUES (:id,:status,:at,:amount,:type)"
        ),
        {
            "id": str(uuid4()),
            "status": status,
            "at": (at or NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "amount": amount,
            "type": bonus_type,
        },
    )
    await db.commit()


def request(snapshot, proposed=0, days=7):
    return {
        "new_base_bonus": proposed,
        "days_projection": days,
        "expected_settings_revision": snapshot["revision"],
    }


async def test_reducing_bonus_cannot_create_negative_cost_or_change_snapshots(
    bonus_client,
):
    client, db, _, saved = bonus_client
    for _ in range(3):
        await add(db)
    await add(db, "2.00", "FALLIDA", "FAILED_ATTEMPT")
    before = list(
        (await db.execute(text("SELECT * FROM deliveries ORDER BY id"))).all()
    )
    response = await client.post("/api/v1/settings/simulate-bonus", json=request(saved))
    assert response.status_code == 200
    row = response.json()
    assert row["historical_cost"] == 5
    assert row["scenario_cost"] == 2  # Old delta formula produced 5 - 10 * 3 = -25.
    assert row["difference"] == -3
    assert row["percentage_change"] == -60
    assert row["completed_deliveries"] == 3 and row["failed_bonus_deliveries"] == 1
    assert row["recorded_completed_bonus"] == 3 and row["recorded_failed_bonus"] == 2
    assert row["current_monthly_cost"] == row["historical_cost"]
    assert row["projected_monthly_cost"] == row["scenario_cost"]
    assert row["currency"] is None
    assert row["comparison_basis"] == "flat_bonus_same_deliveries"
    assert (
        list((await db.execute(text("SELECT * FROM deliveries ORDER BY id"))).all())
        == before
    )
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
    assert await read(client) == saved


async def test_window_is_start_inclusive_end_exclusive_and_excludes_future(
    bonus_client,
):
    client, db, _, saved = bonus_client
    await add(db, "1", at=NOW - timedelta(days=7))
    await add(db, "100", at=NOW - timedelta(days=7, microseconds=1))
    await add(db, "100", at=NOW)
    await add(db, "100", at=NOW + timedelta(hours=1))
    response = await client.post(
        "/api/v1/settings/simulate-bonus", json=request(saved, 2)
    )
    row = response.json()
    assert response.status_code == 200
    assert row["completed_deliveries"] == 1
    assert row["historical_cost"] == 1 and row["scenario_cost"] == 2
    assert row["period_start"] == "2026-11-06T02:00:00Z"
    assert row["period_end"] == "2026-11-13T02:00:00Z"


@pytest.mark.parametrize(
    "proposal,applied,total", [(2.675, 2.68, 8.04), (0.005, 0.01, 0.03), (0, 0, 0)]
)
async def test_decimal_half_up_is_applied_per_delivery(
    bonus_client, proposal, applied, total
):
    client, db, _, saved = bonus_client
    for _ in range(3):
        await add(db, "0.00")
    row = (
        await client.post(
            "/api/v1/settings/simulate-bonus", json=request(saved, proposal)
        )
    ).json()
    assert row["proposed_base_bonus"] == proposal
    assert row["applied_bonus"] == applied and row["scenario_cost"] == total
    assert row["percentage_change"] is None and row["percentage_increase"] == 0


async def test_empty_period_is_an_explicit_empty_sample(bonus_client):
    client, _, _, saved = bonus_client
    row = (
        await client.post("/api/v1/settings/simulate-bonus", json=request(saved, 2))
    ).json()
    assert row["completed_deliveries"] == row["failed_bonus_deliveries"] == 0
    assert row["historical_cost"] == row["scenario_cost"] == row["difference"] == 0
    assert row["percentage_change"] is None


async def test_failed_non_bonus_and_nonterminal_rows_do_not_enter_the_sample(
    bonus_client,
):
    client, db, _, saved = bonus_client
    await add(db, None, "FALLIDA", None)
    await add(db, "99", "PENDIENTE", "SUCCESS")
    await add(db, "99", "CANCELADA", "SUCCESS")
    row = (
        await client.post("/api/v1/settings/simulate-bonus", json=request(saved, 2))
    ).json()
    assert row["completed_deliveries"] == row["failed_bonus_deliveries"] == 0
    assert row["historical_cost"] == 0


@pytest.mark.parametrize(
    "status,bonus_type,amount",
    [
        ("COMPLETADA", None, "1"),
        ("COMPLETADA", "FAILED_ATTEMPT", "1"),
        ("COMPLETADA", "SUCCESS", None),
        ("COMPLETADA", "SUCCESS", "-1"),
        ("FALLIDA", "SUCCESS", "1"),
        ("FALLIDA", "FAILED_ATTEMPT", None),
        ("FALLIDA", "FAILED_ATTEMPT", "-1"),
    ],
)
async def test_incomplete_or_inconsistent_snapshot_stops_instead_of_inventing_zero(
    bonus_client, status, bonus_type, amount
):
    client, db, _, saved = bonus_client
    await add(db, amount, status, bonus_type)
    response = await client.post(
        "/api/v1/settings/simulate-bonus", json=request(saved, 2)
    )
    assert response.status_code == 409
    assert "histórico" in response.json()["detail"]


async def test_revision_change_between_preflight_and_calculation_is_rejected(
    bonus_client,
):
    client, db, _, saved = bonus_client
    response = await client.patch(
        "/api/v1/settings", json={"rider_delivery_bonus": 11}, headers=match(saved)
    )
    assert response.status_code == 200
    stale = await client.post("/api/v1/settings/simulate-bonus", json=request(saved, 2))
    assert stale.status_code == 412
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 2


async def test_unconfigured_simulation_does_not_initialize_settings(settings_client):
    client, db, _ = settings_client
    response = await client.post(
        "/api/v1/settings/simulate-bonus", json={"new_base_bonus": 2}
    )
    assert response.status_code == 409
    assert await db.scalar(select(func.count()).select_from(PlatformSetting)) == 0
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize("role", [UserRole.SUPERADMIN, UserRole.GERENTE])
async def test_allowed_roles_can_simulate_without_writing(bonus_client, role):
    client, _, actor, saved = bonus_client
    actor.role = role
    assert (
        await client.post("/api/v1/settings/simulate-bonus", json=request(saved, 2))
    ).status_code == 200


@pytest.mark.parametrize(
    "role", [UserRole.OPERADOR, UserRole.REPARTIDOR, UserRole.AUDITOR]
)
async def test_other_roles_cannot_query_bonus_history(bonus_client, role):
    client, _, actor, saved = bonus_client
    actor.role = role
    assert (
        await client.post("/api/v1/settings/simulate-bonus", json=request(saved, 2))
    ).status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"days_projection": True},
        {"days_projection": 1.5},
        {"days_projection": "7"},
        {"days_projection": 0},
        {"days_projection": 91},
        {"new_base_bonus": -1},
        {"new_base_bonus": 100000000},
        {"expected_settings_revision": "*"},
        {"unexpected": True},
    ],
)
async def test_invalid_requests_fail_before_calculation(bonus_client, changes):
    client, _, _, saved = bonus_client
    response = await client.post(
        "/api/v1/settings/simulate-bonus", json={**request(saved, 2), **changes}
    )
    assert response.status_code == 422


async def test_legacy_request_without_revision_retains_wire_fields_and_defaults(
    bonus_client,
):
    client, db, _, _ = bonus_client
    await add(db, "12.50")
    row = (await client.post("/api/v1/settings/simulate-bonus", json={})).json()
    assert row["history_days"] == 30 and row["proposed_base_bonus"] == 10
    assert row["current_monthly_cost"] == 12.5 and row["projected_monthly_cost"] == 10


async def test_failure_uses_frozen_bonus_date_and_reports_undated_global_records(
    bonus_client,
):
    client, db, _, saved = bonus_client
    await db.execute(
        text(
            "INSERT INTO deliveries VALUES (:id,'FALLIDA',NULL,:snapshot,2,'FAILED_ATTEMPT')"
        ),
        {
            "id": str(uuid4()),
            "snapshot": (NOW - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
        },
    )
    await db.execute(
        text("INSERT INTO deliveries VALUES (:id,'COMPLETADA',NULL,NULL,1,'SUCCESS')"),
        {"id": str(uuid4())},
    )
    await db.commit()
    row = (
        await client.post("/api/v1/settings/simulate-bonus", json=request(saved, 0))
    ).json()
    assert row["failed_bonus_deliveries"] == 1
    assert row["historical_cost"] == row["scenario_cost"] == 2
    assert row["completed_deliveries"] == 0
    assert row["undated_bonus_deliveries"] == 1


@pytest.mark.parametrize("value", [None, True, "NaN", -1, "bad", 100000000])
async def test_invalid_saved_baseline_is_never_replaced_with_zero(bonus_client, value):
    client, db, _, _ = bonus_client
    row = await db.get(PlatformSetting, "rider_delivery_bonus")
    row.value = value
    await db.commit()
    response = await client.post(
        "/api/v1/settings/simulate-bonus",
        json={"new_base_bonus": 2, "days_projection": 7},
    )
    assert response.status_code == 409


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e309"])
async def test_non_finite_proposal_is_rejected_as_validation_error(
    bonus_client, number
):
    client, _, _, _ = bonus_client
    response = await client.post(
        "/api/v1/settings/simulate-bonus",
        content='{"new_base_bonus":' + number + "}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422

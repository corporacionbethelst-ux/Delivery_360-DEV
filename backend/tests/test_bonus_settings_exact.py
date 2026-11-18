"""Exact settings inputs, raw JSON precision, shared revisions and atomic audit."""

from decimal import Decimal
import pytest
from sqlalchemy import select, text, func
from app.models.audit_log import AuditLog
from app.models.platform_setting import PlatformSetting
from app.models.user import UserRole
from tests.test_platform_settings_contract import settings_client, match  # noqa: F401

PATH = "/api/v1/settings/exact/v2"


async def read(client):
    response = await client.get(PATH)
    assert response.status_code == 200, response.text
    return response.json()


async def test_exact_update_preserves_decimal_text_and_legacy_read(settings_client):
    client, db, _ = settings_client
    initial = await read(client)
    patch = {
        "rider_delivery_bonus": "99999999.99",
        "rider_failed_attempt_bonus": "0.10",
        "delivery_fee_base": "0.00",
        "commission_percentage": "12.123456789012345678",
    }
    response = await client.patch(PATH, json=patch, headers=match(initial))
    assert response.status_code == 200, response.text
    updated = response.json()
    assert all(updated[k] == v for k, v in patch.items())
    assert (
        updated["version"] == 2
        and updated["currency"] == "USD"
        and updated["field_issues"] == []
    )
    assert updated == await read(client)
    old = (await client.get("/api/v1/settings")).json()
    assert (
        old["revision"] == updated["legacy_revision"]
        and old["rider_failed_attempt_bonus"] == 0.1
        and "version" not in old
    )
    assert (
        await db.scalar(
            select(PlatformSetting.value).where(
                PlatformSetting.key == "rider_failed_attempt_bonus"
            )
        )
        == "0.10"
    )
    audit = (await db.scalars(select(AuditLog))).one()
    assert audit.old_values["values"] == {k: None for k in patch}
    assert audit.old_values["stored_json"] == {k: "null" for k in patch}
    assert audit.new_values["values"] == patch
    replay = await client.patch(PATH, json=patch, headers=match(initial))
    assert replay.status_code == 412
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1


@pytest.mark.parametrize(
    "bad",
    [
        0,
        0.1,
        True,
        False,
        None,
        "",
        "NaN",
        "Infinity",
        "1e2",
        "-0.01",
        "1.001",
        "100000000.00",
        " 2.00",
        "00.10",
        "1,20",
    ],
)
async def test_money_input_never_passes_through_a_number_or_rounding(
    settings_client, bad
):
    client, db, _ = settings_client
    initial = await read(client)
    r = await client.patch(
        PATH, json={"rider_delivery_bonus": bad}, headers=match(initial)
    )
    assert r.status_code == 422, r.text
    assert await read(client) == initial
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize(
    "raw",
    [
        '"2.50001"',
        "true",
        '"NaN"',
        '"-1"',
        '{"value":2}',
        "100000000",
    ],
)
async def test_invalid_stored_precision_stays_reviewable_without_float_recovery(
    settings_client, raw
):
    client, db, _ = settings_client
    await read(client)
    await db.execute(
        text(
            "UPDATE platform_settings SET value=:raw WHERE key='rider_delivery_bonus'"
        ),
        {"raw": raw},
    )
    await db.commit()
    r = await read(client)
    assert r["rider_delivery_bonus"] is None
    assert r["field_issues"] == [
        {"field": "rider_delivery_bonus", "reason": "PARAMETRO_NO_VALIDO"}
    ]
    assert (
        await db.scalar(
            text(
                "SELECT CAST(value AS TEXT) FROM platform_settings WHERE key='rider_delivery_bonus'"
            )
        )
    ) == raw
    repaired = await client.patch(
        PATH, json={"rider_delivery_bonus": "0.10"}, headers=match(r)
    )
    assert (
        repaired.status_code == 200
        and repaired.json()["rider_delivery_bonus"] == "0.10"
        and repaired.json()["field_issues"] == []
    )
    audit = (await db.scalars(select(AuditLog))).one()
    assert audit.old_values["stored_json"]["rider_delivery_bonus"] == raw


async def test_legacy_numeric_update_invalidates_exact_revision_without_losing_other_values(
    settings_client,
):
    client, db, _ = settings_client
    initial = await read(client)
    old = await client.patch(
        "/api/v1/settings",
        json={"rider_delivery_bonus": 2.50001},
        headers=match({"revision": initial["legacy_revision"]}),
    )
    assert old.status_code == 200
    stale = await client.patch(
        PATH, json={"delivery_fee_base": "4.00"}, headers=match(initial)
    )
    assert stale.status_code == 412
    fresh = await read(client)
    assert fresh["rider_delivery_bonus"] is None and fresh["field_issues"]
    update = await client.patch(
        PATH, json={"delivery_fee_base": "4.00"}, headers=match(fresh)
    )
    assert update.status_code == 200
    assert (
        await db.scalar(
            select(PlatformSetting.value).where(
                PlatformSetting.key == "rider_delivery_bonus"
            )
        )
        == 2.50001
    )


async def test_audit_failure_rolls_back_exact_string_and_revision(
    settings_client, monkeypatch
):
    client, db, _ = settings_client
    initial = await read(client)

    async def broken(*args, **kwargs):
        raise RuntimeError("synthetic audit flush failure")

    monkeypatch.setattr(db, "flush", broken)
    with pytest.raises(RuntimeError, match="synthetic audit"):
        await client.patch(
            PATH, json={"delivery_fee_base": "0.10"}, headers=match(initial)
        )
    monkeypatch.undo()
    assert await read(client) == initial
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize(
    "role",
    [
        UserRole.GERENTE,
        UserRole.OPERADOR,
        UserRole.REPARTIDOR,
        UserRole.AUDITOR,
        UserRole.CLIENTE,
    ],
)
async def test_only_superadmin_updates_and_only_manager_reads(settings_client, role):
    client, db, actor = settings_client
    initial = await read(client)
    actor.role = role
    assert (await client.get(PATH)).status_code == (
        200 if role == UserRole.GERENTE else 403
    )
    assert (
        await client.patch(
            PATH, json={"delivery_fee_base": "1.00"}, headers=match(initial)
        )
    ).status_code == 403
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


async def test_missing_revision_and_unsupported_filters_do_not_mutate(settings_client):
    client, db, _ = settings_client
    assert (
        await client.patch(PATH, json={"delivery_fee_base": "0.00"})
    ).status_code == 428
    assert await db.scalar(select(func.count()).select_from(PlatformSetting)) == 0
    assert (await client.get(PATH + "?currency=VES")).status_code == 422


async def test_retired_backfill_has_no_database_import_or_write(monkeypatch):
    from app.scripts.migrate_historical_snapshots import migrate_historical_snapshots

    with pytest.raises(RuntimeError, match="Operación retirada"):
        await migrate_historical_snapshots()

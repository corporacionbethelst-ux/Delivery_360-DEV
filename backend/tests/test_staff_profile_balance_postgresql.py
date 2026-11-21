"""Staff and owner share the real canonical ledger and reservation calculation."""

from uuid import uuid4
from decimal import Decimal
from concurrent.futures import Future
import asyncio
import threading
import pytest
from sqlalchemy import select, text, event
from app.models.rider import Rider
from app.models.payout import Payout, PayoutStatus
from tests.test_assignment_concurrency_postgresql import wait_for_blocker
from tests.test_rider_earnings_exact_postgresql import (
    entry,
    withdrawal,
    get,
    reports_db,
    quote_db,
    currency_db,
)  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["GERENTE", "SUPERADMIN"])
async def test_staff_matches_owner_exact_money_and_keeps_identities_separate(
    reports_db, role
):
    f = reports_db
    await entry(f, "0.31", after="0.31")
    await withdrawal(f, "0.10")
    target = f[2]["rider"]
    staff = get(f, f"/payouts/riders/{target}/balance/exact", role=role)
    owner = get(f, "/payouts/balance/exact")
    assert staff["scope"] == "staff_canonical_usd_balance"
    assert staff["actor"] == {"user_id": str(f[2][role]), "role": role}
    assert staff["user_id"] == owner["user_id"] == str(f[2]["REPARTIDOR"])
    assert staff["rider_id"] == str(target)
    for key in (
        "ledger_balance",
        "reserved",
        "available",
        "pending",
        "processed",
        "total_earned",
    ):
        assert staff[key] == owner[key] and isinstance(staff[key], str)
    assert staff["ledger_balance"] == "0.31"
    assert staff["reserved"] == "0.10" and staff["available"] == "0.21"
    assert staff["bank_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["OPERADOR", "AUDITOR", "CLIENTE", "REPARTIDOR"])
async def test_other_roles_cannot_query_a_profile_balance(reports_db, role):
    f = reports_db
    get(f, f"/payouts/riders/{f[2]['rider']}/balance/exact", role=role, status=403)


@pytest.mark.asyncio
async def test_staff_no_evidence_zero_is_distinct_from_missing_rider(reports_db):
    f = reports_db
    result = get(f, f"/payouts/riders/{f[2]['rider']}/balance/exact", role="GERENTE")
    assert result["available"] == "0.00" and result["ledger_integrity"] == "no_evidence"
    for target in (uuid4(), f[2]["REPARTIDOR"]):
        get(f, f"/payouts/riders/{target}/balance/exact", role="GERENTE", status=404)


@pytest.mark.asyncio
async def test_staff_cannot_publish_corrupt_chain_or_select_another_scope(reports_db):
    f = reports_db
    path = f"/payouts/riders/{f[2]['rider']}/balance/exact"
    get(f, path, role="GERENTE", params={"user_id": str(f[2]["OTHER"])}, status=422)
    await entry(f, "0.31", after="0.32")
    get(f, path, role="GERENTE", status=409)


@pytest.mark.asyncio
async def test_staff_waits_for_canonical_writer_and_reads_committed_reservations(
    reports_db,
):
    f = reports_db
    await entry(f, "0.31", after="0.31")
    await withdrawal(f, "0.10")
    waiting = Future()
    main_thread = threading.get_ident()

    def observe(conn, cursor, statement, params, ctx, many):
        if (
            threading.get_ident() != main_thread
            and "FOR UPDATE" in statement
            and "FROM riders" in statement
            and not waiting.done()
        ):
            waiting.set_result(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )

    event.listen(f[3].sync_engine, "before_cursor_execute", observe)
    try:
        async with asyncio.timeout(20):
            async with f[1]() as writer:
                pid = await writer.scalar(text("SELECT pg_backend_pid()"))
                await writer.execute(
                    select(Rider.id).where(Rider.id == f[2]["rider"]).with_for_update()
                )
                pending = asyncio.create_task(
                    asyncio.to_thread(
                        get,
                        f,
                        f"/payouts/riders/{f[2]['rider']}/balance/exact",
                        "GERENTE",
                    )
                )
                try:
                    waiter = await asyncio.wait_for(asyncio.wrap_future(waiting), 5)
                    await wait_for_blocker(f[1], waiter, pid)
                    writer.add(
                        Payout(
                            rider_id=f[2]["rider"],
                            amount=Decimal("0.10"),
                            currency_code="USD",
                            status=PayoutStatus.PENDIENTE,
                        )
                    )
                    await writer.commit()
                finally:
                    await writer.rollback()
                result = await pending
                assert result["reserved"] == "0.20" and result["available"] == "0.11"
    finally:
        event.remove(f[3].sync_engine, "before_cursor_execute", observe)

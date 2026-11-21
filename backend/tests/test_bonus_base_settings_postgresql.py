"""Original JSON precision and real settings/terminal transaction coordination."""

import asyncio
import threading
from concurrent.futures import Future
from decimal import Decimal
import pytest
from sqlalchemy import text, select, event
from app.models.financial import Financial
from app.models.platform_setting import PlatformSetting
from app.models.rider import Rider, RiderTier
from app.services.bonus_base_settings import load_bonus_bases
from tests.test_zone_bonus_factors_postgresql import (
    factor_db,
    bonus_db,
    payment_db,
    put,
    report,
)  # noqa:F401
from tests.test_delivery_financial_postgresql import request, OPERATIONS
from tests.test_assignment_concurrency_postgresql import wait_for_blocker


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0.0049999999999999999999", "0.00"),
        ("100.004999999999999999", "100.00"),
    ],
)
async def test_all_closures_round_original_json_number_once(
    factor_db, operation, raw, expected
):
    f = factor_db
    put(f, "1")
    async with f[1]() as db:
        rider = await db.get(Rider, f[2]["rider"])
        rider.tier = RiderTier.BRONCE
        await db.execute(
            text(
                "UPDATE platform_settings SET value=CAST(:raw AS json) WHERE key IN ('rider_delivery_bonus','rider_failed_attempt_bonus')"
            ),
            {"raw": raw},
        )
        await db.commit()
        old = (
            await db.execute(
                text(
                    "SELECT id,to_jsonb(d) FROM deliveries d WHERE id<>:id ORDER BY id"
                ),
                {"id": f[2]["delivery"]},
            )
        ).all()
        settings = (
            await db.execute(
                text("SELECT key,value::text FROM platform_settings ORDER BY key")
            )
        ).all()
    response = request(f[0], f[2], operation)
    assert response.status_code == 200, response.text
    assert report(f)["amount"] == expected
    async with f[1]() as db:
        rows = (
            await db.scalars(
                select(Financial).where(Financial.reference_id == str(f[2]["order"]))
            )
        ).all()
        assert len(rows) == (0 if expected == "0.00" else 1)
        if rows:
            assert (
                rows[0].amount == Decimal(expected) and rows[0].currency_code == "USD"
            )
        assert (
            await db.execute(
                text("SELECT key,value::text FROM platform_settings ORDER BY key")
            )
        ).all() == settings
        assert (
            await db.execute(
                text(
                    "SELECT id,to_jsonb(d) FROM deliveries d WHERE id<>:id ORDER BY id"
                ),
                {"id": f[2]["delivery"]},
            )
        ).all() == old


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_terminal_waits_for_committed_base_setting(factor_db, operation):
    f = factor_db
    put(f, "1")
    engine = f[1].kw["bind"]
    waiting = Future()
    main = threading.get_ident()
    key = (
        "rider_failed_attempt_bonus"
        if "failure" in operation
        else "rider_delivery_bonus"
    )

    def observe(conn, cursor, statement, params, ctx, many):
        if (
            threading.get_ident() != main
            and "FROM platform_settings" in statement
            and "FOR SHARE" in statement
            and not waiting.done()
        ):
            waiting.set_result(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )

    event.listen(engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with asyncio.timeout(25):
            async with f[1]() as writer:
                pid = await writer.scalar(text("SELECT pg_backend_pid()"))
                setting = await writer.scalar(
                    select(PlatformSetting)
                    .where(PlatformSetting.key == key)
                    .with_for_update()
                )
                setting.value = "3.00"
                await writer.flush()
                pending = asyncio.create_task(
                    asyncio.to_thread(request, f[0], f[2], operation)
                )
                try:
                    waiter = await asyncio.wait_for(asyncio.wrap_future(waiting), 5)
                    await wait_for_blocker(f[1], waiter, pid)
                    await writer.commit()
                finally:
                    await writer.rollback()
                response = await pending
                assert response.status_code == 200, response.text
                assert report(f)["amount"] == "3.45"
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", observe)


@pytest.mark.asyncio
async def test_shared_reader_blocks_writer_until_rollback_and_bypasses_orm_cache(
    factor_db,
):
    f = factor_db
    key = "rider_delivery_bonus"
    waiting = Future()
    engine = f[1].kw["bind"]
    main = threading.get_ident()

    def observe(conn, cursor, statement, params, ctx, many):
        if (
            threading.get_ident() != main
            and "FROM platform_settings" in statement
            and "FOR UPDATE" in statement
            and not waiting.done()
        ):
            waiting.set_result(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )

    async def write():
        async with f[1]() as db:
            item = await db.scalar(
                select(PlatformSetting)
                .where(PlatformSetting.key == key)
                .with_for_update()
            )
            item.value = "4.00"
            await db.commit()

    event.listen(engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with asyncio.timeout(25):
            async with f[1]() as reader:
                cached = await reader.scalar(
                    select(PlatformSetting).where(PlatformSetting.key == key)
                )
                async with f[1]() as writer:
                    await writer.execute(
                        text(
                            "UPDATE platform_settings SET value=CAST(:v AS json) WHERE key=:k"
                        ),
                        {"v": "0.0049999999999999999999", "k": key},
                    )
                    await writer.commit()
                pid = await reader.scalar(text("SELECT pg_backend_pid()"))
                assert (await load_bonus_bases(reader, [key]))[key] == Decimal(
                    "0.0049999999999999999999"
                )
                assert cached.value == "2.50"
                pending = asyncio.create_task(
                    asyncio.to_thread(lambda: asyncio.run(write()))
                )
                try:
                    waiter = await asyncio.wait_for(asyncio.wrap_future(waiting), 5)
                    await wait_for_blocker(f[1], waiter, pid)
                finally:
                    await reader.rollback()
                await pending
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", observe)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("missing", [True, False])
async def test_missing_and_json_null_keep_each_closures_fallback(
    factor_db, operation, missing
):
    f = factor_db
    put(f, "1")
    async with f[1]() as db:
        if missing:
            await db.execute(
                text(
                    "DELETE FROM platform_settings WHERE key IN ('rider_delivery_bonus','rider_failed_attempt_bonus')"
                )
            )
        else:
            await db.execute(
                text(
                    "UPDATE platform_settings SET value='null'::json WHERE key IN ('rider_delivery_bonus','rider_failed_attempt_bonus')"
                )
            )
        await db.commit()
    r = request(f[0], f[2], operation)
    assert r.status_code == 200, r.text
    value = report(f)
    assert value["amount"] == ("2.88" if operation == "order" else "0.00")
    async with f[1]() as db:
        from app.models.delivery import Delivery

        row = await db.get(Delivery, f[2]["delivery"])
        assert row.bonus_config_warning_snapshot

"""Real PostgreSQL aggregates and mounted authenticated HTTP contracts."""

import importlib
from datetime import datetime, timedelta, timezone, time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, select, update, func

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limiter import RateLimiter
from app.core.reporting_period import calendar_window, explicit_window, aware_utc
from app.core.security import create_access_token
from app.main import app
from app.middleware import rate_limit_middleware
from app.models.delivery import Delivery, DeliveryStatus
from app.models.notification import Alert
from app.models.order import Order, OrderStatus
from app.models.productivity import ProductivityMetrics
from app.models.rider import Rider, RiderStatus
from app.models.shift import Shift, ShiftStatus
from app.models.user import User, UserRole
from app.services.dashboard_service import DashboardService
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
CLOCK = NOW.replace(tzinfo=None)


@pytest.fixture
async def dashboard_db(pg_wallets, monkeypatch):
    sessions, _, riders = pg_wallets
    monkeypatch.setattr(settings, "CELERY_TIMEZONE", "UTC")
    service = importlib.import_module("app.services.dashboard_service")
    productivity = importlib.import_module("app.api.v1.productivity")
    frozen = lambda days=7, now=None: calendar_window(days, now or NOW)
    monkeypatch.setattr(service, "calendar_window", frozen)
    monkeypatch.setattr(productivity, "calendar_window", frozen)
    monkeypatch.setattr(rate_limit_middleware, "rate_limiter", RateLimiter())
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(Rider.__table__.c.status.type.create, checkfirst=True)
        await db.execute(
            text(
                "ALTER TABLE riders ADD COLUMN status riderstatus DEFAULT 'ACTIVO', ADD COLUMN is_online BOOLEAN DEFAULT FALSE, ADD COLUMN last_lat FLOAT, ADD COLUMN last_lng FLOAT, ADD COLUMN last_location_at TIMESTAMP, ADD COLUMN updated_at TIMESTAMP"
            )
        )
        for model in (Order, Delivery, Shift, Alert, ProductivityMetrics):
            await connection.run_sync(model.__table__.create)
        ids = {"rider": riders[0], "other_rider": riders[1]}
        for name, role in {
            "manager": UserRole.GERENTE,
            "super": UserRole.SUPERADMIN,
            "operator": UserRole.OPERADOR,
            "auditor": UserRole.AUDITOR,
            "customer": UserRole.CLIENTE,
            "roleless": UserRole.OPERADOR,
            "inactive": UserRole.GERENTE,
        }.items():
            user = User(
                id=uuid4(),
                email=name + "@dashboard.test",
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
        for name, rid in (("owner", riders[0]), ("rival", riders[1])):
            ids[name] = await db.scalar(select(Rider.user_id).where(Rider.id == rid))
        await db.commit()
    previous = app.dependency_overrides.copy()

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
        app.dependency_overrides.update(previous)


def headers(ids, who="manager"):
    return {"Authorization": "Bearer " + create_access_token(ids[who])}


def order(**values):
    return Order(
        id=uuid4(),
        customer_name="Test",
        customer_phone="123",
        pickup_address="Origin",
        delivery_address="Destination",
        **{"created_at": CLOCK - timedelta(hours=1), **values},
    )


async def delivery(
    db,
    rider,
    *,
    completed=None,
    started=None,
    sla=None,
    status=DeliveryStatus.COMPLETADA,
    created=None,
):
    parent = order(created_at=created or CLOCK - timedelta(hours=1))
    db.add(parent)
    await db.flush()
    row = Delivery(
        order_id=parent.id,
        rider_id=rider,
        status=status,
        completed_at=completed,
        started_at=started,
        sla_compliant=sla,
    )
    db.add(row)
    return row


@pytest.mark.parametrize("days", [0, -1, 32, True, 1.5, "7"])
def test_calendar_refuses_unbounded_or_non_integer_periods(days):
    with pytest.raises(ValueError):
        calendar_window(days, NOW)


@pytest.mark.parametrize(
    "zone,clock,expected",
    [
        ("America/New_York", datetime(2026, 3, 9, 4, tzinfo=timezone.utc), 23),
        ("America/New_York", datetime(2026, 11, 2, 5, tzinfo=timezone.utc), 25),
    ],
)
def test_calendar_uses_local_midnight_across_dst(monkeypatch, zone, clock, expected):
    monkeypatch.setattr(settings, "CELERY_TIMEZONE", zone)
    window = calendar_window(2, clock)
    assert (window.end - window.start).total_seconds() == expected * 3600
    assert len(window.dates) == 2
    assert aware_utc(window.start).utcoffset() == timedelta(0)


def test_explicit_period_is_half_open_and_bounded(monkeypatch):
    monkeypatch.setattr(settings, "CELERY_TIMEZONE", "UTC")
    end = datetime(2026, 10, 31, tzinfo=timezone.utc)
    window = explicit_window(end - timedelta(days=1), end)
    assert len(window.dates) == 1 and window.dates[0].isoformat() == "2026-10-30"
    for start, stop in (
        (end, end),
        (end, end - timedelta(seconds=1)),
        (end - timedelta(days=33), end),
    ):
        with pytest.raises(ValueError):
            explicit_window(start, stop)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,manager_status,operator_status",
    [
        ("super", 200, 200),
        ("manager", 200, 200),
        ("operator", 403, 200),
        ("auditor", 403, 403),
        ("customer", 403, 403),
        ("owner", 403, 403),
        ("roleless", 401, 401),
        ("inactive", 401, 401),
    ],
)
async def test_mounted_dashboard_role_matrix(
    dashboard_db, who, manager_status, operator_status
):
    client, _, ids = dashboard_db
    for name, status in (("manager", manager_status), ("operator", operator_status)):
        for prefix in ("/api/v1/dashboard/", "/api/v1/dashboard/dashboard/"):
            response = client.get(prefix + name, headers=headers(ids, who))
            assert response.status_code == status, response.text


@pytest.mark.asyncio
async def test_unauthenticated_and_invalid_queries(dashboard_db):
    client, _, ids = dashboard_db
    assert client.get("/api/v1/dashboard/manager").status_code == 401
    for query in ("days=0", "days=32", "days=bad"):
        assert (
            client.get(
                "/api/v1/dashboard/manager?" + query, headers=headers(ids)
            ).status_code
            == 422
        )


@pytest.mark.asyncio
async def test_empty_snapshot_preserves_missing_evidence(dashboard_db):
    client, _, ids = dashboard_db
    response = client.get("/api/v1/dashboard/manager?days=7", headers=headers(ids))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"]["orders_created"] == 0
    assert data["summary"]["sla_percent"] is None
    assert data["summary"]["avg_delivery_minutes"] is None
    assert data["summary"]["active_users"] == 8
    assert len(data["series"]) == 7
    assert all(
        row["orders_created"] == row["completed_deliveries"] == 0
        for row in data["series"]
    )
    assert data["orders_today"] is None
    assert (
        data["source"] == "database_snapshot" and data["financials_available"] is False
    )
    assert data["period_end"] == data["generated_at"] == "2026-10-30T12:00:00Z"


@pytest.mark.asyncio
async def test_real_cohorts_unknown_sla_and_valid_durations(dashboard_db):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        # An old order completed today still belongs to the completion cohort.
        await delivery(
            db,
            ids["rider"],
            completed=CLOCK - timedelta(hours=1),
            started=CLOCK - timedelta(hours=2),
            sla=True,
            created=CLOCK - timedelta(days=20),
        )
        await delivery(
            db,
            ids["rider"],
            completed=CLOCK - timedelta(hours=1),
            started=CLOCK,
            sla=False,
        )
        await delivery(db, ids["rider"], completed=CLOCK - timedelta(hours=2))
        await delivery(db, ids["rider"], completed=CLOCK)  # exclusive upper boundary
        await delivery(db, ids["rider"], completed=CLOCK + timedelta(days=1))
        await delivery(
            db,
            ids["rider"],
            completed=CLOCK - timedelta(hours=1),
            status=DeliveryStatus.FALLIDA,
        )
        db.add(order(status=OrderStatus.CANCELADO))
        await db.commit()
    data = client.get("/api/v1/dashboard/manager?days=1", headers=headers(ids)).json()
    summary = data["summary"]
    assert summary["orders_created"] == 6 and summary["cancelled_orders"] == 1
    assert summary["completed_deliveries"] == 3
    assert summary["sla_known_count"] == 2 and summary["sla_unknown_count"] == 1
    assert summary["sla_percent"] == 50
    assert (
        summary["valid_duration_count"] == 1 and summary["avg_delivery_minutes"] == 60
    )
    assert data["series"] == [
        {"date": "2026-10-30", "orders_created": 6, "completed_deliveries": 3}
    ]
    assert data["orders_today"] == 6 and data["sla_breached"] == 1
    assert "total_revenue" not in data


@pytest.mark.asyncio
async def test_all_unknown_sla_is_not_zero_percent(dashboard_db):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        await delivery(db, ids["rider"], completed=CLOCK - timedelta(hours=1))
        await db.commit()
    summary = client.get("/api/v1/dashboard/manager", headers=headers(ids)).json()[
        "summary"
    ]
    assert summary["sla_percent"] is None and summary["sla_unknown_count"] == 1


@pytest.mark.asyncio
async def test_local_date_groups_utc_columns_correctly(dashboard_db, monkeypatch):
    client, sessions, ids = dashboard_db
    monkeypatch.setattr(settings, "CELERY_TIMEZONE", "America/Caracas")
    async with sessions() as db:
        db.add_all(
            [
                order(created_at=datetime(2026, 10, 30, 3, 59)),
                order(created_at=datetime(2026, 10, 30, 4)),
            ]
        )
        await db.commit()
    data = client.get("/api/v1/dashboard/manager?days=2", headers=headers(ids)).json()
    assert data["timezone"] == "America/Caracas"
    assert [(r["date"], r["orders_created"]) for r in data["series"]] == [
        ("2026-10-29", 1),
        ("2026-10-30", 1),
    ]
    assert data["period_start"] == "2026-10-29T04:00:00Z"


@pytest.mark.asyncio
async def test_global_totals_are_not_preview_lengths_and_shift_attendance_is_real(
    dashboard_db,
):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        db.add_all([order(created_at=CLOCK - timedelta(days=60)) for _ in range(25)])
        db.add(order(status=OrderStatus.ASIGNADO))
        for checked_in, checked_out in ((None, None), (CLOCK, None), (CLOCK, CLOCK)):
            db.add(
                Shift(
                    rider_id=ids["rider"],
                    shift_date=CLOCK,
                    start_time=time(8),
                    end_time=time(17),
                    status=ShiftStatus.EN_CURSO,
                    check_in_at=checked_in,
                    check_out_at=checked_out,
                )
            )
        for status in ("OPEN", "ACKNOWLEDGED", "RESOLVED"):
            db.add(Alert(alert_type="SLA_WARNING", title="Test", status=status))
        await db.commit()
    data = client.get(
        "/api/v1/dashboard/operator?days=1", headers=headers(ids, "operator")
    ).json()
    assert data["summary"]["orders_created"] == 1
    assert data["summary"]["pending_orders"] == 25
    assert data["summary"]["in_progress_orders"] == 1
    assert data["summary"]["active_shifts"] == 1
    assert data["summary"]["open_alerts"] == 2
    assert len(data["pending_orders"]) == 20 and data["queue_truncated"] is True
    assert (
        data["pending_orders"]
        == client.get(
            "/api/v1/dashboard/operator", headers=headers(ids, "operator")
        ).json()["pending_orders"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lat,lng,minutes,online,status,user_active,visible",
    [
        (0, 0, 0, True, "ACTIVO", True, True),
        (1, 2, 5, True, "OCUPADO", True, True),
        (1, 2, 6, True, "ACTIVO", True, False),
        (1, 2, -1, True, "ACTIVO", True, False),
        (91, 2, 0, True, "ACTIVO", True, False),
        (0, 181, 0, True, "ACTIVO", True, False),
        (float("nan"), 2, 0, True, "ACTIVO", True, False),
        (0, 0, 0, False, "ACTIVO", True, False),
        (0, 0, 0, True, "SUSPENDIDO", True, False),
        (0, 0, 0, True, "ACTIVO", False, False),
    ],
)
async def test_positions_are_fresh_valid_and_authorized(
    dashboard_db, lat, lng, minutes, online, status, user_active, visible
):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        await db.execute(
            update(Rider)
            .where(Rider.id == ids["rider"])
            .values(
                last_lat=lat,
                last_lng=lng,
                last_location_at=CLOCK - timedelta(minutes=minutes),
                is_online=online,
                status=RiderStatus(status),
            )
        )
        await db.execute(
            update(User).where(User.id == ids["owner"]).values(is_active=user_active)
        )
        await db.commit()
    data = client.get(
        "/api/v1/dashboard/operator", headers=headers(ids, "operator")
    ).json()
    assert len(data["riders_online"]) == int(visible)
    assert data["summary"]["riders_online"] == int(
        online and status in ("ACTIVO", "OCUPADO") and user_active
    )
    if visible:
        assert data["riders_online"][0]["lat"] == lat


@pytest.mark.asyncio
async def test_live_role_and_token_revocation_control_dashboard(dashboard_db):
    client, sessions, ids = dashboard_db
    token = headers(ids)
    async with sessions() as db:
        await db.execute(
            update(User).where(User.id == ids["manager"]).values(role=UserRole.OPERADOR)
        )
        await db.commit()
    assert client.get("/api/v1/dashboard/manager", headers=token).status_code == 403
    assert client.get("/api/v1/dashboard/operator", headers=token).status_code == 200
    async with sessions() as db:
        await db.execute(
            update(User).where(User.id == ids["manager"]).values(token_version=1)
        )
        await db.commit()
    assert client.get("/api/v1/dashboard/operator", headers=token).status_code == 401


async def metric(db, rider, **values):
    row = ProductivityMetrics(
        rider_id=rider,
        **{
            "period_start": CLOCK - timedelta(days=1),
            "period_end": CLOCK,
            "total_deliveries": 4,
            "on_time_deliveries": 1,
            "late_deliveries": 1,
            **values,
        },
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,status",
    [
        ("manager", 200),
        ("operator", 200),
        ("auditor", 200),
        ("owner", 200),
        ("rival", 403),
        ("customer", 403),
    ],
)
async def test_history_owner_and_staff_permissions(dashboard_db, who, status):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        await metric(db, ids["rider"])
        await db.commit()
    for prefix in (
        "/api/v1/productivity/rider/",
        "/api/v1/productivity/productivity/rider/",
    ):
        response = client.get(prefix + str(ids["rider"]), headers=headers(ids, who))
        assert response.status_code == status, response.text
        if status == 200:
            data = response.json()[0]
            assert data["sla_percent"] == 50 and data["unknown_sla_count"] == 2
            assert (
                data["performance_score"] is None
                and data["source"] == "consolidated_metrics"
            )


@pytest.mark.asyncio
async def test_history_unknowns_not_defaults_and_shift_rows_not_double_counted(
    dashboard_db,
):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        row = await metric(db, ids["rider"], on_time_deliveries=0, late_deliveries=0)
        await db.execute(
            update(ProductivityMetrics)
            .where(ProductivityMetrics.id == row.id)
            .values(
                total_earnings=None,
                total_distance_km=float("nan"),
                avg_delivery_time_minutes=-1,
            )
        )
        shift = Shift(
            rider_id=ids["rider"],
            shift_date=CLOCK,
            start_time=time(8),
            end_time=time(17),
        )
        db.add(shift)
        await db.flush()
        await metric(db, ids["rider"], shift_id=shift.id)
        await db.commit()
    data = client.get(
        f"/api/v1/productivity/rider/{ids['rider']}", headers=headers(ids, "owner")
    ).json()
    assert len(data) == 1
    assert data[0]["sla_percent"] is None and data[0]["unknown_sla_count"] == 4
    assert all(
        data[0][key] is None
        for key in ("total_earnings", "total_distance_km", "avg_delivery_minutes")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["duplicate", "negative", "excess", "period"])
async def test_incoherent_history_fails_explicitly_even_with_limit_one(
    dashboard_db, kind
):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        values = (
            {"total_deliveries": -1}
            if kind == "negative"
            else (
                {"total_deliveries": 1}
                if kind == "excess"
                else (
                    {"period_end": CLOCK - timedelta(days=2)}
                    if kind == "period"
                    else {}
                )
            )
        )
        await metric(db, ids["rider"], **values)
        if kind == "duplicate":
            await metric(db, ids["rider"])
        await db.commit()
    response = client.get(
        f"/api/v1/productivity/rider/{ids['rider']}?limit=1", headers=headers(ids)
    )
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_ranking_uses_completed_volume_and_unknown_sla_remains_null(dashboard_db):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        for rider in (ids["rider"], ids["other_rider"], ids["rider"]):
            await delivery(db, rider, completed=CLOCK - timedelta(hours=1))
        await delivery(db, ids["other_rider"], completed=CLOCK)
        await db.commit()
    response = client.get(
        "/api/v1/productivity/ranking?days=1", headers=headers(ids, "operator")
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert [(r["rider_id"], r["completed_deliveries"]) for r in data] == [
        (str(ids["rider"]), 2),
        (str(ids["other_rider"]), 1),
    ]
    assert all(
        r["sla_percent"] is None
        and r["performance_score"] is None
        and r["ranking_basis"] == "completed_deliveries"
        for r in data
    )
    for who in ("owner", "auditor", "customer"):
        assert (
            client.get(
                "/api/v1/productivity/ranking", headers=headers(ids, who)
            ).status_code
            == 403
        )


@pytest.mark.asyncio
async def test_missing_rider_uuid_limits_and_read_only_comparison(dashboard_db):
    client, sessions, ids = dashboard_db
    assert (
        client.get(
            f"/api/v1/productivity/rider/{uuid4()}", headers=headers(ids)
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/v1/productivity/rider/invalid", headers=headers(ids)
        ).status_code
        == 422
    )
    for path in (
        f"rider/{ids['rider']}?limit=0",
        "ranking?days=32",
        "ranking?limit=101",
    ):
        assert (
            client.get("/api/v1/productivity/" + path, headers=headers(ids)).status_code
            == 422
        )
    async with sessions() as db:
        await metric(
            db,
            ids["rider"],
            period_start=datetime(2026, 10, 28),
            period_end=datetime(2026, 10, 29),
            created_at=datetime(2026, 10, 30),
            on_time_deliveries=0,
            late_deliveries=0,
        )
        await db.commit()
        result = await DashboardService(db).get_productivity_comparison(
            datetime(2026, 10, 28), datetime(2026, 10, 29)
        )
        assert result == [
            {
                "date": datetime(2026, 10, 28).date(),
                "avg_deliveries_per_hour": None,
                "avg_sla_compliance": None,
                "total_deliveries": 4,
            }
        ]
        assert (
            await db.scalar(select(func.count()).select_from(ProductivityMetrics)) == 1
        )
        with pytest.raises(ValueError):
            await DashboardService(db).get_productivity_comparison(
                datetime(2026, 10, 28), datetime(2026, 10, 29), "week"
            )


@pytest.mark.asyncio
async def test_legacy_operator_uses_real_enum_and_valid_sla_deadlines(dashboard_db):
    _, sessions, ids = dashboard_db
    async with sessions() as db:
        row = await delivery(
            db,
            ids["rider"],
            status=DeliveryStatus.EN_ROUTE,
            started=CLOCK - timedelta(minutes=20),
        )
        row.sla_expected_minutes = 30
        await db.commit()
        result = await DashboardService(db).get_operator_dashboard()
        assert result["in_progress_orders"] == 0
        assert result["at_risk_deliveries"] == 1


@pytest.mark.asyncio
async def test_measured_zero_and_legacy_manager_contract(dashboard_db):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        await delivery(
            db,
            ids["rider"],
            completed=CLOCK - timedelta(hours=1),
            started=CLOCK - timedelta(hours=1),
            sla=False,
        )
        await db.commit()
        legacy = await DashboardService(db).get_manager_dashboard(
            CLOCK - timedelta(hours=2), CLOCK
        )
        assert legacy["sla_percentage"] == 0
        assert legacy["avg_delivery_time_minutes"] == 0
        assert legacy["delivery_rate"] is None and legacy["avg_cost_per_order"] is None
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 1
    data = client.get("/api/v1/dashboard/manager", headers=headers(ids)).json()
    assert data["summary"]["sla_percent"] == 0
    assert data["summary"]["avg_delivery_minutes"] == 0


@pytest.mark.asyncio
async def test_positions_preview_cap_does_not_limit_online_total(dashboard_db):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        for index in range(51):
            user = User(
                id=uuid4(),
                email=f"position-{index}@dashboard.test",
                hashed_password="unused",
                first_name="Test",
                last_name="Rider",
                role=UserRole.REPARTIDOR,
            )
            db.add(user)
            await db.flush()
            await db.execute(
                text(
                    "INSERT INTO riders (id,user_id,status,is_online,last_lat,last_lng,last_location_at) VALUES (:id,:user,'ACTIVO',TRUE,0,0,:clock)"
                ),
                {"id": uuid4(), "user": user.id, "clock": CLOCK},
            )
        await db.commit()
    data = client.get(
        "/api/v1/dashboard/operator", headers=headers(ids, "operator")
    ).json()
    assert data["summary"]["riders_online"] == 51
    assert len(data["riders_online"]) == 50 and data["positions_truncated"] is True


@pytest.mark.asyncio
async def test_ranking_ties_are_stable_and_legacy_alias_is_guarded(dashboard_db):
    client, sessions, ids = dashboard_db
    async with sessions() as db:
        for rid in (ids["rider"], ids["other_rider"]):
            await delivery(db, rid, completed=CLOCK - timedelta(hours=1), sla=True)
        await db.commit()
    data = client.get(
        "/api/v1/productivity/productivity/ranking?limit=1", headers=headers(ids)
    ).json()
    assert data[0]["rider_id"] == str(min(ids["rider"], ids["other_rider"]))
    assert data[0]["sla_percent"] == 100
    assert (
        client.get(
            "/api/v1/productivity/productivity/ranking", headers=headers(ids, "owner")
        ).status_code
        == 403
    )

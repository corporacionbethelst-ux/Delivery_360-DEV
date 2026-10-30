"""Native PostgreSQL route, HTTP authorization, concurrency and rollback contracts."""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text, func, update
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.api.v1 import routes as api
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.crud.route import route as crud
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.route import Route, RouteStatus, RoutePoint, RouteDeviation
from app.services.route_service import RouteService

PLAN = [{"latitude": 0.0, "longitude": 0.0}, {"latitude": 0.0, "longitude": 0.02}]


@pytest.fixture
async def routes_db(pg_wallets, monkeypatch, tmp_path):
    sessions, _, riders = pg_wallets
    monkeypatch.chdir(tmp_path)
    async with sessions() as db:
        conn = await db.connection()
        await conn.run_sync(
            lambda c: Rider.__table__.c.status.type.create(c, checkfirst=True)
        )
        await db.execute(
            text(
                "ALTER TABLE riders ADD COLUMN status riderstatus DEFAULT 'ACTIVO', ADD COLUMN is_online BOOLEAN DEFAULT true, ADD COLUMN approved_at TIMESTAMP, ADD COLUMN last_lat FLOAT, ADD COLUMN last_lng FLOAT, ADD COLUMN last_location_at TIMESTAMP, ADD COLUMN updated_at TIMESTAMP"
            )
        )
        await db.execute(text("CREATE TABLE orders(id UUID PRIMARY KEY, status VARCHAR(30) DEFAULT 'EN_RUTA')"))
        for model in (RiderDocument, Delivery, Route, RoutePoint, RouteDeviation):
            await conn.run_sync(model.__table__.create)
        actors = list((await db.scalars(select(User).order_by(User.email))).all())
        staff = User(
            email="route-manager@example.test",
            hashed_password="unused",
            first_name="Route",
            last_name="Manager",
            role=UserRole.GERENTE,
        )
        db.add(staff)
        deliveries = []
        for index, rider_id in enumerate(riders):
            for kind in DocumentType:
                folder = tmp_path / "uploads" / "documents" / str(rider_id)
                folder.mkdir(parents=True, exist_ok=True)
                file = folder / (kind.value + ".pdf")
                file.write_bytes(b"%PDF test evidence")
                db.add(
                    RiderDocument(
                        rider_id=rider_id,
                        type=kind,
                        status=DocumentStatus.APROBADO,
                        file_url=f"/uploads/documents/{rider_id}/{file.name}",
                    )
                )
            oid = uuid4()
            await db.execute(text("INSERT INTO orders(id) VALUES (:id)"), {"id": oid})
            obj = Delivery(
                order_id=oid, rider_id=rider_id, status=DeliveryStatus.EN_ROUTE
            )
            db.add(obj)
            await db.flush()
            deliveries.append(obj.id)
        await db.commit()
        owners = list((await db.execute(text("SELECT id, user_id FROM riders"))).all())
        owner_ids = {row.id: row.user_id for row in owners}
        staff_id = staff.id
    ids = []
    for did in deliveries:
        async with sessions() as db:
            obj = await RouteService(db).create_route(did, PLAN, 2.224, 10)
            ids.append(obj.id)
    return {
        "sessions": sessions,
        "riders": riders,
        "deliveries": deliveries,
        "routes": ids,
        "staff": staff_id,
        "owners": owner_ids,
    }


@pytest.fixture
async def route_http(routes_db):
    ctx = routes_db
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/routes")
    actor = [ctx["staff"]]

    async def database():
        async with ctx["sessions"]() as db:
            try:
                yield db
            finally:
                await db.rollback()

    async def current_user():
        async with ctx["sessions"]() as db:
            return await db.get(User, actor[0])

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, ctx, actor


async def set_role(ctx, role, uid=None):
    async with ctx["sessions"]() as db:
        await db.execute(
            update(User).where(User.id == (uid or ctx["staff"])).values(role=role)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_route_storage_uses_real_fields_enums_and_uuid(routes_db):
    ctx = routes_db
    async with ctx["sessions"]() as db:
        obj = await crud.get_route(db, ctx["routes"][0])
        assert obj.status is RouteStatus.PLANIFICADA and obj.planned_route == PLAN
        assert obj.planned_distance_km == 2.224 and obj.planned_duration_minutes == 10
        assert (await crud.get_route_by_delivery(db, ctx["deliveries"][0])).id == obj.id
        point = await crud.add_route_point(db, obj.id, 0, 0, heading=90, speed=30)
        assert point.route_id == obj.id and point.timestamp and point.heading == 90
        assert (await crud.get_route(db, obj.id)).status is RouteStatus.EN_PROGRESO


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,allowed",
    [
        (UserRole.GERENTE, True),
        (UserRole.SUPERADMIN, True),
        (UserRole.OPERADOR, True),
        (UserRole.AUDITOR, True),
        (UserRole.CLIENTE, False),
        (None, False),
    ],
)
async def test_read_roles_cannot_inherit_access_from_authentication(
    route_http, role, allowed
):
    client, ctx, _ = route_http
    await set_role(ctx, role)
    for path in (
        "",
        f"/{ctx['routes'][0]}",
        f"/{ctx['routes'][0]}/points",
        f"/{ctx['routes'][0]}/metrics",
        f"/{ctx['routes'][0]}/deviations",
    ):
        response = await client.get("/api/v1/routes" + path)
        assert response.status_code == (200 if allowed else 403), response.text


@pytest.mark.asyncio
async def test_rider_can_read_only_own_routes_and_no_other_history(route_http):
    client, ctx, actor = route_http
    actor[0] = ctx["owners"][ctx["riders"][0]]
    response = await client.get("/api/v1/routes")
    assert [r["id"] for r in response.json()["data"]] == [str(ctx["routes"][0])]
    assert (
        await client.get(f"/api/v1/routes/{ctx['routes'][0]}/metrics")
    ).status_code == 200
    for suffix in ("", "/metrics", "/points", "/deviations"):
        assert (
            await client.get(f"/api/v1/routes/{ctx['routes'][1]}" + suffix)
        ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/routes/{ctx['riders'][1]}/track", json={"lat": 0, "lng": 0}
        )
    ).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.AUDITOR, UserRole.CLIENTE, None])
async def test_readonly_or_unknown_roles_cannot_write(route_http, role):
    client, ctx, _ = route_http
    await set_role(ctx, role)
    assert (
        await client.post(
            f"/api/v1/routes/{ctx['riders'][0]}/track", json={"lat": 0, "lng": 0}
        )
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/routes/{ctx['routes'][0]}/analyze")
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/routes",
            json={"delivery_id": str(ctx["deliveries"][0]), "planned_route": PLAN},
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_track_canonical_and_compatibility_alias_persist_real_points(route_http):
    client, ctx, actor = route_http
    actor[0] = ctx["owners"][ctx["riders"][0]]
    for middle in ("", "/routes"):
        response = await client.post(
            f"/api/v1/routes{middle}/{ctx['riders'][0]}/track",
            json={"lat": 0, "lng": 0.01, "heading": 90, "speed_kmh": 18},
        )
        assert response.status_code == 200, response.text
        assert response.json()["route_id"] == str(ctx["routes"][0])
    assert response.json()["points_count"] == 2
    async with ctx["sessions"]() as db:
        snapshot = (
            await db.execute(
                select(Rider.last_lat, Rider.last_lng, Rider.last_location_at).where(
                    Rider.id == ctx["riders"][0]
                )
            )
        ).one()
        assert (
            snapshot.last_lat == 0
            and snapshot.last_lng == 0.01
            and snapshot.last_location_at
        )
    history = await client.get(
        f"/api/v1/routes/{ctx['routes'][0]}/points?limit=1&skip=1"
    )
    assert (
        len(history.json()["data"]) == 1
        and history.json()["data"][0]["speed_kmh"] == 18
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [RiderStatus.SUSPENDIDO, RiderStatus.INACTIVO, RiderStatus.PENDIENTE]
)
async def test_route_ingestion_cannot_bypass_rider_restriction(route_http, status):
    client, ctx, _ = route_http
    async with ctx["sessions"]() as db:
        await db.execute(
            update(Rider).where(Rider.id == ctx["riders"][0]).values(status=status)
        )
        await db.commit()
    response = await client.post(
        f"/api/v1/routes/{ctx['riders'][0]}/track", json={"lat": 0, "lng": 0}
    )
    assert response.status_code == 403
    async with ctx["sessions"]() as db:
        assert await db.scalar(select(func.count()).select_from(RoutePoint)) == 0


@pytest.mark.asyncio
async def test_missing_documents_do_not_commit_gps_payload(route_http):
    client, ctx, _ = route_http
    async with ctx["sessions"]() as db:
        await db.execute(
            update(RiderDocument)
            .where(RiderDocument.rider_id == ctx["riders"][0])
            .values(status=DocumentStatus.RECHAZADO)
        )
        await db.commit()
    assert (
        await client.post(
            f"/api/v1/routes/{ctx['riders'][0]}/track", json={"lat": 0, "lng": 0}
        )
    ).status_code == 403
    async with ctx["sessions"]() as db:
        assert await db.scalar(select(func.count()).select_from(RoutePoint)) == 0


@pytest.mark.asyncio
async def test_terminal_delivery_or_route_cannot_accept_more_points(route_http):
    client, ctx, _ = route_http
    async with ctx["sessions"]() as db:
        await db.execute(
            update(Delivery)
            .where(Delivery.id == ctx["deliveries"][0])
            .values(status=DeliveryStatus.COMPLETADA)
        )
        await db.commit()
    assert (
        await client.post(
            f"/api/v1/routes/{ctx['riders'][0]}/track", json={"lat": 0, "lng": 0}
        )
    ).status_code == 409
    async with ctx["sessions"]() as db:
        await db.execute(
            update(Delivery)
            .where(Delivery.id == ctx["deliveries"][0])
            .values(status=DeliveryStatus.EN_ROUTE)
        )
        await db.execute(
            update(Route)
            .where(Route.id == ctx["routes"][0])
            .values(status=RouteStatus.CANCELADA)
        )
        await db.commit()
    assert (
        await client.post(
            f"/api/v1/routes/{ctx['riders'][0]}/track", json={"lat": 0, "lng": 0}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_duplicate_create_is_conflict_missing_delivery_is_404(route_http):
    client, ctx, _ = route_http
    response = await client.post(
        "/api/v1/routes",
        json={"delivery_id": str(ctx["deliveries"][0]), "planned_route": PLAN},
    )
    assert response.status_code == 409
    response = await client.post(
        "/api/v1/routes/", json={"delivery_id": str(uuid4()), "planned_route": PLAN}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_service_deviation_metres_and_resolution_persist_not_python_attributes(
    routes_db,
):
    ctx = routes_db
    async with ctx["sessions"]() as db:
        service = RouteService(db)
        assert await service.detect_deviation(ctx["routes"][0], 0, 0.01, PLAN) is None
        obj = await service.detect_deviation(ctx["routes"][0], 0.01, 0.01, PLAN)
        assert 1.11 < obj.distance_from_route_km < 1.12 and obj.status == "abierto"
        did = obj.id
    async with ctx["sessions"]() as db:
        obj = await crud.resolve_deviation(db, did, "Operación revisada", ctx["staff"])
        resolved_at = obj.resolved_at
        assert obj.status == "resuelto" and obj.resolved_by == ctx["staff"]
    async with ctx["sessions"]() as db:
        obj = await crud.resolve_deviation(db, did, "No sobrescribir", None)
        assert (
            obj.resolved_at == resolved_at
            and obj.resolution_notes == "Operación revisada"
        )
        assert await crud.get_active_deviations(db) == []


@pytest.mark.asyncio
async def test_parallel_worker_replays_never_duplicate_point_deviations(routes_db):
    ctx = routes_db
    async with ctx["sessions"]() as db:
        for lat in (0, 0.001, 0.006):
            await crud.add_route_point(db, ctx["routes"][0], lat, 0.01)

    async def run():
        async with ctx["sessions"]() as db:
            return await RouteService(db).analyze_route(ctx["deliveries"][0])

    results = await asyncio.gather(run(), run(), run())
    assert sorted(r["deviations_count"] for r in results) == [0, 0, 1]
    async with ctx["sessions"]() as db:
        rows = list((await db.scalars(select(RouteDeviation))).all())
        assert len(rows) == 1 and 0.667 < rows[0].distance_from_route_km < 0.668
        assert rows[0].actual_location["route_point_id"]


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_point_and_route_transition(routes_db):
    ctx = routes_db
    async with ctx["sessions"]() as db:
        with patch.object(db, "commit", side_effect=RuntimeError("commit unavailable")):
            with pytest.raises(RuntimeError):
                await crud.add_route_point(db, ctx["routes"][0], 0, 0.01)
    async with ctx["sessions"]() as db:
        assert await db.scalar(select(func.count()).select_from(RoutePoint)) == 0
        assert (await db.get(Route, ctx["routes"][0])).status is RouteStatus.PLANIFICADA


@pytest.mark.asyncio
async def test_http_analysis_and_resolution_bind_both_resource_ids(route_http):
    client, ctx, _ = route_http
    async with ctx["sessions"]() as db:
        await crud.add_route_point(db, ctx["routes"][0], 0.01, 0.01)
    response = await client.post(f"/api/v1/routes/{ctx['routes'][0]}/analyze")
    assert response.status_code == 200 and response.json()["deviations_count"] == 1
    response = await client.get(f"/api/v1/routes/{ctx['routes'][0]}/deviations")
    did = response.json()["data"][0]["id"]
    assert (
        await client.post(
            f"/api/v1/routes/{ctx['routes'][1]}/deviations/{did}/resolve",
            json={"notes": "revisado"},
        )
    ).status_code == 404
    response = await client.post(
        f"/api/v1/routes/{ctx['routes'][0]}/deviations/{did}/resolve",
        json={"notes": "revisado"},
    )
    assert response.status_code == 200 and response.json()["status"] == "resuelto"


@pytest.mark.asyncio
async def test_invalid_time_range_and_missing_route_return_explicit_errors(route_http):
    client, ctx, _ = route_http
    assert (
        await client.get(
            f"/api/v1/routes/{ctx['routes'][0]}/points?start_time=2026-10-30&end_time=2026-10-29"
        )
    ).status_code == 422
    assert (await client.get(f"/api/v1/routes/{uuid4()}/metrics")).status_code == 404
    assert (await client.get("/api/v1/routes?limit=10000")).status_code == 422


async def additional_delivery(ctx, status=DeliveryStatus.EN_ROUTE):
    async with ctx["sessions"]() as db:
        oid = uuid4()
        await db.execute(text("INSERT INTO orders(id) VALUES (:id)"), {"id": oid})
        obj = Delivery(order_id=oid, rider_id=ctx["riders"][0], status=status)
        db.add(obj)
        await db.commit()
        return obj.id


@pytest.mark.asyncio
async def test_create_route_http_stores_plan_and_rejects_terminal_delivery(route_http):
    client, ctx, _ = route_http
    did = await additional_delivery(ctx)
    response = await client.post(
        "/api/v1/routes",
        json={
            "delivery_id": str(did),
            "planned_route": PLAN,
            "distance_km": 2.224,
            "duration_minutes": 12,
        },
    )
    assert response.status_code == 201, response.text
    rid = response.json()["id"]
    assert response.json()["planned_duration_minutes"] == 12
    assert (await client.get(f"/api/v1/routes/{rid}/metrics")).json()[
        "points_count"
    ] == 0
    terminal = await additional_delivery(ctx, DeliveryStatus.COMPLETADA)
    assert (
        await client.post(
            "/api/v1/routes", json={"delivery_id": str(terminal), "planned_route": PLAN}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_parallel_create_locks_delivery_and_does_not_duplicate_route(routes_db):
    ctx = routes_db
    did = await additional_delivery(ctx)

    async def create():
        async with ctx["sessions"]() as db:
            return await RouteService(db).create_route(did, PLAN)

    results = await asyncio.gather(create(), create(), return_exceptions=True)
    assert sum(isinstance(r, Route) for r in results) == 1
    assert sum(isinstance(r, ValueError) for r in results) == 1


@pytest.mark.asyncio
async def test_ambiguous_active_deliveries_require_explicit_selection(route_http):
    client, ctx, _ = route_http
    did = await additional_delivery(ctx)
    url = f"/api/v1/routes/{ctx['riders'][0]}/track"
    assert (await client.post(url, json={"lat": 0, "lng": 0})).status_code == 409
    assert (
        await client.post(url, json={"lat": 0, "lng": 0, "delivery_id": str(did)})
    ).status_code == 409
    assert (
        await client.post(
            url, json={"lat": 0, "lng": 0, "delivery_id": str(ctx["deliveries"][0])}
        )
    ).status_code == 200
    assert (
        await client.post(
            url, json={"lat": 0, "lng": 0, "delivery_id": str(ctx["deliveries"][1])}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_api_commit_failure_cannot_leave_a_point_without_rider_snapshot(
    route_http,
):
    from sqlalchemy.ext.asyncio import AsyncSession

    client, ctx, _ = route_http
    with patch.object(AsyncSession, "commit", side_effect=RuntimeError("unavailable")):
        with pytest.raises(RuntimeError):
            await client.post(
                f"/api/v1/routes/{ctx['riders'][0]}/track", json={"lat": 0, "lng": 0.01}
            )
    async with ctx["sessions"]() as db:
        assert await db.scalar(select(func.count()).select_from(RoutePoint)) == 0
        assert (
            await db.scalar(select(Rider.last_lng).where(Rider.id == ctx["riders"][0]))
            is None
        )
        assert (await db.get(Route, ctx["routes"][0])).status is RouteStatus.PLANIFICADA


@pytest.mark.asyncio
async def test_native_worker_uses_async_session_and_disposes_engine(
    routes_db, monkeypatch
):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.workers import route_analysis_worker as worker

    ctx = routes_db
    async with ctx["sessions"]() as db:
        schema = await db.scalar(text("SELECT current_schema()"))
        url = db.bind.url
        await crud.add_route_point(db, ctx["routes"][0], 0.01, 0.01)
    engines = []

    def factory(_url, **kwargs):
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": schema}}, **kwargs
        )
        engines.append(engine)
        return engine

    monkeypatch.setattr(worker, "create_async_engine", factory)
    assert (await worker.run_analysis(ctx["deliveries"][0]))["deviations_count"] == 1
    assert (await worker.run_analysis(ctx["deliveries"][0]))["deviations_count"] == 0
    assert len(engines) == 2


@pytest.mark.asyncio
async def test_invalid_stored_plan_does_not_write_fabricated_deviations(routes_db):
    ctx = routes_db
    async with ctx["sessions"]() as db:
        await crud.add_route_point(db, ctx["routes"][0], 0.01, 0.01)
        await db.execute(
            update(Route)
            .where(Route.id == ctx["routes"][0])
            .values(planned_route={"legacy": "unknown"})
        )
        await db.commit()
        with pytest.raises(ValueError):
            await RouteService(db).analyze_route(ctx["deliveries"][0])
        assert await db.scalar(select(func.count()).select_from(RouteDeviation)) == 0


@pytest.mark.asyncio
async def test_oversized_history_is_refused_without_partial_metrics(routes_db):
    from sqlalchemy import insert

    ctx = routes_db
    async with ctx["sessions"]() as db:
        await db.execute(
            insert(RoutePoint),
            [
                {
                    "id": uuid4(),
                    "route_id": ctx["routes"][0],
                    "latitude": 0,
                    "longitude": 0,
                    "timestamp": datetime(2026, 10, 29) + timedelta(seconds=i),
                }
                for i in range(10001)
            ],
        )
        await db.commit()
        with pytest.raises(ValueError, match="10000"):
            await RouteService(db).calculate_route_metrics(ctx["routes"][0])
        with pytest.raises(ValueError, match="10000"):
            await RouteService(db).analyze_route(ctx["deliveries"][0])


@pytest.mark.asyncio
async def test_route_geometry_batch_does_not_block_the_event_loop(
    routes_db, monkeypatch
):
    import threading
    from app.services import route_service

    ctx = routes_db
    main_thread = threading.get_ident()
    observed = []
    original = route_service.route_distance_m

    def measure(*args):
        observed.append(threading.get_ident())
        return original(*args)

    monkeypatch.setattr(route_service, "route_distance_m", measure)
    async with ctx["sessions"]() as db:
        await crud.add_route_point(db, ctx["routes"][0], 0.01, 0.01)
        assert (await RouteService(db).analyze_route(ctx["deliveries"][0]))[
            "deviations_count"
        ] == 1
    assert observed and all(value != main_thread for value in observed)

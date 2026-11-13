"""Initialize only the dedicated local-test Compose database, never an existing app DB."""

import asyncio
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def validate_environment(env):
    from urllib.parse import urlsplit

    target = urlsplit(env.get("DATABASE_URL", ""))
    sync = urlsplit(env.get("DATABASE_URL_SYNC", ""))
    if (
        env.get("APP_ENV") != "testing"
        or env.get("ENVIRONMENT") != "testing"
        or target.scheme not in {"postgresql", "postgresql+asyncpg"}
        or target.hostname != "test-db"
        or target.path != "/test_delivery360_manual"
        or target.username != "local_test"
        or target.port != 5432
        or target.query
        or target.fragment
        or sync != target._replace(scheme="postgresql")
        or not re.fullmatch(r"[a-f0-9]{16}", env.get("LOCAL_TEST_ID", ""))
        or not re.fullmatch(r"[A-Za-z0-9_-]{24,64}", env.get("LOCAL_TEST_PASSWORD", ""))
        or any(
            env.get(key, "").lower() != "false"
            for key in (
                "EMAILS_ENABLED",
                "NOTIFICATIONS_ENABLED",
                "ENABLE_ELECTRONIC_INVOICING",
                "TRACKING_SCHEDULER_ENABLED",
            )
        )
    ):
        raise RuntimeError(
            "Local setup requires the isolated testing Compose environment"
        )


def load_models():
    # Standalone execution must register every relationship, including Vehicle.
    from app.models import all_models  # noqa: F401
    from sqlalchemy.orm import configure_mappers

    configure_mappers()


async def seed(instance_id, password):
    load_models()
    from datetime import datetime, timezone
    from sqlalchemy import func, select, text
    from app.core.database import AsyncSessionLocal, engine
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    from app.models.rider import Rider, RiderStatus, VehicleType
    from app.models.zone import Zone
    from app.models.order import Order, OrderStatus
    from app.models.platform_setting import PlatformSetting

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS local_test_instance (id TEXT PRIMARY KEY, created_at TIMESTAMP NOT NULL)"
                )
            )
            previous = (
                (await db.execute(text("SELECT id FROM local_test_instance")))
                .scalars()
                .all()
            )
            if previous:
                if previous != [instance_id]:
                    raise RuntimeError(
                        "The database belongs to a different local-test instance"
                    )
                print(
                    "Local test data already initialized; accounts, passwords and edits preserved"
                )
                return
            if await db.scalar(select(func.count()).select_from(User)):
                raise RuntimeError(
                    "Initialization refused: this database already contains accounts"
                )
            users = {}
            for role, login in (
                (UserRole.SUPERADMIN, "admin"),
                (UserRole.GERENTE, "gerente"),
                (UserRole.OPERADOR, "operador"),
                (UserRole.REPARTIDOR, "repartidor"),
                (UserRole.AUDITOR, "auditor"),
                (UserRole.CLIENTE, "cliente"),
            ):
                user = User(
                    email=login + ".local-test@example.com",
                    hashed_password=hash_password(password),
                    first_name="Prueba",
                    last_name=role.value,
                    role=role,
                    is_active=True,
                    is_superuser=role == UserRole.SUPERADMIN,
                )
                db.add(user)
                users[role] = user
            await db.flush()
            zone = Zone(
                name="Zona de pruebas",
                code="LOCAL-TEST",
                description="Datos sintéticos del laboratorio local",
                delivery_fee_base=2,
                cost_per_km=0,
                estimated_time_min=30,
                is_active=True,
                color_hex="#2563eb",
                center_lat=10.4806,
                center_lng=-66.9036,
            )
            db.add(zone)
            await db.flush()
            rider = Rider(
                user_id=users[UserRole.REPARTIDOR].id,
                zone_id=zone.id,
                operating_zone=zone.name,
                vehicle_type=VehicleType.MOTO,
                status=RiderStatus.ACTIVO,
                is_online=False,
                vehicle_plate="PRUEBA-01",
                vehicle_model="Solo laboratorio",
                wallet_balance=0,
                pending_balance=0,
            )
            db.add(rider)
            values = {
                "delivery_fee_base": 2,
                "commission_percentage": 10,
                "min_order_amount": 0,
                "active_zones": [zone.name],
                "support_email": "soporte.local-test@example.com",
                "maintenance_mode": False,
                "rider_delivery_bonus": 2.5,
                "rider_failed_attempt_bonus": 1,
            }
            for key, value in values.items():
                row = await db.get(PlatformSetting, key)
                if row is None:
                    row = PlatformSetting(key=key, value=value)
                    db.add(row)
                row.value = value
                row.updated_by_user_id = users[UserRole.SUPERADMIN].id
                row.updated_at = now
            for index in range(1, 4):
                db.add(
                    Order(
                        external_id=f"LOCAL-TEST-{index:03d}",
                        customer_name=f"Cliente de prueba {index}",
                        customer_phone="+584120000000",
                        pickup_address="Origen de laboratorio",
                        delivery_address=f"Destino de laboratorio {index}",
                        items=[
                            {"name": "Producto sintético", "quantity": 1, "price": 10}
                        ],
                        subtotal=10,
                        delivery_fee=2,
                        total=12,
                        status=OrderStatus.PENDIENTE,
                        source="local-test",
                    )
                )
            await db.execute(
                text("INSERT INTO local_test_instance VALUES (:id,:created)"),
                {"id": instance_id, "created": now},
            )
            await db.commit()
            print(
                "Local test initialized: six roles, one offline rider, one zone and three pending orders; no payments or external messages"
            )
    finally:
        await engine.dispose()


def main():
    validate_environment(os.environ)
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )
    asyncio.run(seed(os.environ["LOCAL_TEST_ID"], os.environ["LOCAL_TEST_PASSWORD"]))


if __name__ == "__main__":
    main()

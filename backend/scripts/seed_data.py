import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
import random
import uuid
from decimal import Decimal
import math

# Ajusta el path según tu estructura real
sys.path.insert(0, "/app")

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, select, update
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus, VehicleType as RiderVehicleType
from app.models.vehicle import Vehicle, VehicleType, VehicleStatus # Importamos el nuevo modelo y enums
from app.models.zone import Zone
from app.models.order import Order, OrderStatus, OrderPriority
from app.models.delivery import Delivery, DeliveryStatus, ProofType
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.payout import Payout, PayoutStatus, PayoutMethod, PayoutStatusHistory
from app.models.audit_log import AuditLog, ActionType
from app.models.platform_setting import PlatformSetting
from app.services.financial_service import FinancialService, money
from app.models.productivity import ProductivityRecord, MetricType
from app.models.notification import Notification, NotificationType, NotificationPriority 
from app.models.route import Route, RoutePoint, RouteStatus

# Configuración DB
DATABASE_URL = str(settings.DATABASE_URL).replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# ==========================================
# DATOS MAESTROS REALISTAS
# ==========================================

RESTAURANTS = [
    {"name": "Burger King Zona G", "address": "Cra 4 #85-10, Chapinero", "lat": 4.668, "lng": -74.050},
    {"name": "Pizza Hut Parque 93", "address": "Cll 93B #13-30", "lat": 4.676, "lng": -74.047},
    {"name": "Saludpan Farmacia", "address": "Av 19 #11-40, Centro", "lat": 4.600, "lng": -74.075},
    {"name": "Sushi Master Usaquén", "address": "Cra 6 #119-60", "lat": 4.695, "lng": -74.030},
    {"name": "La Hamburguesa del Sur", "address": "Cll 42 Sur #20-10", "lat": 4.570, "lng": -74.120},
]

MENUS = {
    "BURGER": [
        {"name": "Whopper Doble", "price": 28000},
        {"name": "Papas Grandes", "price": 8000},
        {"name": "Coca-Cola 1.5L", "price": 6000},
    ],
    "PIZZA": [
        {"name": "Pizza Pepperoni Familiar", "price": 45000},
        {"name": "Pizza Hawaiana Mediana", "price": 32000},
        {"name": "Gaseosa 2L", "price": 7000},
    ],
    "SUSHI": [
        {"name": "Rol California x12", "price": 35000},
        {"name": "Spicy Tuna Roll", "price": 22000},
    ],
    "PHARMA": [
        {"name": "Acetaminofén MK", "price": 12000},
        {"name": "Suero Oral", "price": 15000},
    ]
}

CUSTOMER_NAMES = [
    "Juan Pérez", "María Rodríguez", "Carlos López", "Ana Gómez", "Luis Martínez",
    "Sofía Hernández", "Jorge Díaz", "Camila Torres", "Andrés Ramírez", "Valentina Cruz"
]

STREETS = ["Calle", "Carrera", "Av", "Diagonal", "Transversal"]
NEIGHBORHOODS = ["Chapinero", "Usaquén", "Suba", "Kennedy", "Engativá", "Teusaquillo"]

def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_random_location_near(base_lat: float, base_lng: float, radius_km: float = 2.0):
    lat_offset = radius_km / 111.0
    lng_offset = radius_km / (111.0 * math.cos(math.radians(base_lat)))
    return (
        base_lat + random.uniform(-lat_offset, lat_offset),
        base_lng + random.uniform(-lng_offset, lng_offset)
    )

def generate_realistic_items() -> Tuple[List[dict], int]:
    menu_type = random.choice(list(MENUS.keys()))
    items_count = random.randint(1, 4)
    selected_items = random.sample(MENUS[menu_type], min(items_count, len(MENUS[menu_type])))
    
    order_items = []
    subtotal = 0
    for item in selected_items:
        qty = random.randint(1, 3)
        total_line = item["price"] * qty
        order_items.append({
            "product_name": item["name"],
            "quantity": qty,
            "unit_price": item["price"],
            "subtotal": total_line,
            "category": menu_type
        })
        subtotal += total_line
        
    return order_items, subtotal

# ==========================================
# FUNCIONES DE SEMILLA
# ==========================================

async def seed_users(db: AsyncSession, count: int = 10) -> List[User]:
    print(f"👥 Sembrando usuarios...")
    users = []
    
    admins = [
        {"email": "super@delivery360.com", "role": UserRole.SUPERADMIN, "name": "Super Admin"},
        {"email": "gerente@delivery360.com", "role": UserRole.GERENTE, "name": "Gerente General"},
        {"email": "ops@delivery360.com", "role": UserRole.OPERADOR, "name": "Operador Logística"},
    ]
    
    for admin in admins:
        exists = await db.execute(select(User).where(User.email == admin["email"]))
        if not exists.scalar_one_or_none():
            user = User(
                id=uuid.uuid4(),
                email=admin["email"],
                hashed_password=get_password_hash("Admin123!"),
                first_name=admin["name"].split()[0],
                last_name=admin["name"].split()[1] if len(admin["name"].split()) > 1 else "",
                role=admin["role"],
                is_active=True,
                is_superuser=(admin["role"] == UserRole.SUPERADMIN),
                phone=f"+57300{random.randint(1000000, 9999999)}"
            )
            db.add(user)
            users.append(user)
            
    await db.commit()
    print(f"   ✅ {len(users)} usuarios creados.")
    return users

async def seed_zones(db: AsyncSession) -> List[Zone]:
    """Seed real operating zones used by fleet and order dashboards."""
    print("🗺️ Sembrando zonas operativas...")
    zone_defs = [
        {
            "name": "Norte",
            "code": "NRT",
            "description": "Zona norte y Chapinero alto.",
            "delivery_fee_base": 4500,
            "cost_per_km": 900,
            "estimated_time_min": 35,
            "is_priority": True,
            "color_hex": "#3b82f6",
            "center_lat": 4.676,
            "center_lng": -74.047,
        },
        {
            "name": "Centro",
            "code": "CTR",
            "description": "Centro ampliado y zonas de alta rotación.",
            "delivery_fee_base": 4000,
            "cost_per_km": 850,
            "estimated_time_min": 30,
            "is_priority": False,
            "color_hex": "#22c55e",
            "center_lat": 4.600,
            "center_lng": -74.075,
        },
        {
            "name": "Sur",
            "code": "SUR",
            "description": "Operación sur y periferia cercana.",
            "delivery_fee_base": 5000,
            "cost_per_km": 1000,
            "estimated_time_min": 45,
            "is_priority": False,
            "color_hex": "#f97316",
            "center_lat": 4.570,
            "center_lng": -74.110,
        },
        {
            "name": "Zona G",
            "code": "ZNG",
            "description": "Restaurantes premium Zona G y alrededores.",
            "delivery_fee_base": 5500,
            "cost_per_km": 1100,
            "estimated_time_min": 25,
            "is_priority": True,
            "color_hex": "#a855f7",
            "center_lat": 4.668,
            "center_lng": -74.050,
        },
    ]

    zones: List[Zone] = []
    created = 0
    for data in zone_defs:
        existing = await db.execute(select(Zone).where(Zone.code == data["code"]))
        zone = existing.scalar_one_or_none()
        if not zone:
            zone = Zone(id=uuid.uuid4(), is_active=True, **data)
            db.add(zone)
            created += 1
        zones.append(zone)

    await db.commit()
    print(f"   ✅ {created} zonas creadas / {len(zones)} zonas disponibles.")
    return zones


async def seed_platform_settings(db: AsyncSession, zones: List[Zone]):
    """Seed persisted platform settings used by the admin settings module."""
    print("⚙️ Sembrando configuración global de plataforma...")

    admin_result = await db.execute(
        select(User).where(User.role.in_([UserRole.SUPERADMIN, UserRole.GERENTE])).order_by(User.created_at.asc())
    )
    admin_user = admin_result.scalars().first()
    active_zone_names = [zone.name for zone in zones if getattr(zone, "is_active", True)] or ["Norte", "Sur", "Centro"]

    setting_defs = {
        "delivery_fee_base": {
            "value": 5000,
            "description": "Tarifa base de envío usada para pruebas operativas.",
        },
        "commission_percentage": {
            "value": 15,
            "description": "Comisión de plataforma usada para reportes demo.",
        },
        "min_order_amount": {
            "value": 10000,
            "description": "Pedido mínimo habilitado para flujos de prueba.",
        },
        "active_zones": {
            "value": active_zone_names,
            "description": "Zonas activas precargadas desde seed_data.",
        },
        "support_email": {
            "value": "soporte@delivery360.com",
            "description": "Correo de soporte visible en configuración.",
        },
        "maintenance_mode": {
            "value": False,
            "description": "Modo mantenimiento inicial desactivado.",
        },
    }

    created = 0
    updated_descriptions = 0
    now = utc_now_naive()
    for key, data in setting_defs.items():
        result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
        setting = result.scalar_one_or_none()
        if not setting:
            db.add(
                PlatformSetting(
                    key=key,
                    value=data["value"],
                    description=data["description"],
                    updated_by_user_id=admin_user.id if admin_user else None,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
        elif not setting.description:
            setting.description = data["description"]
            updated_descriptions += 1

    await db.commit()
    print(f"   ✅ {created} configuraciones creadas / {updated_descriptions} descripciones actualizadas.")


async def seed_riders(db: AsyncSession, zones: List[Zone], count: int = 15) -> List[Rider]:
    print(f"🛵 Sembrando repartidores...")
    riders = []
    # Usamos los valores string directamente para evitar conflictos de enums entre modelos
    vehicle_types = ["MOTO", "MOTO", "BICICLETA", "AUTO"] 
    fallback_zone_points = [(4.668, -74.050), (4.676, -74.047), (4.600, -74.075), (4.695, -74.030)]

    for i in range(count):
        email = f"rider{i+1}@delivery360.com"
        exists_user = await db.execute(select(User).where(User.email == email))
        user = exists_user.scalar_one_or_none()
        
        if not user:
            user = User(
                id=uuid.uuid4(),
                email=email,
                hashed_password=get_password_hash("Rider123!"),
                first_name="Repartidor",
                last_name=f"{i+1}",
                role=UserRole.REPARTIDOR,
                is_active=True,
                phone=f"+573{random.randint(100000000, 999999999)}"
            )
            db.add(user)
            await db.flush()
            
        exists_rider = await db.execute(select(Rider).where(Rider.user_id == user.id))
        rider = exists_rider.scalar_one_or_none()
        
        if not rider:
            selected_zone = random.choice(zones) if zones else None
            fallback_lat, fallback_lng = random.choice(fallback_zone_points)
            base_lat = selected_zone.center_lat if selected_zone and selected_zone.center_lat else fallback_lat
            base_lng = selected_zone.center_lng if selected_zone and selected_zone.center_lng else fallback_lng
            lat, lng = get_random_location_near(base_lat, base_lng, 1.0)
            status = random.choices(["ACTIVO", "INACTIVO", "OCUPADO"], weights=[80, 10, 10])[0]
            
            rider = Rider(
                id=uuid.uuid4(),
                user_id=user.id,
                vehicle_type=random.choice(vehicle_types),
                vehicle_plate=f"{random.choice(['ABC', 'XYZ'])}-{random.randint(100, 999)}",
                vehicle_model=f"Yamaha NMAX {random.randint(2020, 2024)}",
                operating_zone=selected_zone.name if selected_zone else random.choice(["Norte", "Centro", "Sur"]),
                zone_id=selected_zone.id if selected_zone else None,
                cpf=str(random.randint(1000000000, 9999999999)),
                cnh=f"LIC{random.randint(100000, 999999)}",
                status=status,
                is_online=(status == "ACTIVO"),
                last_lat=lat,
                last_lng=lng,
                last_location_at=utc_now_naive(),
                level=random.randint(1, 10),
                wallet_balance=Decimal(str(round(random.uniform(10, 100), 2))),
            )
            db.add(rider)
            riders.append(rider)
            
    await db.commit()
    print(f"   ✅ {len(riders)} repartidores listos.")
    return riders

async def seed_vehicles(db: AsyncSession, users: List[User], riders: List[Rider], count: int = 20):
    """
    Genera una flota de vehículos.
    - Algunos se asignan a los riders existentes (vinculando rider_id/user_id).
    - Otros quedan disponibles (rider_id NULL) para pruebas de asignación manual.
    """
    print(f"🚗 Sembrando flota de vehículos...")
    vehicles_created = 0
    
    # Tipos y estados disponibles
    v_types = ["MOTO", "AUTO", "FURGONETA", "BICICLETA"]
    v_statuses = ["ACTIVO", "ACTIVO", "ACTIVO", "MANTENIMIENTO", "BAJA"] # Mayor probabilidad de ACTIVO
    
    # 1. Crear vehículos para los riders existentes (simulando que su vehículo está en la flota formal)
    for rider in riders:
        # Obtenemos el usuario dueño del rider. Si no está en la lista local,
        # lo consultamos en BD porque seed_users solo retorna usuarios recién creados.
        user = next((u for u in users if u.id == rider.user_id), None)
        if not user:
            user = await db.get(User, rider.user_id)
        if not user:
            continue
            
        # Verificar si ya existe un vehículo con esa placa (por seguridad)
        existing = await db.execute(select(Vehicle).where(Vehicle.plate == rider.vehicle_plate))
        if existing.scalar_one_or_none():
            continue

        vehicle = Vehicle(
            id=uuid.uuid4(),
            rider_id=user.id, # Vinculado al dueño (usuario)
            plate=rider.vehicle_plate,
            type=rider.vehicle_type, # Usa el tipo del rider
            model=rider.vehicle_model or f"Vehículo {rider.vehicle_type}",
            color=random.choice(["Rojo", "Azul", "Negro", "Blanco", "Gris"]),
            year=random.randint(2018, 2024),
            status="ACTIVO",
            insurance_expiry=datetime.now().date() + timedelta(days=random.randint(30, 300)),
            notes=f"Asignado inicialmente al rider {rider.id}"
        )
        db.add(vehicle)
        vehicles_created += 1

    # 2. Crear vehículos adicionales "huérfanos" o de reserva para la flota
    extra_count = max(0, count - vehicles_created)
    for i in range(extra_count):
        v_type = random.choice(v_types)
        plate = f"{random.choice(['AAA', 'BBB', 'CCC', 'DDD'])}-{random.randint(100, 999)}"
        
        # Verificar duplicados de placa
        existing = await db.execute(select(Vehicle).where(Vehicle.plate == plate))
        if existing.scalar_one_or_none():
            continue

        vehicle = Vehicle(
            id=uuid.uuid4(),
            rider_id=None, # Disponible para asignar
            plate=plate,
            type=v_type,
            model=f"Modelo Genérico {v_type} {i+1}",
            color=random.choice(["Amarillo", "Verde", "Plateado", "Naranja"]),
            year=random.randint(2015, 2023),
            status=random.choice(v_statuses),
            insurance_expiry=datetime.now().date() + timedelta(days=random.randint(-10, 200)), # Algunos vencidos
            notes="Vehículo de reserva o flotilla propia."
        )
        db.add(vehicle)
        vehicles_created += 1

    await db.commit()
    print(f"   ✅ {vehicles_created} vehículos registrados en la flota.")

async def seed_orders_and_complex_data(db: AsyncSession, riders: List[Rider], count: int = 50):
    print(f"📦 Generando órdenes, entregas y rutas...")
    
    active_riders = [r for r in riders if r.status == "ACTIVO"]
    
    if not active_riders:
        result = await db.execute(select(Rider).where(Rider.status == "ACTIVO"))
        active_riders = list(result.scalars().all())
        if not active_riders:
            print("   ⚠️ No hay riders activos disponibles para asignar órdenes.")
            return []

    now = utc_now_naive()
    from collections import defaultdict
    rider_stats = defaultdict(lambda: {"completed": 0, "total_time": 0, "earnings": Decimal(0)})
    
    for r in riders:
        rider_stats[r.id] = {"completed": 0, "total_time": 0, "earnings": Decimal(0)}

    orders = []

    for i in range(count):
        restaurant = random.choice(RESTAURANTS)
        pick_lat, pick_lng = get_random_location_near(restaurant["lat"], restaurant["lng"], 0.5)
        del_lat, del_lng = get_random_location_near(restaurant["lat"], restaurant["lng"], random.uniform(2, 8))
        
        items, subtotal = generate_realistic_items()
        delivery_fee = random.choice([4000, 5000, 6000, 7500])
        total = subtotal + delivery_fee
        
        status = random.choices(
            ["PENDIENTE", "ASIGNADO", "EN_RUTA", "ENTREGADO", "CANCELADO"],
            weights=[10, 15, 15, 55, 5]
        )[0]
        
        assigned_rider = None
        if status != "PENDIENTE" and active_riders:
            assigned_rider = random.choice(active_riders)
            if assigned_rider.id not in rider_stats:
                rider_stats[assigned_rider.id] = {"completed": 0, "total_time": 0, "earnings": Decimal(0)}

        hours_ago = random.randint(1, 48)
        ordered_at = now - timedelta(hours=hours_ago)
        accepted_at = ordered_at + timedelta(minutes=random.randint(2, 10)) if status != "PENDIENTE" else None
        
        picked_up_at = None
        delivered_at = None
        if status in ["EN_RUTA", "ENTREGADO"]:
            picked_up_at = accepted_at + timedelta(minutes=random.randint(10, 25))
        
        if status == "ENTREGADO":
            delivered_at = picked_up_at + timedelta(minutes=random.randint(15, 45))
            if assigned_rider:
                duration = (delivered_at - ordered_at).total_seconds() / 60
                rider_stats[assigned_rider.id]["completed"] += 1
                rider_stats[assigned_rider.id]["total_time"] += duration
                rider_stats[assigned_rider.id]["earnings"] += Decimal(str(delivery_fee * 0.7))

        order = Order(
            id=uuid.uuid4(),
            external_id=f"ORD-{2024000 + i}",
            customer_name=random.choice(CUSTOMER_NAMES),
            customer_phone=f"+573{random.randint(100000000, 999999999)}",
            pickup_address=f"{restaurant['address']}",
            pickup_latitude=pick_lat,
            pickup_longitude=pick_lng,
            delivery_address=f"{random.choice(STREETS)} {random.randint(1, 100)}, {random.choice(NEIGHBORHOODS)}",
            delivery_latitude=del_lat,
            delivery_longitude=del_lng,
            items=items,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            total=total,
            payment_method=random.choice(["EFECTIVO", "TARJETA"]),
            payment_status="PAGADO",
            status=status,
            priority=random.choice(["NORMAL"] * 8 + ["URGENTE"] * 2),
            assigned_rider_id=assigned_rider.id if assigned_rider else None,
            ordered_at=ordered_at,
            accepted_at=accepted_at,
            picked_up_at=picked_up_at,
            delivered_at=delivered_at,
            sla_deadline=ordered_at + timedelta(minutes=60),
        )
        
        if status == "CANCELADO":
            order.cancellation_reason = "Cliente no esperaba el pedido"
            order.cancelled_by = "CLIENTE"
            
        db.add(order)
        orders.append(order)
        
        if assigned_rider and status != "PENDIENTE" and status != "CANCELADO":
            d_status_map = {
                "ASIGNADO": "PENDIENTE",
                "EN_RUTA": "EN_ROUTE",
                "ENTREGADO": "COMPLETADA",
            }
            
            delivery = Delivery(
                id=uuid.uuid4(),
                order_id=order.id,
                rider_id=assigned_rider.id,
                status=d_status_map.get(status, "PENDIENTE"),
                started_at=accepted_at,
                completed_at=delivered_at,
                distance_total=random.uniform(3.5, 12.0),
                sla_expected_minutes=60,
                sla_actual_minutes=int((delivered_at - ordered_at).total_seconds()/60) if delivered_at else None,
                sla_compliant=(delivered_at < order.sla_deadline) if delivered_at else None
            )
            db.add(delivery)

    await db.commit()
    print(f"   ✅ {len(orders)} órdenes y entregas generadas.")

    active_orders = [o for o in orders if o.status in ["ASIGNADO", "EN_RUTA"]]
    for order in active_orders:
        if order.assigned_rider_id:
            stmt = update(Rider).where(Rider.id == order.assigned_rider_id).values(current_order_id=order.id)
            await db.execute(stmt)
    await db.commit()

    all_rider_ids = set(rider_stats.keys())
    result = await db.execute(select(Rider).where(Rider.id.in_(list(all_rider_ids))))
    db_riders = {r.id: r for r in result.scalars().all()}

    for r_id, stats in rider_stats.items():
        if stats["completed"] > 0:
            record = ProductivityRecord(
                id=uuid.uuid4(),
                rider_id=r_id,
                metric_type="ENTREGAS_TOTAL",
                value=float(stats["completed"]),
                date=now.date(),
            )
            db.add(record)
            
            if stats["earnings"] > 0:
                idempotency_key = f"seed-earnings-{now.date()}-{r_id}"
                existing_txn = await db.execute(select(Financial).where(Financial.idempotency_key == idempotency_key))
                existing_txn = existing_txn.scalar_one_or_none()

                if existing_txn:
                    if r_id in db_riders:
                        db_riders[r_id].wallet_balance = existing_txn.balance_after
                else:
                    txn = await FinancialService(db).create_ledger_entry(
                        rider_id=r_id,
                        transaction_type=TransactionType.PAGO_ENTREGA,
                        amount=stats["earnings"],
                        status=PaymentStatus.PROCESADO,
                        description=f"Saldo del día ({stats['completed']} entregas)",
                        source_type="SEED_ORDER_BATCH",
                        source_id=str(now.date()),
                        idempotency_key=idempotency_key,
                        commit=False,
                    )

                    if r_id in db_riders:
                        db_riders[r_id].wallet_balance = txn.balance_after
                
    await db.commit()
    print("   ✅ Productividad y finanzas actualizadas con ledger trazable.")
    
    return orders


async def seed_demo_payouts(db: AsyncSession, riders: List[Rider]):
    """Seed payout requests with status history for manager/rider finance demos."""
    print("💸 Sembrando retiros demo con historial...")

    admin_result = await db.execute(select(User).where(User.role == UserRole.SUPERADMIN))
    admin_user = admin_result.scalar_one_or_none()
    if not admin_user:
        print("   ⚠️ No hay superadmin para trazar retiros demo.")
        return

    candidates = [rider for rider in riders if money(getattr(rider, "wallet_balance", 0)) > Decimal("20.00")]
    if not candidates:
        result = await db.execute(select(Rider).where(Rider.wallet_balance > 20).limit(5))
        candidates = list(result.scalars().all())

    statuses = [PayoutStatus.PENDIENTE, PayoutStatus.PROCESADO, PayoutStatus.RECHAZADO]
    created = 0
    now = utc_now_naive()

    for index, rider in enumerate(candidates[:6]):
        status_value = statuses[index % len(statuses)]
        idempotency_key = f"seed-payout-{status_value.value.lower()}-{rider.id}"
        existing = await db.execute(select(Payout).where(Payout.idempotency_key == idempotency_key))
        if existing.scalar_one_or_none():
            continue

        current_balance = money(getattr(rider, "wallet_balance", 0))
        if current_balance <= Decimal("20.00"):
            continue

        amount = min(Decimal("30000.00"), max(Decimal("10.00"), money(current_balance * Decimal("0.30"))))
        balance_after = current_balance - amount if status_value in [PayoutStatus.PENDIENTE, PayoutStatus.PROCESADO] else current_balance
        payout_id = uuid.uuid4()
        requested_at = now - timedelta(hours=8 + index)
        processed_at = requested_at + timedelta(hours=2) if status_value != PayoutStatus.PENDIENTE else None

        payout = Payout(
            id=payout_id,
            rider_id=rider.id,
            amount=amount,
            status=status_value,
            method=random.choice([PayoutMethod.TRANSFERENCIA, PayoutMethod.BILLETERA_DIGITAL]),
            bank_account_last4=str(random.randint(1000, 9999)),
            reference_code=f"SEED-PAY-{str(payout_id)[:8].upper()}" if status_value == PayoutStatus.PROCESADO else None,
            rejection_reason="Datos bancarios pendientes de validación" if status_value == PayoutStatus.RECHAZADO else None,
            idempotency_key=idempotency_key,
            balance_before=current_balance,
            balance_after=balance_after,
            requested_by_user_id=rider.user_id,
            processed_by_user_id=admin_user.id if status_value != PayoutStatus.PENDIENTE else None,
            requested_at=requested_at,
            processed_at=processed_at,
            updated_at=processed_at or requested_at,
        )
        db.add(payout)
        db.add(
            PayoutStatusHistory(
                payout_id=payout_id,
                old_status=None,
                new_status=PayoutStatus.PENDIENTE.value,
                reason="Solicitud demo creada desde seed_data",
                changed_by_user_id=rider.user_id,
                balance_before=current_balance,
                balance_after=current_balance - amount,
                created_at=requested_at,
            )
        )

        if status_value == PayoutStatus.PROCESADO:
            db.add(
                PayoutStatusHistory(
                    payout_id=payout_id,
                    old_status=PayoutStatus.PENDIENTE.value,
                    new_status=PayoutStatus.PROCESADO.value,
                    reason="Retiro demo aprobado",
                    changed_by_user_id=admin_user.id,
                    balance_before=current_balance,
                    balance_after=balance_after,
                    created_at=processed_at,
                )
            )
            await FinancialService(db).create_ledger_entry(
                rider_id=rider.id,
                amount=amount,
                balance_before=current_balance,
                transaction_type=TransactionType.RETIRO,
                status=PaymentStatus.PROCESADO,
                description=f"Retiro demo aprobado: {payout.reference_code}",
                reference_id=str(payout_id),
                source_type="PAYOUT",
                source_id=str(payout_id),
                idempotency_key=f"seed-payout-ledger-{payout_id}",
                created_by_user_id=admin_user.id,
                commit=False,
            )
            rider.wallet_balance = balance_after
        elif status_value == PayoutStatus.RECHAZADO:
            db.add(
                PayoutStatusHistory(
                    payout_id=payout_id,
                    old_status=PayoutStatus.PENDIENTE.value,
                    new_status=PayoutStatus.RECHAZADO.value,
                    reason=payout.rejection_reason,
                    changed_by_user_id=admin_user.id,
                    balance_before=current_balance - amount,
                    balance_after=current_balance,
                    created_at=processed_at,
                )
            )

        created += 1

    await db.commit()
    print(f"   ✅ {created} retiros demo creados con historial.")


async def seed_audit_logs(db: AsyncSession):
    """Seed representative audit events for the admin audit module."""
    print("🧾 Sembrando eventos de auditoría demo...")

    existing = await db.execute(select(AuditLog).where(AuditLog.resource_id == "demo-audit-v1"))
    if existing.scalar_one_or_none():
        print("   ℹ️ Auditoría demo ya existe; se omite duplicación.")
        return

    user_result = await db.execute(
        select(User).where(User.role.in_([UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR])).limit(3)
    )
    actors = list(user_result.scalars().all())
    if not actors:
        print("   ⚠️ No hay usuarios administrativos para auditoría demo.")
        return

    now = utc_now_naive()
    templates = [
        (ActionType.LOGIN, "Auth", "login", "Inicio de sesión administrativo", True, None, "/api/v1/auth/login"),
        (ActionType.CONFIG_CHANGE, "PlatformSettings", "global", "Actualización de configuración global", True, "delivery_fee_base, active_zones", "/api/v1/settings"),
        (ActionType.CREATE, "User", "demo-rider", "Creación de usuario repartidor demo", True, None, "/api/v1/users"),
        (ActionType.UPDATE, "Zone", "NRT", "Actualización de zona operativa Norte", True, "delivery_fee_base", "/api/v1/zones/NRT"),
        (ActionType.PAYMENT, "Payout", "demo-payout", "Aprobación de retiro demo", True, "status", "/api/v1/payouts/demo/approve"),
        (ActionType.EXPORT, "AuditLog", "csv", "Exportación de auditoría demo", True, None, "/api/v1/audit/export"),
        (ActionType.ACCESS_DENIED, "Settings", "global", "Intento de cambio de configuración sin permisos", False, None, "/api/v1/settings"),
    ]

    for idx, (action, resource_type, resource_id, description, success, summary, path) in enumerate(templates):
        actor = actors[idx % len(actors)]
        db.add(
            AuditLog(
                user_id=actor.id,
                user_email=actor.email,
                user_role=actor.role.value if hasattr(actor.role, "value") else str(actor.role),
                action_type=action,
                resource_type=resource_type,
                resource_id="demo-audit-v1" if idx == 0 else resource_id,
                description=description,
                old_values={"seed": False} if action in [ActionType.CONFIG_CHANGE, ActionType.UPDATE] else None,
                new_values={"seed": True} if action in [ActionType.CONFIG_CHANGE, ActionType.UPDATE] else None,
                changes_summary=summary,
                ip_address=f"10.0.0.{idx + 10}",
                user_agent="Delivery360 SeedData/1.0",
                request_method="POST" if action in [ActionType.CREATE, ActionType.PAYMENT, ActionType.LOGIN] else "GET",
                request_path=path,
                status_code=200 if success else 403,
                success=success,
                error_message=None if success else "Permisos insuficientes para modificar configuración",
                contains_personal_data=resource_type == "User",
                created_at=now - timedelta(minutes=idx * 17),
            )
        )

    await db.commit()
    print(f"   ✅ {len(templates)} eventos de auditoría demo creados.")


async def seed_alerts(db: AsyncSession, orders: List[Order], riders: List[Rider]):
    print(f"🔔 Generando alertas operacionales basadas en datos reales...")
    
    result = await db.execute(select(User).where(User.is_superuser == True))
    admins = result.scalars().all()
    
    if not admins:
        print("   ⚠️ No hay administradores para asignar alertas.")
        return

    target_user = admins[0]
    now = utc_now_naive()
    alerts_to_create = []

    cancelled_orders = [o for o in orders if o.status == "CANCELADO"]
    for order in cancelled_orders[:3]:
        alerts_to_create.append({
            "type": "ALERTA_OPERACIONAL",
            "priority": "ALTA",
            "title": f"Orden Cancelada: {order.external_id}",
            "message": f"La orden de {order.customer_name} fue cancelada. Razón: {order.cancellation_reason}",
            "data": {"alert_type": "FAILURE", "severity": "high", "related_order_id": order.external_id},
            "is_read": False,
            "created_at": now - timedelta(minutes=random.randint(10, 60))
        })

    late_deliveries = [o for o in orders if o.delivered_at and o.sla_deadline and o.delivered_at > o.sla_deadline]
    for order in late_deliveries[:3]:
        alerts_to_create.append({
            "type": "ALERTA_OPERACIONAL",
            "priority": "CRITICA",
            "title": f"Retraso SLA Detectado: {order.external_id}",
            "message": f"La entrega superó el tiempo estimado en {int((order.delivered_at - order.sla_deadline).total_seconds()/60)} minutos.",
            "data": {"alert_type": "DELAY", "severity": "critical", "related_order_id": order.external_id},
            "is_read": False,
            "created_at": now - timedelta(minutes=random.randint(5, 30))
        })

    inactive_riders = [r for r in riders if r.status == "INACTIVO"]
    if inactive_riders:
        alerts_to_create.append({
            "type": "ALERTA_OPERACIONAL",
            "priority": "NORMAL",
            "title": "Riders Inactivos",
            "message": f"Hay {len(inactive_riders)} repartidores inactivos en este momento.",
            "data": {"alert_type": "RIDER", "severity": "medium"},
            "is_read": True,
            "created_at": now - timedelta(hours=2)
        })

    alerts_to_create.append({
        "type": "ALERTA_OPERACIONAL",
        "priority": "BAJA",
        "title": "Mantenimiento Programado",
        "message": "Se realizará mantenimiento en los servidores este domingo a las 3 AM.",
        "data": {"alert_type": "SYSTEM", "severity": "low"},
        "is_read": True,
        "created_at": now - timedelta(hours=24)
    })

    notifications = []
    for alert_data in alerts_to_create:
        n = Notification(
            user_id=target_user.id,
            notification_type=alert_data["type"],
            priority=alert_data["priority"],
            title=alert_data["title"],
            message=alert_data["message"],
            data=alert_data["data"],
            is_read=alert_data["is_read"],
            created_at=alert_data["created_at"]
        )
        notifications.append(n)
        db.add(n)

    await db.commit()
    print(f"   ✅ {len(notifications)} alertas generadas y vinculadas a eventos reales.")

# ==========================================
# MAIN
# ==========================================

async def main():
    print("🚀 INICIANDO SEED DATA AVANZADO (CON ZONAS, VEHÍCULOS Y ALERTAS)")
    async with AsyncSessionLocal() as db:
        try:
            users = await seed_users(db)
            zones = await seed_zones(db)
            await seed_platform_settings(db, zones)
            riders = await seed_riders(db, zones)
            
            # NUEVO: Sembrar vehículos después de tener usuarios y riders
            await seed_vehicles(db, users, riders, count=25)
            
            orders = await seed_orders_and_complex_data(db, riders, count=60)
            await seed_demo_payouts(db, riders)
            await seed_alerts(db, orders, riders)
            await seed_audit_logs(db)
            
            print("\n✅ ¡SEED COMPLETADO CON ÉXITO!")
            print("\n🔐 CREDENCIALES:")
            print("   Superadmin: super@delivery360.com / Admin123!")
            print("\n💡 DATOS GENERADOS:")
            print("   - Usuarios, Zonas, Riders, Vehículos (Flota)")
            print("   - Órdenes, Entregas, Finanzas, Productividad")
            print("   - Alertas Operacionales Reales")
            print("   - Configuración global, retiros e historial/auditoría demo")
            
        except Exception as e:
            await db.rollback()
            print(f"\n❌ ERROR CRÍTICO: {e}")
            import traceback
            traceback.print_exc()
            raise
        finally:
            await db.close()

if __name__ == "__main__":
    asyncio.run(main())
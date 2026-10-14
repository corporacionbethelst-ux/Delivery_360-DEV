import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone, time
from typing import List, Optional, Tuple
import random
import uuid
from decimal import Decimal
import math

# Ajusta el path según tu estructura real
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../backend (funciona con /app en Docker y rutas locales)
for _p in ("/app", _BACKEND_ROOT):
    if _p not in sys.path and os.path.isdir(_p):
        sys.path.insert(0, _p)

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, select, update, delete
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus, VehicleType as RiderVehicleType, RiderTier
from app.models.vehicle import Vehicle, VehicleType, VehicleStatus # Importamos el nuevo modelo y enums
from app.models.enums import VehicleOwnershipType
from app.models.zone import Zone
from app.models.order import Order, OrderStatus, OrderPriority
from app.models.delivery import Delivery, DeliveryStatus, ProofType
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.models.financial import Financial, TransactionType, PaymentStatus, RiderWallet, FinancialTransaction, TransactionStatus as FinTransactionStatus
from app.models.payout import Payout, PayoutStatus, PayoutMethod, PayoutStatusHistory
from app.models.location import RiderLiveLocation, DeliveryRouteSnapshot
from app.models.financial import PayoutRequest, PayoutStatus as PayoutRequestStatus
from app.models.audit_log import AuditLog, ActionType
from app.models.platform_setting import PlatformSetting
from app.services.financial_service import FinancialService, money
from app.models.productivity import ProductivityRecord, MetricType
from app.models.notification import Notification, NotificationType, NotificationPriority
from app.models.fiscal import CountryTaxRegime 
from app.models.route import Route, RoutePoint, RouteStatus
from app.models.shift import Shift, ShiftStatus, CheckInOut

# Configuración DB
DATABASE_URL = str(settings.DATABASE_URL).replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


# ==========================================
# FUNCIONES AUXILIARES DE CONFIGURACIÓN DB
# ==========================================

async def ensure_transaction_types(db: AsyncSession):
    """
    Asegura que todos los tipos de transacción requeridos existan en el ENUM transactiontype.
    
    Esta función es idempotente y maneja correctamente el caso donde el valor ya existe,
    evitando errores de duplicado mediante un bloque PL/pgSQL con excepción.
    """
    print("🔧 Verificando tipos de transacción en ENUM transactiontype...")
    
    required_types = [
        'PAGO_ENTREGA',
        'PAGO_INTENTO_FALLIDO',
        'BONO_RENDIMIENTO',
        'PENALIZACION',
        'AJUSTE_MANUAL',
        'INGRESO',
        'RETIRO',
        'BONO',           # Legacy
        'DESCUENTO',      # Legacy
        'AJUSTE',         # Legacy
    ]
    
    for tx_type in required_types:
        try:
            # Validación estricta del valor antes de interpolación (seguridad)
            if not tx_type.isupper() or not tx_type.replace('_', '').isalnum():
                raise ValueError(f"Tipo de transacción inválido: {tx_type}")
            
            # Usamos DO $$ ... END $$ para ejecutar un bloque anónimo de PL/pgSQL
            # que intenta agregar el valor y lo ignora si ya existe
            # NOTA: No podemos usar parámetros ($1) en bloques DO, usamos interpolación segura
            sql = text(f"""
                DO $$
                BEGIN
                    ALTER TYPE transactiontype ADD VALUE '{tx_type}';
                EXCEPTION
                    WHEN duplicate_object THEN NULL;
                    WHEN undefined_object THEN NULL;
                END
                $$;
            """)
            await db.execute(sql)
            await db.commit()
            print(f"   ✅ Tipo '{tx_type}' verificado/creado exitosamente.")
        except Exception as e:
            await db.rollback()
            print(f"   ⚠️ Advertencia al procesar '{tx_type}': {e}")
            # Continuamos con el siguiente tipo en lugar de fallar completamente


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
    """Seed persisted platform settings used by the admin settings module.
    
    Includes Fases 1, 2 y 3:
    - Fase 1: Bono por entrega exitosa (rider_delivery_bonus)
    - Fase 2: Bono por intento fallido (rider_failed_attempt_bonus)
    - Configuraciones adicionales de plataforma
    """
    print("⚙️ Sembrando configuración global de plataforma (Fases 1, 2 y 3)...")

    admin_result = await db.execute(
        select(User).where(User.role.in_([UserRole.SUPERADMIN, UserRole.GERENTE])).order_by(User.created_at.asc())
    )
    admin_user = admin_result.scalars().first()
    active_zone_names = [zone.name for zone in zones if getattr(zone, "is_active", True)] or ["Norte", "Sur", "Centro"]

    setting_defs = {
        # FASE 1: Bono por entrega exitosa (2500 COP)
        "rider_delivery_bonus": {
            "value": "2500",  # String como JSON, valor en COP
            "description": "Bono en COP por cada entrega completada exitosamente (Fase 1).",
        },
        # FASE 2: Bono por intento fallido (culpa del cliente) (1500 COP)
        "rider_failed_attempt_bonus": {
            "value": "1500",  # String como JSON, valor en COP
            "description": "Bono en COP por intento de entrega fallido por causa del cliente (Fase 2).",
        },
        # Configuraciones existentes
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


async def seed_zones_with_multipliers(db: AsyncSession):
    """Actualiza las zonas con multiplicadores por defecto (FASE 3).
    
    Define multiplicadores geográficos para bonos de repartidores:
    - NORTE: 1.5x (zona lejana/peligrosa: +50%)
    - SUR: 1.2x (zona media: +20%)
    - CENTRO: 1.0x (zona estándar: precio base)
    - ZONA G: 1.3x (zona compleja: +30%)
    """
    print("📍 Sembrando multiplicadores de bono en zonas (Fase 3)...")
    
    # Definición de zonas ejemplo con sus multiplicadores
    zones_update = {
        "NRT": 1.5,    # Zona Norte: lejana/peligrosa: +50%
        "SUR": 1.2,    # Zona Sur: media: +20%
        "CTR": 1.0,    # Zona Centro: estándar: precio base
        "ZNG": 1.3,    # Zona G: compleja: +30%
    }

    updated = 0
    created = 0
    for code, multiplier in zones_update.items():
        stmt = select(Zone).where(Zone.code == code)
        result = await db.execute(stmt)
        zone = result.scalar_one_or_none()
        
        if zone:
            zone.bonus_multiplier = multiplier
            print(f"   📍 Zone {zone.name} ({code}) set to multiplier x{multiplier}")
            updated += 1
        else:
            # Opcional: Crear la zona si no existe (ajusta los campos requeridos)
            new_zone = Zone(
                id=uuid.uuid4(),
                name=f"Zona {code}",
                code=code,
                description=f"Zona de operación {code} con multiplicador {multiplier}",
                delivery_fee_base=5000.0,
                cost_per_km=1000.0,
                is_active=True,
                bonus_multiplier=multiplier,
                color_hex="#6b7280"
            )
            db.add(new_zone)
            print(f"   ✅ Created new zone: {code} with multiplier x{multiplier}")
            created += 1

    await db.commit()
    print(f"   ✅ {updated} zonas actualizadas / {created} zonas creadas con multiplicadores.")


async def seed_riders(db: AsyncSession, zones: List[Zone], vehicles: List[Vehicle], count: int = 15) -> List[Rider]:
    """
    Genera repartidores con soporte para vehículos propios y de empresa.
    
    - 70% de repartidores usan vehículo propio (vehicle_ownership_type=PROPIO)
    - 30% de repartidores usan vehículo de empresa (vehicle_ownership_type=EMPRESA)
    - Al menos 2 repartidores tienen nivel ORO para pruebas de bonos
    - Algunos repartidores tienen niveles PLATA y PLATINO para variedad
    """
    print(f"🛵 Sembrando repartidores (con vehículos propios y de empresa)...")
    riders = []
    # Usamos los valores string directamente para evitar conflictos de enums entre modelos
    vehicle_types = ["MOTO", "MOTO", "BICICLETA", "AUTO"] 
    fallback_zone_points = [(4.668, -74.050), (4.676, -74.047), (4.600, -74.075), (4.695, -74.030)]

    # Obtener vehículos disponibles de empresa (sin rider_id asignado)
    company_vehicles = [v for v in vehicles if v.rider_id is None and v.status == "ACTIVO"]
    
    # Definir tiers para los primeros repartidores (asegurar al menos 2 ORO)
    # Distribución: rider 0=ORO, 1=ORO, 2=PLATINO, 3=PLATA, resto aleatorio
    tier_assignment = {
        0: RiderTier.ORO,
        1: RiderTier.ORO,
        2: RiderTier.PLATINO,
        3: RiderTier.PLATA,
    }
    
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
            
            # Determinar tier del rider (al menos 2 ORO garantizados)
            rider_tier = tier_assignment.get(i, random.choice([RiderTier.BRONCE, RiderTier.PLATA, RiderTier.ORO]))

            # Determinar tipo de propiedad del vehículo (70% propio, 30% empresa)
            is_company_vehicle = (i % 3 == 0) and len(company_vehicles) > 0  # Cada tercer rider usa vehículo de empresa
            
            if is_company_vehicle:
                # Vehículo de EMPRESA: asignar un vehículo disponible de la flota
                assigned_vehicle = company_vehicles.pop(0)  # Tomar el primer vehículo disponible
                rider = Rider(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    vehicle_type=assigned_vehicle.type,
                    vehicle_plate=None,  # NULL para vehículo de empresa
                    vehicle_model=None,  # NULL para vehículo de empresa
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
                    vehicle_ownership_type=VehicleOwnershipType.EMPRESA.value,
                    assigned_vehicle_id=assigned_vehicle.id,
                    tier=rider_tier,
                )
                print(f"   🏢 Rider {email} con vehículo de empresa: {assigned_vehicle.plate} | Tier: {rider_tier.value}")
            else:
                # Vehículo PROPIO: datos tradicionales del rider
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
                    vehicle_ownership_type=VehicleOwnershipType.PROPIO.value,
                    assigned_vehicle_id=None,
                    tier=rider_tier,
                )
            db.add(rider)
            riders.append(rider)
            
    await db.commit()
    print(f"   ✅ {len(riders)} repartidores listos.")
    return riders

async def seed_vehicles(db: AsyncSession, users: List[User], riders: List[Rider], count: int = 20) -> List[Vehicle]:
    """
    Genera una flota de vehículos.
    - Algunos se asignan a los riders existentes (vinculando rider_id/user_id).
    - Otros quedan disponibles (rider_id NULL) para pruebas de asignación manual.
    
    Retorna la lista de vehículos creados para usar en seed_riders.
    """
    print(f"🚗 Sembrando flota de vehículos...")
    vehicles_created = 0
    vehicles_list = []
    
    # Tipos y estados disponibles
    v_types = ["MOTO", "AUTO", "FURGONETA", "BICICLETA"]
    v_statuses = ["ACTIVO", "ACTIVO", "ACTIVO", "MANTENIMIENTO", "BAJA"] # Mayor probabilidad de ACTIVO
    
    # 1. Crear vehículos para los riders existentes (simulando que su vehículo está en la flota formal)
    #    Solo para riders con vehículo PROPIO
    for rider in riders:
        # Saltar riders con vehículo de empresa (ya tienen assigned_vehicle_id)
        if hasattr(rider, 'vehicle_ownership_type') and rider.vehicle_ownership_type == "EMPRESA":
            continue
            
        # Obtenemos el usuario dueño del rider. Si no está en la lista local,\n        # lo consultamos en BD porque seed_users solo retorna usuarios recién creados.\n        user = next((u for u in users if u.id == rider.user_id), None)\n        if not user:\n            user = await db.get(User, rider.user_id)\n        if not user:\n            continue\n            \n        # Verificar si ya existe un vehículo con esa placa (por seguridad)\n        existing = await db.execute(select(Vehicle).where(Vehicle.plate == rider.vehicle_plate))\n        if existing.scalar_one_or_none():\n            continue\n\n        vehicle = Vehicle(\n            id=uuid.uuid4(),\n            rider_id=user.id, # Vinculado al dueño (usuario)\n            plate=rider.vehicle_plate,\n            type=rider.vehicle_type, # Usa el tipo del rider\n            model=rider.vehicle_model or f\"Vehículo {rider.vehicle_type}\",\n            color=random.choice(["Rojo", "Azul", "Negro", "Blanco", "Gris"]),\n            year=random.randint(2018, 2024),\n            status="ACTIVO",\n            insurance_expiry=datetime.now().date() + timedelta(days=random.randint(30, 300)),\n            notes=f"Asignado inicialmente al rider {rider.id}"\n        )\n        db.add(vehicle)\n        vehicles_list.append(vehicle)\n        vehicles_created += 1

    # 2. Crear vehículos adicionales \"huérfanos\" o de reserva para la flota
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
        vehicles_list.append(vehicle)
        vehicles_created += 1

    await db.commit()
    print(f"   ✅ {vehicles_created} vehículos registrados en la flota.")
    return vehicles_list

async def seed_orders_and_complex_data(db: AsyncSession, riders: List[Rider], count: int = 50):
    print(f"📦 Generando órdenes, entregas y rutas...")
    
    active_riders = [r for r in riders if r.status == "ACTIVO"]
    
    if not active_riders:
        result = await db.execute(select(Rider).where(Rider.status == "ACTIVO"))
        active_riders = list(result.scalars().all())
        if not active_riders:
            print("   ⚠️ No hay riders activos disponibles para asignar órdenes.")
            return []

    # ==========================================
    # LIMPIEZA PREvia PARA IDEMPOTENCIA (FASE 3)
    # ==========================================
    # Para garantizar idempotencia total, eliminamos órdenes y financials generados por seed anterior
    # Esto evita UniqueViolationError en external_id y permite re-ejecutar el script sin errores
    print("   🧹 Limpiando datos previos de seed (órdenes, deliveries, financials)...")
    try:
        # FASE 10: huérfanos fiscales de seeds previos. Las FKs de
        # electronic_invoices.order_id y payment_distribution_snapshots.order_id
        # tienen ON DELETE CASCADE, PERO el orden físico de esta limpieza borra
        # deliveries/órdenes ANTES de purgar splits/conciliaciones — y en Postgres
        # las restricciones NO-deferrable se validan al instante del DELETE, así
        # que cualquier borrado de orders con hijos fiscales abortaba la limpieza
        # entera (excepción -> rollback -> ⚠️ "Advertencia en limpieza"). Al no
        # limpiarse, las reinserciones de órdenes/chats fallaban con IntegrityError
        # y main() moría ANTES de ejecutar seed_fase10_fiscal() => tablas fiscales
        # SIEMPRE en 0. Fix: purgar primero los hijos fiscales del seed demo
        # (facturas + splits + conciliaciones), luego cascade limpia solos los
        # restos al borrar orders, y resync del contador de la resolución CO.
        await db.execute(text(
            "DELETE FROM bank_reconciliation_records "
            "WHERE notes = 'Demo seed Fase 10' OR bank_reference LIKE 'SEED-BANK-%'"
        ))
        await db.execute(text(
            "DELETE FROM payment_distribution_snapshots "
            "WHERE applied_rule_json LIKE '%demo_seed%' "
            "   OR order_id IN (SELECT id FROM orders WHERE external_id LIKE 'ORD-%' "
            "                   OR external_id LIKE 'LIVE-MAP-DEMO-%')"
        ))
        await db.execute(text(
            "DELETE FROM electronic_invoices "
            "WHERE unique_identifier LIKE 'SEED-%' "
            "   OR order_id IN (SELECT id FROM orders WHERE external_id LIKE 'ORD-%' "
            "                   OR external_id LIKE 'LIVE-MAP-DEMO-%')"
        ))
        # Resync del contador de la resolución CO tras la purga de facturas demo
        # (lo vuelve a avanzar seed_fase10_fiscal al re-sembrar).
        await db.execute(text(
            "UPDATE invoice_resolutions r SET current_counter = COALESCE(("
            "  SELECT max(ei.sequence_number) FROM electronic_invoices ei"
            "  WHERE ei.provider_type = r.country_code"
            "), 0) "
            "WHERE r.country_code = 'CO'"
        ))
        # Eliminar financials asociados a seed previo
        await db.execute(text("DELETE FROM financials WHERE source_type LIKE 'SEED%'"))
        # Eliminar deliveries asociados a órdenes de seed
        await db.execute(text("DELETE FROM deliveries WHERE order_id IN (SELECT id FROM orders WHERE external_id LIKE 'ORD-%' OR external_id LIKE 'LIVE-MAP-DEMO-%')"))
        # Eliminar órdenes de seed previo
        await db.execute(text("DELETE FROM orders WHERE external_id LIKE 'ORD-%' OR external_id LIKE 'LIVE-MAP-DEMO-%'"))
        await db.commit()
        print("   ✅ Limpieza completada exitosamente.")
    except Exception as e:
        await db.rollback()
        print(f"   ⚠️ Advertencia en limpieza: {e}")

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
    
    # ==========================================
    # GENERAR TRANSACCIONES DE EJEMPLO PARA NUEVOS TIPOS (FASE 3)
    # ==========================================
    print("💰 Generando transacciones de ejemplo para nuevos tipos (Fase 3)...")
    
    if active_riders:
        sample_rider = active_riders[0]
        
        # Obtener un usuario admin para referencias (si existe)
        result_users = await db.execute(select(User).where(User.role.in_([UserRole.SUPERADMIN, UserRole.GERENTE])).limit(1))
        users_list = list(result_users.scalars().all())
        sample_admin = users_list[0] if users_list else None
        
        # Obtener balance actual del rider
        current_balance = float(sample_rider.wallet_balance) if sample_rider.wallet_balance else 0.0
        
        # 1. PAGO_ENTREGA - Ya se genera arriba en el batch de productividad
        #    Se deja comentado porque ya está cubierto por el código de rider_stats
        
        # 2. PAGO_INTENTO_FALLIDO - Ejemplo de bonificación por intento fallido
        idempotency_failed = f"seed-failed-attempt-{sample_rider.id}"
        existing = await db.execute(
            select(Financial).where(Financial.idempotency_key == idempotency_failed)
        )
        if not existing.scalar_one_or_none():
            await FinancialService(db).create_ledger_entry(
                rider_id=sample_rider.id,
                transaction_type=TransactionType.PAGO_INTENTO_FALLIDO,
                amount=1500.00,
                status=PaymentStatus.PROCESADO,
                description="Bono por intento fallido - Entrega no completada por cliente ausente",
                source_type="SEED_DEMO",
                source_id="failed_attempt_001",
                idempotency_key=idempotency_failed,
                created_by_user_id=sample_admin.id if sample_admin else None,
                commit=False,
            )
            print("   ✅ Transacción PAGO_INTENTO_FALLIDO creada")
        
        # 3. BONO_RENDIMIENTO - Ejemplo de bono por productividad
        idempotency_bonus = f"seed-performance-bonus-{sample_rider.id}"
        existing = await db.execute(
            select(Financial).where(Financial.idempotency_key == idempotency_bonus)
        )
        if not existing.scalar_one_or_none():
            await FinancialService(db).create_ledger_entry(
                rider_id=sample_rider.id,
                transaction_type=TransactionType.BONO_RENDIMIENTO,
                amount=25000.00,
                status=PaymentStatus.PROCESADO,
                description="Bono de rendimiento semanal - Meta de 50 entregas completadas",
                source_type="SEED_DEMO",
                source_id="performance_bonus_001",
                idempotency_key=idempotency_bonus,
                created_by_user_id=sample_admin.id if sample_admin else None,
                commit=False,
            )
            print("   ✅ Transacción BONO_RENDIMIENTO creada")
        
        # 4. PENALIZACION - Ejemplo de descuento operativo
        idempotency_penalty = f"seed-penalty-{sample_rider.id}"
        existing = await db.execute(
            select(Financial).where(Financial.idempotency_key == idempotency_penalty)
        )
        if not existing.scalar_one_or_none():
            await FinancialService(db).create_ledger_entry(
                rider_id=sample_rider.id,
                transaction_type=TransactionType.PENALIZACION,
                amount=5000.00,  # Monto positivo, el servicio calcula el signo según DEBIT_TYPES
                status=PaymentStatus.PROCESADO,
                description="Penalización por reporte de incidente operacional",
                source_type="SEED_DEMO",
                source_id="penalty_001",
                idempotency_key=idempotency_penalty,
                created_by_user_id=sample_admin.id if sample_admin else None,
                commit=False,
            )
            print("   ✅ Transacción PENALIZACION creada")
        
        # 5. AJUSTE_MANUAL - Ejemplo de ajuste administrativo (positivo)
        idempotency_adjustment = f"seed-manual-adjustment-{sample_rider.id}"
        existing = await db.execute(
            select(Financial).where(Financial.idempotency_key == idempotency_adjustment)
        )
        if not existing.scalar_one_or_none():
            await FinancialService(db).create_ledger_entry(
                rider_id=sample_rider.id,
                transaction_type=TransactionType.AJUSTE_MANUAL,
                amount=10000.00,
                status=PaymentStatus.PROCESADO,
                description="Ajuste manual - Corrección de error en cálculo de bonos (crédito)",
                source_type="SEED_DEMO",
                source_id="manual_adjustment_001",
                idempotency_key=idempotency_adjustment,
                created_by_user_id=sample_admin.id if sample_admin else None,
                commit=False,
            )
            print("   ✅ Transacción AJUSTE_MANUAL creada")
        
        # 6. INGRESO - Ejemplo de depósito de saldo externo
        idempotency_deposit = f"seed-deposit-{sample_rider.id}"
        existing = await db.execute(
            select(Financial).where(Financial.idempotency_key == idempotency_deposit)
        )
        if not existing.scalar_one_or_none():
            await FinancialService(db).create_ledger_entry(
                rider_id=sample_rider.id,
                transaction_type=TransactionType.INGRESO,
                amount=50000.00,
                status=PaymentStatus.PROCESADO,
                description="Depósito de saldo inicial - Promoción bienvenida",
                source_type="SEED_DEMO",
                source_id="deposit_001",
                idempotency_key=idempotency_deposit,
                created_by_user_id=sample_admin.id if sample_admin else None,
                commit=False,
            )
            print("   ✅ Transacción INGRESO creada")
        
        await db.commit()
        print("   ✅ Todas las transacciones de ejemplo Fase 3 creadas exitosamente.")
    
    return orders


async def seed_live_map_demo_data(db: AsyncSession, riders: List[Rider], target_count: int = 5) -> List[Order]:
    """Ensure operator live-map has real active deliveries with valid GPS coordinates.

    The operator map intentionally reads /deliveries?status=EN_ROUTE and renders only
    deliveries with finite current_latitude/current_longitude. This seed creates or
    refreshes deterministic demo orders/deliveries so local/dev environments can
    validate the production flow without frontend mocks.
    """
    print("🗺️ Poblando mapa en vivo de operador con entregas GPS demo...")

    now = utc_now_naive()
    demo_routes = [
        {
            "external_id": "LIVE-MAP-DEMO-001",
            "customer_name": "Cliente Demo Norte",
            "pickup_name": "Burger King Zona G",
            "pickup_address": "Cra 4 #85-10, Chapinero",
            "pickup_lat": 4.6680,
            "pickup_lng": -74.0500,
            "delivery_address": "Calle 92 #15-20, Chicó",
            "delivery_lat": 4.6738,
            "delivery_lng": -74.0521,
            "current_lat": 4.6706,
            "current_lng": -74.0510,
        },
        {
            "external_id": "LIVE-MAP-DEMO-002",
            "customer_name": "Cliente Demo Centro",
            "pickup_name": "Saludpan Farmacia",
            "pickup_address": "Av 19 #11-40, Centro",
            "pickup_lat": 4.6000,
            "pickup_lng": -74.0750,
            "delivery_address": "Carrera 7 #26-35, Centro Internacional",
            "delivery_lat": 4.6129,
            "delivery_lng": -74.0705,
            "current_lat": 4.6068,
            "current_lng": -74.0729,
        },
        {
            "external_id": "LIVE-MAP-DEMO-003",
            "customer_name": "Cliente Demo Usaquén",
            "pickup_name": "Sushi Master Usaquén",
            "pickup_address": "Cra 6 #119-60, Usaquén",
            "pickup_lat": 4.6950,
            "pickup_lng": -74.0300,
            "delivery_address": "Calle 116 #14-20, Santa Bárbara",
            "delivery_lat": 4.6958,
            "delivery_lng": -74.0445,
            "current_lat": 4.6952,
            "current_lng": -74.0378,
        },
        {
            "external_id": "LIVE-MAP-DEMO-004",
            "customer_name": "Cliente Demo Chapinero",
            "pickup_name": "Pizza Hut Parque 93",
            "pickup_address": "Cll 93B #13-30, Parque 93",
            "pickup_lat": 4.6760,
            "pickup_lng": -74.0470,
            "delivery_address": "Calle 72 #10-34, Quinta Camacho",
            "delivery_lat": 4.6575,
            "delivery_lng": -74.0583,
            "current_lat": 4.6669,
            "current_lng": -74.0524,
        },
        {
            "external_id": "LIVE-MAP-DEMO-005",
            "customer_name": "Cliente Demo Sur",
            "pickup_name": "La Hamburguesa del Sur",
            "pickup_address": "Cll 42 Sur #20-10",
            "pickup_lat": 4.5700,
            "pickup_lng": -74.1200,
            "delivery_address": "Carrera 24 #38-15 Sur, Restrepo",
            "delivery_lat": 4.5862,
            "delivery_lng": -74.1037,
            "current_lat": 4.5784,
            "current_lng": -74.1112,
        },
    ][:target_count]

    candidate_riders = [r for r in riders if (r.status == RiderStatus.ACTIVO or str(r.status) == RiderStatus.ACTIVO.value)]
    if len(candidate_riders) < len(demo_routes):
        result = await db.execute(
            select(Rider)
            .where(Rider.status == RiderStatus.ACTIVO)
            .limit(len(demo_routes))
        )
        candidate_riders = list(result.scalars().all())

    if not candidate_riders:
        print("   ⚠️ No hay riders activos para poblar el live-map de operador.")
        return []

    created_or_updated: List[Order] = []

    for index, route in enumerate(demo_routes):
        rider = candidate_riders[index % len(candidate_riders)]
        order_result = await db.execute(select(Order).where(Order.external_id == route["external_id"]))
        order = order_result.scalar_one_or_none()

        if not order:
            order = Order(
                id=uuid.uuid4(),
                external_id=route["external_id"],
                customer_name=route["customer_name"],
                customer_phone=f"+573{random.randint(100000000, 999999999)}",
                pickup_name=route["pickup_name"],
                pickup_address=route["pickup_address"],
                pickup_latitude=route["pickup_lat"],
                pickup_longitude=route["pickup_lng"],
                delivery_address=route["delivery_address"],
                delivery_latitude=route["delivery_lat"],
                delivery_longitude=route["delivery_lng"],
                items=[{"product_name": "Pedido demo live-map", "quantity": 1, "unit_price": 25000, "subtotal": 25000}],
                subtotal=25000,
                delivery_fee=5000,
                total=30000,
                payment_method="TARJETA",
                payment_status="PAGADO",
                status=OrderStatus.EN_RUTA,
                priority=OrderPriority.ALTA,
                assigned_rider_id=rider.id,
                ordered_at=now - timedelta(minutes=35 + index * 4),
                accepted_at=now - timedelta(minutes=30 + index * 4),
                picked_up_at=now - timedelta(minutes=18 + index * 2),
                estimated_delivery_time=now + timedelta(minutes=15 + index * 3),
                sla_deadline=now + timedelta(minutes=25 + index * 3),
                source="seed_live_map",
            )
            db.add(order)
            await db.flush()
        else:
            order.customer_name = route["customer_name"]
            order.pickup_name = route["pickup_name"]
            order.pickup_address = route["pickup_address"]
            order.pickup_latitude = route["pickup_lat"]
            order.pickup_longitude = route["pickup_lng"]
            order.delivery_address = route["delivery_address"]
            order.delivery_latitude = route["delivery_lat"]
            order.delivery_longitude = route["delivery_lng"]
            order.status = OrderStatus.EN_RUTA
            order.priority = OrderPriority.ALTA
            order.assigned_rider_id = rider.id
            order.accepted_at = order.accepted_at or now - timedelta(minutes=30 + index * 4)
            order.picked_up_at = order.picked_up_at or now - timedelta(minutes=18 + index * 2)
            order.delivered_at = None
            order.estimated_delivery_time = now + timedelta(minutes=15 + index * 3)
            order.sla_deadline = now + timedelta(minutes=25 + index * 3)
            order.source = "seed_live_map"

        delivery_result = await db.execute(select(Delivery).where(Delivery.order_id == order.id))
        delivery = delivery_result.scalar_one_or_none()
        if not delivery:
            delivery = Delivery(
                id=uuid.uuid4(),
                order_id=order.id,
                rider_id=rider.id,
                proof_type=ProofType.OTP,
            )
            db.add(delivery)

        delivery.status = DeliveryStatus.EN_ROUTE
        delivery.started_at = order.accepted_at or now - timedelta(minutes=30)
        delivery.completed_at = None
        delivery.current_latitude = route["current_lat"]
        delivery.current_longitude = route["current_lng"]
        delivery.last_location_update = now - timedelta(seconds=index * 45)
        delivery.distance_total = random.uniform(3.5, 9.5)
        delivery.sla_expected_minutes = 60
        delivery.sla_actual_minutes = None
        delivery.sla_compliant = None

        rider.is_online = True
        rider.status = RiderStatus.ACTIVO
        rider.current_order_id = order.id
        rider.last_lat = route["current_lat"]
        rider.last_lng = route["current_lng"]
        rider.last_location_at = delivery.last_location_update

        created_or_updated.append(order)

    await db.commit()
    print(f"   ✅ {len(created_or_updated)} entregas activas con GPS listas para /operator/live-map.")
    return created_or_updated


async def seed_shifts(db: AsyncSession, riders: List[Rider], target_count: int = 12) -> List[Shift]:
    """Seed operational shifts for the operator dashboard.

    The operator UI consumes /shifts and expects PLANIFICADO/ACTIVO/FINALIZADO/CANCELADO
    status labels plus rider names and time windows. This creates deterministic shifts
    over today/yesterday/tomorrow so the module has visible data after seeding.
    """
    print("🕒 Sembrando turnos demo para el módulo operador...")

    active_riders = [r for r in riders if (r.status == RiderStatus.ACTIVO or str(r.status) == RiderStatus.ACTIVO.value)]
    if not active_riders:
        result = await db.execute(select(Rider).where(Rider.status == RiderStatus.ACTIVO).limit(target_count))
        active_riders = list(result.scalars().all())

    if not active_riders:
        print("   ⚠️ No hay riders activos para crear turnos demo.")
        return []

    now = utc_now_naive()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    shift_templates = [
        {"day": 0, "start": time(7, 0), "end": time(15, 0), "status": ShiftStatus.EN_CURSO, "check_in_offset": 125},
        {"day": 0, "start": time(8, 0), "end": time(16, 0), "status": ShiftStatus.EN_CURSO, "check_in_offset": 90},
        {"day": 0, "start": time(9, 0), "end": time(17, 0), "status": ShiftStatus.PROGRAMADO, "check_in_offset": None},
        {"day": 0, "start": time(12, 0), "end": time(20, 0), "status": ShiftStatus.PROGRAMADO, "check_in_offset": None},
        {"day": 0, "start": time(14, 0), "end": time(22, 0), "status": ShiftStatus.PROGRAMADO, "check_in_offset": None},
        {"day": -1, "start": time(7, 0), "end": time(15, 0), "status": ShiftStatus.COMPLETADO, "check_in_offset": 480},
        {"day": -1, "start": time(10, 0), "end": time(18, 0), "status": ShiftStatus.COMPLETADO, "check_in_offset": 480},
        {"day": -1, "start": time(14, 0), "end": time(22, 0), "status": ShiftStatus.CANCELADO, "check_in_offset": None},
        {"day": 1, "start": time(7, 0), "end": time(15, 0), "status": ShiftStatus.PROGRAMADO, "check_in_offset": None},
        {"day": 1, "start": time(15, 0), "end": time(23, 0), "status": ShiftStatus.PROGRAMADO, "check_in_offset": None},
        {"day": 2, "start": time(8, 0), "end": time(16, 0), "status": ShiftStatus.PROGRAMADO, "check_in_offset": None},
        {"day": 2, "start": time(16, 0), "end": time(23, 59), "status": ShiftStatus.PROGRAMADO, "check_in_offset": None},
    ][:target_count]

    seeded: List[Shift] = []
    for index, template in enumerate(shift_templates):
        rider = active_riders[index % len(active_riders)]
        shift_date = today + timedelta(days=template["day"])
        existing_result = await db.execute(
            select(Shift).where(
                Shift.rider_id == rider.id,
                Shift.shift_date == shift_date,
                Shift.start_time == template["start"],
            )
        )
        shift = existing_result.scalar_one_or_none()

        if not shift:
            shift = Shift(
                rider_id=rider.id,
                shift_date=shift_date,
                start_time=template["start"],
                end_time=template["end"],
                status=template["status"],
                total_deliveries=random.randint(2, 9) if template["status"] == ShiftStatus.COMPLETADO else random.randint(0, 4),
                completed_deliveries=random.randint(2, 8) if template["status"] == ShiftStatus.COMPLETADO else random.randint(0, 3),
                total_earnings=round(random.uniform(25000, 120000), 2) if template["status"] == ShiftStatus.COMPLETADO else round(random.uniform(0, 45000), 2),
                notes="Turno demo generado para tablero operador",
            )
            db.add(shift)
            await db.flush()
        else:
            shift.end_time = template["end"]
            shift.status = template["status"]
            shift.notes = shift.notes or "Turno demo generado para tablero operador"

        if template["status"] == ShiftStatus.EN_CURSO:
            check_in_at = now - timedelta(minutes=template["check_in_offset"] or 60)
            shift.check_in_at = check_in_at
            shift.check_out_at = None
            if rider.last_lat is not None and rider.last_lng is not None:
                shift.check_in_latitude = rider.last_lat
                shift.check_in_longitude = rider.last_lng
            existing_check = await db.execute(
                select(CheckInOut).where(
                    CheckInOut.shift_id == shift.id,
                    CheckInOut.check_type == "IN",
                )
            )
            if not existing_check.scalar_one_or_none():
                db.add(CheckInOut(
                    rider_id=rider.id,
                    shift_id=shift.id,
                    check_type="IN",
                    timestamp=check_in_at,
                    latitude=rider.last_lat,
                    longitude=rider.last_lng,
                    notes="Check-in demo",
                ))
        elif template["status"] == ShiftStatus.COMPLETADO:
            shift.check_in_at = datetime.combine(shift_date.date(), template["start"])
            shift.check_out_at = datetime.combine(shift_date.date(), template["end"])
        elif template["status"] == ShiftStatus.CANCELADO:
            shift.cancellation_reason = shift.cancellation_reason or "Cancelado por baja demanda demo"

        seeded.append(shift)

    await db.commit()
    print(f"   ✅ {len(seeded)} turnos demo listos para /operator/shifts.")
    return seeded


async def seed_demo_payouts(db: AsyncSession, riders: List[Rider]):
    """Seed payout requests with all 6 PayoutStatus values for comprehensive demos.
    
    Usa selectinload para cargar relaciones y evitar errores MissingGreenlet.
    Usa getattr seguro para acceder a rider.user.name.
    Usa TODOS los valores del enum PayoutStatus en español: PENDIENTE, APROBADO, 
    EN_PROCESO, COMPLETADO, RECHAZADO, FALLIDO.
    Crea wallets automáticamente si no existen.
    """
    print("💸 Sembrando retiros demo con los 6 estados de PayoutStatus...")

    admin_result = await db.execute(select(User).where(User.role == UserRole.SUPERADMIN))
    admin_user = admin_result.scalar_one_or_none()
    if not admin_user:
        print("   ⚠️ No hay superadmin para trazar retiros demo.")
        return

    # Cargar riders con sus relaciones user y wallet explícitamente para evitar lazy loading
    from sqlalchemy.orm import selectinload
    from app.models.financial import PayoutRequest, PayoutStatus as PayoutRequestStatus
    
    rider_ids = [r.id for r in riders]
    result = await db.execute(
        select(Rider)
        .where(Rider.id.in_(rider_ids))
        .options(selectinload(Rider.user), selectinload(Rider.wallet))
    )
    candidates = list(result.scalars().all())
    
    # Filtrar riders con balance suficiente usando getattr seguro
    candidates = [rider for rider in candidates if money(getattr(rider, "wallet_balance", 0)) > Decimal("20.00")]
    
    if not candidates:
        result = await db.execute(
            select(Rider)
            .options(selectinload(Rider.user), selectinload(Rider.wallet))
            .limit(5)
        )
        candidates = list(result.scalars().all())

    # TODOS los 6 estados de payout en español (usando el enum correcto)
    statuses = [
        PayoutRequestStatus.PENDIENTE,
        PayoutRequestStatus.APROBADO,
        PayoutRequestStatus.EN_PROCESO,
        PayoutRequestStatus.COMPLETADO,
        PayoutRequestStatus.RECHAZADO,
        PayoutRequestStatus.FALLIDO
    ]
    created = 0
    now = utc_now_naive()

    for index, rider in enumerate(candidates[:12]):  # Permitir hasta 12 payouts (2 por estado)
        status_value = statuses[index % len(statuses)]
        idempotency_key = f"seed-payout-{status_value.value.lower()}-{rider.id}-{index // len(statuses)}"
        existing = await db.execute(select(PayoutRequest).where(PayoutRequest.idempotency_key == idempotency_key))
        if existing.scalar_one_or_none():
            continue

        current_balance = money(getattr(rider, "wallet_balance", 0))
        if current_balance <= Decimal("20.00"):
            continue

        amount = min(Decimal("30000.00"), max(Decimal("10.00"), money(current_balance * Decimal("0.30"))))
        
        # Calcular balance_after según el estado
        if status_value in [PayoutRequestStatus.PENDIENTE, PayoutRequestStatus.APROBADO, PayoutRequestStatus.EN_PROCESO]:
            balance_after = current_balance - amount
        elif status_value == PayoutRequestStatus.COMPLETADO:
            balance_after = current_balance - amount
        else:  # RECHAZADO o FALLIDO
            balance_after = current_balance
        
        payout_id = uuid.uuid4()
        requested_at = now - timedelta(hours=8 + index)
        
        # Determinar timestamps según el estado
        if status_value == PayoutRequestStatus.PENDIENTE:
            approved_at = None
            processed_at = None
            completed_at = None
            failed_at = None
        elif status_value == PayoutRequestStatus.APROBADO:
            approved_at = requested_at + timedelta(hours=2)
            processed_at = None
            completed_at = None
            failed_at = None
        elif status_value == PayoutRequestStatus.EN_PROCESO:
            approved_at = requested_at + timedelta(hours=1)
            processed_at = requested_at + timedelta(hours=3)
            completed_at = None
            failed_at = None
        elif status_value == PayoutRequestStatus.COMPLETADO:
            approved_at = requested_at + timedelta(hours=1)
            processed_at = requested_at + timedelta(hours=2)
            completed_at = requested_at + timedelta(hours=4)
            failed_at = None
        elif status_value == PayoutRequestStatus.RECHAZADO:
            approved_at = None
            processed_at = None
            completed_at = None
            failed_at = None
        else:  # FALLIDO
            approved_at = requested_at + timedelta(hours=1)
            processed_at = requested_at + timedelta(hours=2)
            completed_at = None
            failed_at = requested_at + timedelta(hours=5)

        # Crear wallet si no existe
        result = await db.execute(select(RiderWallet).where(RiderWallet.rider_id == rider.id))
        wallet = result.scalar_one_or_none()
        if not wallet:
            wallet = RiderWallet(rider_id=rider.id, balance_cents=int(current_balance * 100))
            db.add(wallet)
            await db.flush()

        # Usar getattr seguro para acceder al nombre del usuario
        user_obj = getattr(rider, 'user', None)
        account_holder_name = getattr(user_obj, 'name', None) or getattr(user_obj, 'first_name', 'Rider') or "Rider"

        payout_req = PayoutRequest(
            id=payout_id,
            wallet_id=wallet.id,
            rider_id=rider.id,
            amount_cents=int(amount * 100),
            currency="USD",
            status=status_value,
            bank_account_last4=str(random.randint(1000, 9999)),
            bank_name="Banco Demo",
            account_holder_name=account_holder_name,
            rejection_reason="Datos bancarios pendientes de validación" if status_value == PayoutRequestStatus.RECHAZADO else None,
            failure_reason="Error en procesamiento bancario" if status_value == PayoutRequestStatus.FALLIDO else None,
            idempotency_key=idempotency_key,
            created_at=requested_at,
            approved_at=approved_at,
            processed_at=processed_at,
            completed_at=completed_at,
            failed_at=failed_at,
        )
        db.add(payout_req)

        created += 1

    await db.commit()
    print(f"   ✅ {created} retiros demo creados con los 6 estados (PENDIENTE, APROBADO, EN_PROCESO, COMPLETADO, RECHAZADO, FALLIDO).")


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

    result = await db.execute(
        select(User).where(
            User.role.in_([UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR]),
            User.is_active == True,
        )
    )
    target_users = list(result.scalars().all())

    if not target_users:
        print("   ⚠️ No hay usuarios operativos para asignar alertas.")
        return

    now = utc_now_naive()
    alerts_to_create = []

    def enum_value(value):
        return value.value if hasattr(value, "value") else str(value)

    cancelled_orders = [o for o in orders if enum_value(o.status) == OrderStatus.CANCELADO.value]
    for order in cancelled_orders[:3]:
        alerts_to_create.append({
            "priority": NotificationPriority.ALTA,
            "title": f"Orden Cancelada: {order.external_id}",
            "message": f"La orden de {order.customer_name} fue cancelada. Razón: {order.cancellation_reason or 'No especificada'}",
            "data": {"alert_type": "FAILURE", "severity": "high", "related_order_id": order.external_id},
            "is_read": False,
            "created_at": now - timedelta(minutes=random.randint(10, 60))
        })

    late_deliveries = [o for o in orders if o.delivered_at and o.sla_deadline and o.delivered_at > o.sla_deadline]
    for order in late_deliveries[:3]:
        alerts_to_create.append({
            "priority": NotificationPriority.CRITICA,
            "title": f"Retraso SLA Detectado: {order.external_id}",
            "message": f"La entrega superó el tiempo estimado en {int((order.delivered_at - order.sla_deadline).total_seconds()/60)} minutos.",
            "data": {"alert_type": "DELAY", "severity": "critical", "related_order_id": order.external_id},
            "is_read": False,
            "created_at": now - timedelta(minutes=random.randint(5, 30))
        })

    inactive_riders = [r for r in riders if enum_value(r.status) == RiderStatus.INACTIVO.value]
    if inactive_riders:
        alerts_to_create.append({
            "priority": NotificationPriority.NORMAL,
            "title": "Riders Inactivos",
            "message": f"Hay {len(inactive_riders)} repartidores inactivos en este momento.",
            "data": {"alert_type": "RIDER", "severity": "medium"},
            "is_read": True,
            "created_at": now - timedelta(hours=2)
        })

    active_order = next((o for o in orders if enum_value(o.status) == OrderStatus.EN_RUTA.value), orders[0] if orders else None)
    if active_order:
        alerts_to_create.append({
            "priority": NotificationPriority.ALTA,
            "title": f"Seguimiento requerido: {active_order.external_id}",
            "message": f"La orden {active_order.external_id} está activa y requiere monitoreo desde operaciones.",
            "data": {"alert_type": "SLA_WARNING", "severity": "high", "related_order_id": active_order.external_id},
            "is_read": False,
            "created_at": now - timedelta(minutes=8)
        })

    alerts_to_create.append({
        "priority": NotificationPriority.BAJA,
        "title": "Mantenimiento Programado",
        "message": "Se realizará mantenimiento en los servidores este domingo a las 3 AM.",
        "data": {"alert_type": "SYSTEM", "severity": "low"},
        "is_read": True,
        "created_at": now - timedelta(hours=24)
    })

    created = 0
    for target_user in target_users:
        for alert_data in alerts_to_create:
            existing = await db.execute(
                select(Notification).where(
                    Notification.user_id == target_user.id,
                    Notification.notification_type == NotificationType.ALERTA_OPERACIONAL,
                    Notification.title == alert_data["title"],
                )
            )
            notification = existing.scalar_one_or_none()
            if notification:
                notification.priority = alert_data["priority"]
                notification.message = alert_data["message"]
                notification.data = alert_data["data"]
                notification.is_read = alert_data["is_read"]
                notification.created_at = alert_data["created_at"]
                continue

            db.add(Notification(
                user_id=target_user.id,
                notification_type=NotificationType.ALERTA_OPERACIONAL,
                priority=alert_data["priority"],
                title=alert_data["title"],
                message=alert_data["message"],
                data=alert_data["data"],
                is_read=alert_data["is_read"],
                created_at=alert_data["created_at"],
            ))
            created += 1

    await db.commit()
    print(f"   ✅ {created} alertas nuevas/actualizadas para {len(target_users)} usuarios operativos.")

# ==========================================
# MAIN
# ==========================================

# ==========================================
# FASE 8: MAPAS & TRACKING (Puerto Ordaz, Venezuela)
# ==========================================

# Coordenadas reales de Puerto Ordaz / Ciudad Guayana, estado Bolívar, Venezuela
PO_CENTER_LAT = 8.3106   # Puerto Ordaz (plaza central aprox.)
PO_CENTER_LNG = -62.6549

PO_ZONES = [
    {"code": "PO-01", "name": "Puerto Ordaz Centro", "color_hex": "#3b82f6",
     "center_lat": 8.3106, "center_lng": -62.6549, "is_priority": True},
    {"code": "PO-02", "name": "Alta Vista", "color_hex": "#22c55e",
     "center_lat": 8.2930, "center_lng": -62.6380, "is_priority": False},
    {"code": "PO-03", "name": "Unare / Villa Asia", "color_hex": "#f97316",
     "center_lat": 8.3350, "center_lng": -62.6800, "is_priority": False},
    {"code": "PO-04", "name": "Chirica / La Florencia", "color_hex": "#a855f7",
     "center_lat": 8.2780, "center_lng": -62.6700, "is_priority": False},
]


async def seed_fase8_tracking(db: AsyncSession):
    """Fase 8: zonas PO-01..PO-04 (Puerto Ordaz), riders con wallet, GPS histórico y snapshots VRP.

    Idempotente: UPSERT/skip por claves naturales (zone.code, rider.user_id,
    marca temporal determinista en rider_live_locations, delivery_id único por snapshot).
    """
    print("🛰️  Sembrando datos Fase 8 (Mapas & Tracking — Puerto Ordaz, Venezuela)...")

    # Resolución defensiva de modelos (evita NameError si el módulo no quedó cargado
    # por diferencias de sys.path entre Docker (/app) y ejecución local).
    try:
        RiderLiveLocation
    except NameError:
        from app.models.location import RiderLiveLocation, DeliveryRouteSnapshot  # type: ignore

    # ---------------- 1) Zonas PO-01..PO-04 (UPSERT por code) ----------------
    zones_by_code: dict[str, Zone] = {}
    zone_created = 0
    for zdef in PO_ZONES:
        existing = (await db.execute(select(Zone).where(Zone.code == zdef["code"]))).scalar_one_or_none()
        if existing:
            zones_by_code[zdef["code"]] = existing
        else:
            zone = Zone(
                id=uuid.uuid4(), is_active=True,
                name=zdef["name"], code=zdef["code"], description=f"Zona operativa Fase 8 — {zdef['name']}, Puerto Ordaz.",
                delivery_fee_base=15000.0, cost_per_km=2500.0, estimated_time_min=30.0,
                bonus_multiplier=1.2 if zdef["is_priority"] else 1.0,
                is_priority=zdef["is_priority"], color_hex=zdef["color_hex"],
                center_lat=zdef["center_lat"], center_lng=zdef["center_lng"],
            )
            db.add(zone)
            zones_by_code[zdef["code"]] = zone
            zone_created += 1
    await db.flush()
    print(f"   ✅ Zonas PO: {zone_created} creadas / {len(zones_by_code)} disponibles.")

    # ---------------- 2) Riders activos en PO con wallet ----------------
    from sqlalchemy.orm import selectinload as _selectinload

    po_zone_ids = [z.id for z in zones_by_code.values()]
    riders = (await db.execute(
        select(Rider)
        .options(_selectinload(Rider.user))
        .where(Rider.zone_id.in_(po_zone_ids), Rider.status == RiderStatus.ACTIVO)
    )).scalars().all()

    if not riders:
        # Crear riders PO sobre usuarios existentes — skip por user_id ya asignado a otro rider
        users_pool = (await db.execute(select(User).limit(50))).scalars().all()
        taken_user_ids = {r.user_id for r in (await db.execute(select(Rider))).scalars().all()}
        available_users = [u for u in users_pool if u.id not in taken_user_ids]
        rider_names = ["Yoiner", "Andreina", "Carlos", "Luisana", "Jose", "Maireth"]
        created_riders = 0
        for idx, user in enumerate(available_users[:6]):
            zdef = PO_ZONES[idx % len(PO_ZONES)]
            first_name = rider_names[idx % len(rider_names)]
            lat, lng = get_random_location_near(zdef["center_lat"], zdef["center_lng"], radius_km=1.0)
            rider = Rider(
                id=uuid.uuid4(), user_id=user.id,
                vehicle_type=RiderVehicleType.MOTO, vehicle_plate=f"PO{800 + created_riders}",
                operating_zone=zdef["name"], zone_id=zones_by_code[zdef["code"]].id,
                status=RiderStatus.ACTIVO, is_online=True, tier=RiderTier.BRONCE,
                last_lat=lat, last_lng=lng, last_location_at=utc_now_naive(),
            )
            db.add(rider)
            created_riders += 1
            print(f"   👤 Rider PO '{first_name}' ({user.email}) → zona {zdef['code']}")
        await db.flush()
        if created_riders:
            print(f"   ✅ {created_riders} riders PO creados.")
        riders = (await db.execute(
            select(Rider).options(_selectinload(Rider.user)).where(Rider.zone_id.in_(po_zone_ids))
        )).scalars().all()

    # Wallets (RiderWallet, esquema Fase 7: balance_cents Integer) — skip si ya existe por rider_id
    wallets_created = 0
    for rider in riders:
        has_wallet = (await db.execute(
            select(RiderWallet).where(RiderWallet.rider_id == rider.id)
        )).scalar_one_or_none()
        if not has_wallet:
            db.add(RiderWallet(id=uuid.uuid4(), rider_id=rider.id, balance_cents=0, currency="USD", is_active=True))
            wallets_created += 1
        # Posición última conocida anclada a la zona PO correspondiente
        if rider.last_lat is None or rider.last_lng is None:
            z = await db.get(Zone, rider.zone_id) if rider.zone_id else None
            lat, lng = get_random_location_near(*(z.center_lat, z.center_lng) if z and z.center_lat else (PO_CENTER_LAT, PO_CENTER_LNG), radius_km=1.5)
            rider.last_lat, rider.last_lng, rider.last_location_at = lat, lng, utc_now_naive()
    await db.flush()
    print(f"   ✅ Wallets: {wallets_created} creados / {len(riders)} riders en PO.")

    # ---------------- 3) GPS histórico simulado (últimas 24 h, cada 5 min) ----------------
    locations_inserted = 0
    # Ancla determinista: slot redondeado a la ventana de 5 min del último cierre de hora UTC.
    # Esto hace la serie temporal IDEMPOTENTE entre ejecuciones del seed (aunque cambie "now").
    anchor = utc_now_naive().replace(minute=(utc_now_naive().minute // 5) * 5, second=0, microsecond=0)
    now = utc_now_naive()  # timestamp real para snapshots (calculated_at/expira en +24h)
    for rider in riders[:8]:
        z = await db.get(Zone, rider.zone_id) if rider.zone_id else None
        base = (z.center_lat, z.center_lng) if z and z.center_lat else (PO_CENTER_LAT, PO_CENTER_LNG)
        for i in range(288):  # 24h * 12 samples/h
            ts = anchor - timedelta(minutes=5 * (288 - i))
            exists = (await db.execute(
                text("SELECT 1 FROM rider_live_locations WHERE rider_id = :r AND recorded_at = :t LIMIT 1"),
                {"r": str(rider.id), "t": ts},
            )).first()
            if exists:
                continue
            jitter = i / 288.0 * 1.2  # deriva suave dentro de ~1.2 km
            lat, lng = get_random_location_near(base[0], base[1], radius_km=0.6 + jitter)
            db.add(RiderLiveLocation(
                id=uuid.uuid4(), rider_id=rider.id, latitude=lat, longitude=lng,
                accuracy_meters=random.uniform(5.0, 25.0), speed_kmh=random.uniform(0.0, 45.0),
                heading_degrees=random.uniform(0.0, 359.0), recorded_at=ts, created_at=ts,
            ))
            locations_inserted += 1
    await db.flush()
    print(f"   ✅ GPS histórico PO: {locations_inserted} posiciones nuevas (skip duplicados).")

    # ---------------- 4) Snapshots de rutas VRP (skip por delivery_id) ----------------
    import json as _json

    deliveries = (await db.execute(
        select(Delivery).options(_selectinload(Delivery.order)).where(
            Delivery.status.in_([DeliveryStatus.EN_ROUTE, DeliveryStatus.INICIADA])
        ).limit(10)
    )).scalars().all()
    snapshots_created = 0
    for dlv in deliveries:
        exists = (await db.execute(
            select(DeliveryRouteSnapshot.id).where(DeliveryRouteSnapshot.delivery_id == dlv.id)
        )).first()
        if exists:
            continue
        original_km = round(random.uniform(3.5, 9.0), 2)
        optimized_km = round(original_km * random.uniform(0.72, 0.90), 2)
        db.add(DeliveryRouteSnapshot(
            id=uuid.uuid4(), delivery_id=dlv.id,
            optimized_sequence_json=_json.dumps([
                {"seq": 1, "type": "pick_up", "lat": PO_CENTER_LAT, "lng": PO_CENTER_LNG},
                {"seq": 2, "type": "drop_off", "lat": 8.2930, "lng": -62.6380},
            ]),
            original_distance_km=original_km, optimized_distance_km=optimized_km,
            savings_percentage=round((1 - optimized_km / original_km) * 100, 1),
            calculated_at=now, expires_at=now + timedelta(hours=int(getattr(settings, "ROUTE_SNAPSHOT_EXPIRY_HOURS", 24))),
        ))
        snapshots_created += 1
    await db.commit()
    print(f"   ✅ Snapshots VRP: {snapshots_created} creados / {len(deliveries)} entregas evaluadas.")
    print("🛰️  Fase 8 seed OK — Puerto Ordaz (PO-01..PO-04).")


async def seed_fase9_notifications(db: AsyncSession):
    """Fase 9 — Seed idempotente de notificaciones omnicanal.

    Plantillas UPSERT por code, preferencias demo por rol, device tokens dummy
    y logs historicos (skip por dedupe_key). Reusa imports locales por seguridad
    de entorno.
    """
    import hashlib as _hl
    import json as _json9
    from app.models.notification import (
        NotificationChannel, NotificationTemplate, NotificationLog,
        UserDeviceToken, NotificationPreference, OmnichannelStatus,
    )

    # Fuente unica de verdad: TEMPLATES_SEED definida en la migracion Fase 9
    templates_seed = [
        ("payout_aprobado", "PUSH", None,
         "Tu retiro de ${{amount_cents}} fue APROBADO. Se procesara a tu cuenta ****{{bank_last4}}."),
        ("payout_rechazado", "PUSH", None,
         "Tu solicitud de retiro de ${{amount_cents}} fue RECHAZADA. Motivo: {{reason}}"),
        ("payout_fallido", "PUSH", None,
         "El pago de tu retiro de ${{amount_cents}} FALLO. Motivo: {{reason}}. Soporte te contactara."),
        ("nuevo_pedido_asignado", "PUSH", None,
         "Nuevo pedido asignado: entrega {{delivery_code}} de {{customer_name}}. Pago estimado: ${{payment_cents}}."),
        ("alerta_desviacion_ruta", "EMAIL", "Alerta de desviacion de ruta - Delivery360",
         "El rider {{rider_name}} se desvio {{deviation_km}} km de la ruta planificada. "
         "Posicion actual: ({{lat}}, {{lng}}). Ultima actualizacion: {{last_seen}}."),
        ("resumen_diario_manager", "EMAIL", "Resumen diario de operaciones - Delivery360",
         "Buen dia {{manager_name}}. Resumen de ayer: {{total_deliveries}} entregas, "
         "{{completed_count}} completadas, {{failed_count}} falladas, "
         "{{on_time_pct}}% a tiempo."),
    ]
    tpl_created = tpl_updated = 0
    for code, channel, subject, body in templates_seed:
        existing = (await db.execute(
            select(NotificationTemplate).where(NotificationTemplate.code == code)
        )).scalar_one_or_none()
        if existing is None:
            db.add(NotificationTemplate(
                id=uuid.uuid4(), code=code, channel=NotificationChannel(channel),
                subject=subject, body_template=body, language="es", is_active=True,
            ))
            tpl_created += 1
        else:
            # UPSERT suave: reactivar/actualizar solo si el contenido divergio
            changed = (existing.body_template != body or existing.subject != subject
                       or not existing.is_active)
            if changed:
                existing.channel = NotificationChannel(channel)
                existing.subject = subject
                existing.body_template = body
                existing.is_active = True
                tpl_updated += 1
    await db.commit()
    print(f"   Plantillas: {tpl_created} creadas, {tpl_updated} actualizadas, "
          f"{len(templates_seed)} totales evaluadas.")

    # ---------------- 2) Usuarios demo por rol ----------------
    # Corrección auditoría Fase 9: los emails hardcodeados no coincidían con el
    # seed principal (admin@delivery360.com / manager1@...) ni con roles reales
    # (SUPERADMIN no existía), por lo que prefs/tokens/logs quedaban en 0.
    # Estrategia robusta: detectar usuarios ya sembrados; si la DB está vacía,
    # crear usuarios demo mínimos idempotentes (email unique como clave natural).
    demo_users = {}

    async def _find_user_by_roles(emails, roles):
        q = select(User).where(User.email.in_(emails))
        if roles:
            q = q.where(User.role.in_(roles))
        return (await db.execute(q.limit(1))).scalars().first()

    mgr = await _find_user_by_roles(
        ["manager1@delivery360.com", "gerente@delivery360.com"], [UserRole.GERENTE])
    ops = await _find_user_by_roles(
        ["operador1@delivery360.com", "ops@delivery360.com"], None)
    adm = await _find_user_by_roles(
        ["admin@delivery360.com", "super@delivery360.com"],
        [UserRole.SUPERADMIN]) or mgr  # fallback: gerente ejerce de admin-demo

    # Riders con cuenta de usuario (Rider.user_id -> User)
    rider_user = None
    ru_rows = (await db.execute(
        select(User).join(Rider, Rider.user_id == User.id).limit(3)
    )).scalars().all()
    if ru_rows:
        rider_user = ru_rows[0]

    import hashlib as _hl_seed
    from app.core.security import get_password_hash as _get_pwd_hash

    async def _ensure_demo_user(email, role, first_name, last_name):
        """Idempotente por email (unique). Devuelve (User, uid_str) capturado AHORA."""
        nonlocal rider_user
        u = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if u:
            return u, str(u.id)
        new_id = uuid.uuid4()
        u = User(
            id=new_id, email=email,
            hashed_password=_get_pwd_hash("SeedFase9!2026"),
            first_name=first_name, last_name=last_name,
            role=role, is_active=True,
            phone=f"+57300{str(abs(hash(email)) % 9000000 + 1000000)}",
        )
        db.add(u)
        await db.flush()
        if role == UserRole.REPARTIDOR and rider_user is None:
            rider_user = u
        return u, str(new_id)

    uid_map = {}
    if mgr is None:
        mgr, uid_map[UserRole.GERENTE] = await _ensure_demo_user(
            "fase9.manager@delivery360.com", UserRole.GERENTE, "Manager", "Demo F9")
    if ops is None:
        ops, uid_map[UserRole.OPERADOR] = await _ensure_demo_user(
            "fase9.ops@delivery360.com", UserRole.OPERADOR, "Operador", "Demo F9")
    if adm is None:
        adm, uid_map[UserRole.SUPERADMIN] = await _ensure_demo_user(
            "fase9.super@delivery360.com", UserRole.SUPERADMIN, "Superadmin", "Demo F9")
    if rider_user is None:
        rider_user, uid_map[UserRole.REPARTIDOR] = await _ensure_demo_user(
            "fase9.rider@delivery360.com", UserRole.REPARTIDOR, "Rider", "Demo F9")

    demo_users[UserRole.GERENTE] = mgr
    if ops is not mgr:
        demo_users[UserRole.OPERADOR] = ops
    if adm is not None:
        demo_users[UserRole.SUPERADMIN] = adm
    demo_users[UserRole.REPARTIDOR] = rider_user
    # Nota auditoría: NO hacer commit aquí — el script puede correr con sesiones
    # expire_on_commit=True y expiraría user.id (lazy IO → MissingGreenlet).
    # El commit de la sección 3 persiste usuarios+prefs atómicamente.
    # CORRECCIÓN AUDITORÍA FASE 9 (UnboundLocalError): demo_ids debe definirse
    # ANTES de su primer uso en la sección 3. uid_map ya captura los ids como str
    # durante _ensure_demo_user (pre-commit), así que esto es seguro incluso con
    # expire_on_commit=True.
    import hashlib as _hl9
    from uuid import UUID as _UUID9
    demo_ids = {role: _UUID9(uid_map.get(role) or str(u.id))
                for role, u in demo_users.items()}

    # ---------------- 3) Preferencias demo evento x canal ----------------
    pref_events = ["payout_aprobado", "nuevo_pedido_asignado", "alerta_desviacion_ruta"]
    role_channels = {
        UserRole.REPARTIDOR: [NotificationChannel.PUSH, NotificationChannel.IN_APP],
        UserRole.GERENTE: [NotificationChannel.PUSH, NotificationChannel.EMAIL],
        UserRole.SUPERADMIN: [NotificationChannel.PUSH, NotificationChannel.EMAIL],
        UserRole.OPERADOR: [NotificationChannel.IN_APP],
    }
    prefs_created = 0
    for role, user in demo_users.items():
        uid_pref = demo_ids.get(role) or _UUID9(str(user.id))
        for event in pref_events:
            for ch in role_channels.get(role, [NotificationChannel.IN_APP]):
                exists = (await db.execute(
                    select(NotificationPreference.id).where(
                        NotificationPreference.user_id == uid_pref,
                        NotificationPreference.event_code == event,
                        NotificationPreference.channel == ch,
                    )
                )).first()
                if exists:
                    continue
                db.add(NotificationPreference(
                    id=uuid.uuid4(), user_id=uid_pref, event_code=event,
                    channel=ch, enabled=True,
                ))
                prefs_created += 1
    await db.commit()
    print(f"   Preferencias demo: {prefs_created} creadas.")

    # ---------------- 4) Device tokens dummy (web) ----------------
    # demo_ids ya definido al inicio de la sección 3 (corrección UnboundLocalError);
    # ids capturados pre-commit (seguro con expire_on_commit=True); FKs son
    # UUID(as_uuid=True) => objetos uuid.UUID para asyncpg.
    tokens_created = 0
    for role, uid in demo_ids.items():
        # CORRECCIÓN AUDITORÍA: UUID no es subcriptable -> usar str(uid)
        fake_token = f"seed-fcm-{str(uid)[:8]}-web"
        exists = (await db.execute(
            select(UserDeviceToken.id).where(UserDeviceToken.device_token == fake_token)
        )).first()
        if exists:
            continue
        db.add(UserDeviceToken(
            id=uuid.uuid4(), user_id=uid, device_token=fake_token,
            platform="web", failure_count=0, is_active=True,
            last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        tokens_created += 1
    await db.commit()
    print(f"   Device tokens dummy: {tokens_created} creados.")

    # ---------------- 5) Logs historicos (mezcla ENVIADO/LEIDO/FALLIDO) ----------------
    # CORRECCIÓN AUDITORÍA FASE 9 (idempotencia entre ejecuciones): los dedupe_keys
    # de producción dependen de la ventana de 5 min del reloj (time.time()//300),
    # por lo que un seed en otra ventana recreaba filas duplicadas. Estrategia:
    #   - clave canónica de la VENTANA ACTUAL (mismo algoritmo exacto de send()) =>
    #     bloquea el test-send duplicado inmediato exigido por el smoke test;
    #   - además se calcula la clave de una ventana histórica FIJA (época anclada,
    #     estable entre ejecuciones) => si ya existe, se omite el log (dedupe
    #     inter-seed determinista). En repositorios nuevos se insertan las 8 filas
    #     históricas; en repositorios ya sembrados se reportan "8 omitidos".
    now9 = datetime.now(timezone.utc).replace(tzinfo=None)
    import time as _time9  # seed_data importa solo `datetime`; evitar sombra de datetime.time
    _f9_fixed_window_ts = (1_700_000_400.0 // 300) * 300  # ventana histórica fija
    _f9_current_window_ts = (_time9.time() // 300) * 300  # ventana activa (smoke dedupe)
    log_specs = []
    if UserRole.REPARTIDOR in demo_users:
        ru_id = demo_ids[UserRole.REPARTIDOR]
        log_specs += [
            ("payout_aprobado", ru_id, NotificationChannel.PUSH, OmnichannelStatus.ENVIADO, 1,
             {"amount_cents": 15000, "bank_last4": "4321", "status": "APROBADO"}),
            ("payout_rechazado", ru_id, NotificationChannel.PUSH, OmnichannelStatus.LEIDO, 2,
             {"amount_cents": 8000, "reason": "Cuenta bancaria no verificada"}),
            ("nuevo_pedido_asignado", ru_id, NotificationChannel.IN_APP, OmnichannelStatus.LEIDO, 3,
             {"delivery_code": "DLV-SEED-001", "customer_name": "Ana Perez", "payment_cents": 12000}),
            ("nuevo_pedido_asignado", ru_id, NotificationChannel.PUSH, OmnichannelStatus.FALLIDO, 4,
             {"delivery_code": "DLV-SEED-002", "customer_name": "Luis Gomez", "payment_cents": 9000}),
        ]
    if UserRole.GERENTE in demo_users:
        gu_id = demo_ids[UserRole.GERENTE]
        log_specs += [
            ("alerta_desviacion_ruta", gu_id, NotificationChannel.EMAIL, OmnichannelStatus.ENVIADO, 5,
             {"rider_name": "Rider Demo", "deviation_km": 0.8, "lat": 8.29, "lng": -62.73,
              "last_seen": "hace 12 min"}),
            ("resumen_diario_manager", gu_id, NotificationChannel.EMAIL, OmnichannelStatus.LEIDO, 6,
             {"manager_name": "Gerente General", "total_deliveries": 42, "completed_count": 38,
              "failed_count": 2, "on_time_pct": 91.5}),
        ]
    if UserRole.SUPERADMIN in demo_users:
        su_id = demo_ids[UserRole.SUPERADMIN]
        log_specs += [
            ("resumen_diario_manager", su_id, NotificationChannel.IN_APP, OmnichannelStatus.ENVIADO, 7,
             {"manager_name": "Super Admin", "total_deliveries": 42, "completed_count": 38,
              "failed_count": 2, "on_time_pct": 91.5}),
            ("payout_aprobado", su_id, NotificationChannel.IN_APP, OmnichannelStatus.LEIDO, 8,
             {"amount_cents": 25000, "bank_last4": "9876", "status": "APROBADO"}),
        ]

    # CORRECCIÓN AUDITORÍA FASE 9 (smoke test dedupe): los logs semilla usaban un
    # prefijo "seed:" con hash propio que NO colisionaba con la clave de producción
    # build_dedupe_key(template_code, entity='global') + ":canal", por lo que un
    # test-send inmediato tras el seed creaba un segundo log (dedupe roto).
    # Ahora se replica EXACTAMENTE la clave de send(). Como send() solo dedupea
    # dentro de la ventana activa de 5 min, las plantillas repetidas en la misma
    # ventana se desplazan a la ventana anterior (mantiene 8 filas históricas y
    # sigue bloqueando el test-send duplicado inmediato).
    from app.services.omnichannel_service import (
        build_dedupe_key as _f9_build_dedupe,
        render_template as render_template,
    )

    logs_created = logs_skipped = 0
    _f9_used_keys = set()
    _f9_tpl_body = {c: b for c, _ch, _s, b in templates_seed}
    _f9_tpl_subj = {c: s for c, _ch, s, _b in templates_seed}
    for code, uid, ch, status_, seq, ctx in log_specs:
        # Clave histórica FIJA (estable entre ejecuciones del seed) — si ya fue
        # sembrada en una corrida anterior, se omite (idempotencia real).
        fixed_key = f"{_f9_build_dedupe(code, None, window_ts=_f9_fixed_window_ts)}:{ch.value}"
        if fixed_key in _f9_used_keys or (await db.execute(
            select(NotificationLog.id).where(NotificationLog.dedupe_key == fixed_key)
        )).first():
            logs_skipped += 1
            continue
        # Clave canónica de la VENTANA ACTUAL con el algoritmo EXACTO de send():
        # bloquea el test-send duplicado inmediato (smoke dedupe). Si colisiona
        # con otra fila del lote, se desplaza a la ventana previa.
        dedupe = f"{_f9_build_dedupe(code, None, window_ts=_f9_current_window_ts)}:{ch.value}"
        if dedupe in _f9_used_keys:
            dedupe = f"{_f9_build_dedupe(code, None, window_ts=_f9_current_window_ts - 300)}:{ch.value}"
        _f9_used_keys.add(dedupe)
        _f9_used_keys.add(fixed_key)
        exists = (await db.execute(
            select(NotificationLog.id).where(NotificationLog.dedupe_key == dedupe)
        )).first()
        if exists:
            logs_skipped += 1
            continue
        created = now9 - timedelta(days=(seq % 7) + 1, hours=seq)
        # Render con el MISMO motor de producción: body legible en el inbox
        # (no JSON crudo) y title = subject renderizado si existe.
        _f9_body = render_template(_f9_tpl_body.get(code, ""), ctx)
        _f9_subj = _f9_tpl_subj.get(code)
        title = (render_template(_f9_subj, ctx) if _f9_subj
                 else code.replace("_", " ").capitalize())
        db.add(NotificationLog(
            id=uuid.uuid4(), user_id=uid, template_code=code,
            channel=ch, status=status_,
            payload_json=_json9.dumps(ctx, default=str),
            dedupe_key=dedupe, title=title[:255],
            body=_f9_body,
            retry_count=1 if status_ == OmnichannelStatus.FALLIDO else 0,
            error_message="Provider stub reporto fallo (dato historico demo)"
                          if status_ == OmnichannelStatus.FALLIDO else None,
            provider_message_id=f"stub-{seq:04d}" if status_ != OmnichannelStatus.FALLIDO else None,
            created_at=created,
            sent_at=created if status_ != OmnichannelStatus.PENDIENTE else None,
            delivered_at=created if status_ in (OmnichannelStatus.ENVIADO, OmnichannelStatus.LEIDO,
                                                OmnichannelStatus.ENTREGADO) else None,
            read_at=created + timedelta(hours=1) if status_ == OmnichannelStatus.LEIDO else None,
        ))
        logs_created += 1
    await db.commit()
    print(f"   Logs historicos: {logs_created} creados, {logs_skipped} omitidos (dedupe).")
    print("\U0001f514 Fase 9 seed OK — Notificaciones omnicanal.")


async def seed_fase10_fiscal(db: AsyncSession):
    """FASE 10: Facturación Electrónica & Motor Fiscal — demo dataset idempotente.

    Nota: las 2 resoluciones y las 6 reglas fiscales YA existen porque la
    migración alembic 20260930_fase10 las siembra con ON CONFLICT DO NOTHING.
    Aquí solo se generan datos DEMO de las tablas transaccionales:
      - electronic_invoices            (facturas sobre órdenes entregadas)
      - payment_distribution_snapshots (split plataforma/rider por orden)
      - bank_reconciliation_records    (extracto bancario demo)
    Idempotencia: UNIQUE constraints + chequeos previos; correr 2x deja los
    mismos conteos. Montos SIEMPRE en centavos (BigInteger)."""
    print("\n🧾 Sembrando datos Fase 10 (Facturación Electrónica — demo)...")

    # 1) Verificar prerequisitos creados por la migración (no duplicar seeds)
    res_count = (await db.execute(text(
        "SELECT count(*) FROM invoice_resolutions WHERE is_active = TRUE"
    ))).scalar() or 0
    cfg_count = (await db.execute(text(
        "SELECT count(*) FROM fiscal_configurations WHERE is_active = TRUE"
    ))).scalar() or 0
    if res_count == 0 or cfg_count == 0:
        print("   ⚠️  Faltan resoluciones/reglas fiscales — ejecuta primero: alembic upgrade head")
        return
    print(f"   ✔ Prerrequisitos migración: {res_count} resoluciones, {cfg_count} reglas fiscales activas.")

    # 2) Contadores de secuencia por resolución (evita colisión con el stub DIAN)
    resolutions = (await db.execute(text(
        "SELECT id::text, prefix, current_counter, start_range, end_range "
        "FROM invoice_resolutions WHERE country_code = 'CO' AND is_active = TRUE "
        "ORDER BY created_at LIMIT 1"
    ))).mappings().first()
    if not resolutions:
        print("   ⚠️  Sin resolución CO activa; se omite facturación demo.")
        return
    seq = max(int(resolutions["current_counter"] or 0), 0)

    # 3) Órdenes ENTREGADAS sin factura → generar hasta 10 facturas demo ACEPTADA
    orders_missing = (await db.execute(text(
        "SELECT o.id::text AS oid, o.total "
        "FROM orders o "
        "JOIN deliveries d ON d.order_id = o.id "
        "WHERE d.status = 'COMPLETADA' "
        "  AND NOT EXISTS (SELECT 1 FROM electronic_invoices ei WHERE ei.order_id = o.id) "
        "ORDER BY o.created_at LIMIT 10"
    ))).mappings().all()

    invoices_created = 0
    for row in orders_missing:
        total_cents = int(round(row["total"] * 100)) if row["total"] is not None else 0
        if total_cents <= 0:
            continue
        seq += 1
        if seq > int(resolutions["end_range"]):
            break
        # Desgaste CO: IVA 19% incluido implícito -> neto = total / 1.19 (centavos exactos)
        tax_cents = total_cents - round(total_cents / 1.19)
        subtotal_cents = total_cents - tax_cents
        await db.execute(text(
            "INSERT INTO electronic_invoices "
            "(id, order_id, invoice_type, resolution_number, sequence_number, unique_identifier, "
            " issue_date, issue_time, provider_type, currency_code, exchange_rate, "
            " subtotal_cents, tax_total_cents, retention_total_cents, discount_total_cents, "
            " grand_total_cents, status, customer_info_json, created_at, updated_at) "
            "VALUES (gen_random_uuid(), CAST(:oid AS uuid), 'VENTA', :resnum, :seq, :uid, "
            " CURRENT_DATE, LOCALTIME, 'CO', 'COP', 1, "
            " :sub, :tax, 0, 0, :tot, 'ACEPTADA', '{}', NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC') "
            "ON CONFLICT (provider_type, resolution_number, sequence_number) DO NOTHING"
        ), {
            "oid": row["oid"], "resnum": 1, "seq": seq,
            "uid": f"SEED-{resolutions['prefix']}{seq:08d}",
            "sub": subtotal_cents, "tax": tax_cents, "tot": total_cents,
        })
        invoices_created += 1

    # Avanzar el contador de la resolución para no re-usar secuencias en runtime
    if invoices_created:
        await db.execute(text(
            "UPDATE invoice_resolutions SET current_counter = :c, updated_at = NOW() AT TIME ZONE 'UTC' "
            "WHERE id = CAST(:rid AS uuid) AND current_counter < :c"
        ), {"rid": resolutions["id"], "c": seq})

    # 4) Snapshots de distribución (split plataforma/rider) para las mismas órdenes
    dist_created = 0
    for row in orders_missing[:invoices_created]:
        gross = int(round(row["total"] * 100)) if row["total"] is not None else 0
        if gross <= 0:
            continue
        rider_share = round(gross * 0.70)   # demo: 70% rider / 30% plataforma
        platform_share = gross - rider_share
        r = await db.execute(text(
            "INSERT INTO payment_distribution_snapshots "
            "(id, order_id, gross_amount_cents, platform_share_cents, restaurant_share_cents, "
            " rider_share_cents, applied_rule_json, settled_at) "
            "VALUES (gen_random_uuid(), CAST(:oid AS uuid), :gross, :plat, 0, :rider, "
            " '{\"demo_seed\":true,\"rule\":\"70/30\"}', NOW() AT TIME ZONE 'UTC') "
            "ON CONFLICT (order_id) DO NOTHING"
        ), {"oid": row["oid"], "gross": gross, "plat": platform_share, "rider": rider_share})
        dist_created += r.rowcount

    # 5) Registros de conciliación bancaria demo (mezcla de estados)
    recon_created = 0
    tx_rows = (await db.execute(text(
        "SELECT ft.id::text AS tid, ft.amount_cents, ft.created_at "
        "FROM financial_transactions ft "
        "WHERE ft.amount_cents > 0 "
        "  AND NOT EXISTS (SELECT 1 FROM bank_reconciliation_records brr "
        "                  WHERE brr.internal_transaction_id = ft.id) "
        "ORDER BY ft.created_at DESC LIMIT 6"
    ))).mappings().all()
    statuses = ["RELACIONADO", "SIN_RELACIONAR", "VARIANCIA"]
    for i, tx in enumerate(tx_rows):
        amount_cents = int(tx["amount_cents"])
        status = statuses[i % len(statuses)]
        matched = amount_cents if status == "RELACIONADO" else (
            amount_cents - 500 if status == "VARIANCIA" else None)
        variance = (amount_cents - matched) if matched is not None else amount_cents
        r = await db.execute(text(
            "INSERT INTO bank_reconciliation_records "
            "(id, statement_date, bank_reference, internal_transaction_id, statement_amount_cents, "
            " matched_amount_cents, variance_cents, match_confidence_score, status, resolved_manually, "
            " notes, created_at) "
            "VALUES (gen_random_uuid(), CURRENT_DATE - INTERVAL '1 day', :ref, CAST(:tid AS uuid), "
            " :stmt, :matched, :var, :conf, CAST(:st AS reconciliationstatus), FALSE, "
            " 'Demo seed Fase 10', NOW() AT TIME ZONE 'UTC')"
        ), {
            "ref": f"SEED-BANK-{uuid.uuid4().hex[:10].upper()}", "tid": tx["tid"],
            "stmt": amount_cents, "matched": matched, "var": variance,
            "conf": 0.95 if status != "SIN_RELACIONAR" else None, "st": status,
        })
        recon_created += r.rowcount

    await db.commit()
    print(f"   ✅ Facturas demo: {invoices_created} nuevas. Splits: {dist_created} nuevos. "
          f"Conciliaciones: {recon_created} nuevas.")
    print("🧾 Fase 10 seed OK — Facturación electrónica demo.")


async def main():
    print("🚀 INICIANDO SEED DATA AVANZADO (CON ZONAS, VEHÍCULOS Y ALERTAS)")
    async with AsyncSessionLocal() as db:
        try:
            # Asegurar que los tipos de transacción existan antes de cualquier inserción
            await ensure_transaction_types(db)
            
            users = await seed_users(db)
            zones = await seed_zones(db)
            await seed_platform_settings(db, zones)
            
            # FASE 3: Sembrar multiplicadores de bono en zonas
            await seed_zones_with_multipliers(db)
            
            # NUEVO: Sembrar vehículos PRIMERO para que estén disponibles al crear riders
            vehicles = await seed_vehicles(db, users, [], count=25)
            
            # FASE 4: Sembrar riders con soporte para vehículos propios y de empresa
            riders = await seed_riders(db, zones, vehicles)
            
            # Actualizar vehículos asignados a riders (para los que son PROPIO)
            await seed_vehicles(db, users, riders, count=25)
            
            await seed_shifts(db, riders)
            
            orders = await seed_orders_and_complex_data(db, riders, count=60)
            live_map_orders = await seed_live_map_demo_data(db, riders)
            orders = orders + live_map_orders
            await seed_demo_payouts(db, riders)
            await seed_alerts(db, orders, riders)
            await seed_audit_logs(db)

            # FASE 8: Mapas & Tracking — zonas Puerto Ordaz (PO-01..PO-04),
            # GPS histórico simulado y snapshots VRP (idempotente)
            await seed_fase8_tracking(db)
            

            # FASE 9: Notificaciones omnicanal — plantillas UPSERT por code,
            # preferencias demo por rol, logs históricos y device tokens dummy
            # (idempotente: skip por dedupe_key / unique constraints)
            await seed_fase9_notifications(db)

            # FASE 10: Facturación Electrónica & Motor Fiscal — facturas/splits/
            # conciliaciones demo sobre órdenes entregadas (idempotente; los
            # seeds maestros de resoluciones y reglas ya están en la migración)
            await seed_fase10_fiscal(db)
            print("\n✅ ¡SEED COMPLETADO CON ÉXITO!")
            print("\n🔐 CREDENCIALES:")
            print("   Superadmin: super@delivery360.com / Admin123!")
            print("\n💡 DATOS GENERADOS:")
            print("   - Usuarios, Zonas, Riders, Vehículos (Flota)")
            print("   - Órdenes, Entregas, Finanzas, Productividad")
            print("   - Entregas activas con GPS para /operator/live-map")
            print("   - Turnos demo para /operator/shifts")
            print("   - Alertas Operacionales Reales para usuarios operativos")
            print("   - Configuración global (Fases 1, 2, 3):")
            print("     * rider_delivery_bonus = 2500 COP")
            print("     * rider_failed_attempt_bonus = 1500 COP")
            print("     * bonus_multiplier en zonas (NRT=1.5x, SUR=1.2x, etc.)")
            print("   - Retiros e historial/auditoría demo")
            
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
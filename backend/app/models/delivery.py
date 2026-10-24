"""Delivery model."""

import uuid
from decimal import Decimal
from datetime import datetime, timezone  # CORREGIDO
from app.core.json_types import JsonValue
from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Text,
    text,
    Boolean,
    JSON,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.core.database import Base


def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive) para compatibilidad con PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DeliveryStatus(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    INICIADA = "INICIADA"
    EN_PICKUP = "EN_PICKUP"
    EN_ROUTE = "EN_ROUTE"
    EN_DESTINO = "EN_DESTINO"
    COMPLETADA = "COMPLETADA"
    FALLIDA = "FALLIDA"


class ProofType(str, enum.Enum):
    FOTO = "FOTO"
    FIRMA = "FIRMA"
    OTP = "OTP"
    NINGUNO = "NINGUNO"


class DeliveryFailureCause(str, enum.Enum):
    """
    Causas estandarizadas para entregas fallidas.
    Determina automáticamente si el repartidor recibe bono por intento fallido.
    """

    # === CAUSAS EXTERNAS (BONIFICABLES - 1500 COP) ===
    CLIENTE_NO_ESTA = "CLIENTE_NO_ESTA"
    CLIENTE_NO_CONTESTA = "CLIENTE_NO_CONTESTA"
    DIRECCION_INCORRECTA = "DIRECCION_INCORRECTA"
    DIRECCION_NO_EXISTE = "DIRECCION_NO_EXISTE"
    COMERCIO_CERRADO = "COMERCIO_CERRADO"
    CLIENTE_RECHAZA = "CLIENTE_RECHAZA"
    ZONA_INSEGURA = "ZONA_INSEGURA"
    FUERZA_MAYOR = "FUERZA_MAYOR"
    EDIFICIO_RESTRINGIDO = "EDIFICIO_RESTRINGIDO"

    # === CAUSAS DEL REPARTIDOR (NO BONIFICABLES) ===
    REPARTIDOR_NO_QUIERE_ENTREGAR = "REPARTIDOR_NO_QUIERE_ENTREGAR"
    REPARTIDOR_LLEGO_TARDE = "REPARTIDOR_LLEGO_TARDE"
    REPARTIDOR_ERROR_PROPIO = "REPARTIDOR_ERROR_PROPIO"
    REPARTIDOR_VEHICULO_FALLA = "REPARTIDOR_VEHICULO_FALLA"
    REPARTIDOR_SIN_BATERIA = "REPARTIDOR_SIN_BATERIA"
    OTRO_REPARTIDOR = "OTRO_REPARTIDOR"

    @property
    def is_bonificable(self) -> bool:
        """Determina si esta causa da derecho al bono por intento fallido."""
        return check_is_bonificable(self)


def get_bonificable_causes() -> list[str]:
    """Retorna lista de valores de causas bonificables."""
    return [
        "CLIENTE_NO_ESTA",
        "CLIENTE_NO_CONTESTA",
        "DIRECCION_INCORRECTA",
        "DIRECCION_NO_EXISTE",
        "COMERCIO_CERRADO",
        "CLIENTE_RECHAZA",
        "ZONA_INSEGURA",
        "FUERZA_MAYOR",
        "EDIFICIO_RESTRINGIDO",
    ]


def check_is_bonificable(cause: "DeliveryFailureCause") -> bool:
    """
    Función helper para verificar si una causa es bonificable.

    Args:
        cause: Instancia de DeliveryFailureCause

    Returns:
        True si la causa da derecho al bono por intento fallido
    """
    if isinstance(cause, DeliveryFailureCause):
        return cause.value in get_bonificable_causes()
    return False


class LockedBonusType(str, enum.Enum):
    """Tipos de bono que pueden ser congelados en un snapshot financiero."""

    SUCCESS = "SUCCESS"  # Bono por entrega completada exitosamente
    FAILED_ATTEMPT = "FAILED_ATTEMPT"  # Bono por intento fallido bonificable


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
        nullable=False,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("riders.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
    )

    status: Mapped[DeliveryStatus | None] = mapped_column(
        SQLEnum(DeliveryStatus), default=DeliveryStatus.PENDIENTE, nullable=True
    )

    # CORREGIDO
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arrived_pickup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    left_pickup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arrived_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    current_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_location_update: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    route_data: Mapped[JsonValue] = mapped_column(JSON, nullable=True)
    distance_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_pickup: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_delivery: Mapped[float | None] = mapped_column(Float, nullable=True)

    proof_type: Mapped[ProofType | None] = mapped_column(
        SQLEnum(ProofType), nullable=True
    )
    proof_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    proof_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_otp: Mapped[str | None] = mapped_column(String(10), nullable=True)
    proof_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_name_received: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    has_issues: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    failure_cause: Mapped[DeliveryFailureCause | None] = mapped_column(
        SQLEnum(DeliveryFailureCause), nullable=True
    )  # Nuevo campo ENUM estandarizado
    issue_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Se mantiene para compatibilidad pero se depreca
    issue_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_resolved: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    issue_analysis_result: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Resultado del análisis de causa (externa/interna)

    time_to_pickup: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_at_pickup: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_to_delivery: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_time: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sla_expected_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_compliant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # =============================================================================
    # SNAPSHOT FINANCIERO INMUTABLE (Fase 3 - Inmutabilidad Financiera)
    # =============================================================================
    # Estos campos se congelan en el momento exacto de transición a estado terminal
    # (COMPLETADA o FALLIDA) y NUNCA deben modificarse después.

    # Monto exacto del bono aplicado, congelado al momento del cierre
    locked_bonus_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Monto del bono congelado en el momento de finalizar la entrega. Inmutable.",
    )

    # Tipo de bono aplicado: SUCCESS (entrega completada) o FAILED_ATTEMPT (fallida bonificable)
    locked_bonus_type: Mapped[LockedBonusType | None] = mapped_column(
        SQLEnum(LockedBonusType),
        nullable=True,
        comment="Tipo de bono congelado. Inmutable.",
    )

    # Timestamp exacto del congelamiento del bono
    bonus_snapshot_date: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="Fecha y hora exacta en que se congeló el bono. Inmutable.",
    )

    # Alerta de configuración faltante en el momento del snapshot (para auditoría)
    bonus_config_warning_snapshot: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Mensaje de alerta sobre configuración faltante en el momento del snapshot. Para auditoría.",
    )

    # FASE 5: Componentes del cálculo del bono para desglose visual
    locked_bonus_base: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Bono base configurado al momento del cálculo. Para desglose frontend.",
    )
    locked_bonus_zone_multiplier: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        nullable=True,
        comment="Multiplicador de zona aplicado. Para desglose frontend.",
    )
    locked_bonus_tier_multiplier: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        nullable=True,
        comment="Multiplicador de tier aplicado. Para desglose frontend.",
    )
    locked_bonus_tier_level: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Nivel del rider (BRONCE/PLATA/ORO/PLATINO) al momento del cálculo.",
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=True
    )

    order = relationship("Order", back_populates="delivery")
    rider = relationship("Rider", back_populates="deliveries", foreign_keys=[rider_id])
    route = relationship(
        "Route",
        back_populates="delivery",
        uselist=False,
        primaryjoin="Delivery.id == foreign(Route.delivery_id)",
        foreign_keys="[Route.delivery_id]",
    )

    def __repr__(self):
        return f"<Delivery(id={self.id}, order={self.order_id}, status={self.status})>"

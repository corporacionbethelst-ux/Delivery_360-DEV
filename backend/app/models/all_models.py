# backend/app/models/all_models.py
"""
Central import point for all SQLAlchemy models.
Import this module to ensure all models are registered with the Base metadata.
"""

from app.models.user import User
from app.models.rider import Rider
from app.models.vehicle import Vehicle  # ✅ AÑADIDO: Vehicle debe importarse aquí
from app.models.zone import Zone
from app.models.platform_setting import PlatformSetting
from app.models.order import Order
from app.models.delivery import Delivery, DeliveryStatus, ProofType
from app.models.payout import Payout, PayoutStatus, PayoutMethod, PayoutStatusHistory
from app.models.route import Route, RoutePoint, RouteDeviation, RouteStatus

# Registro explícito de modelos requeridos por el paquete.
from app.models.shift import Shift, ShiftStatus, CheckInOut

from app.models.financial import (
    Financial,
    FinancialTransaction,
    TransactionType,
    PaymentStatus,
)

from app.models.productivity import ProductivityRecord, MetricType

from app.models.audit_log import AuditLog, AuditAction, ActionType

from app.models.notification import (
    Notification,
    NotificationType,
    NotificationPriority,
    Alert,
)

from app.models.integration import Integration, IntegrationType, IntegrationStatus

# Exportaciones de compatibilidad.
__all__ = [
    "User",
    "Rider",
    "Vehicle",  # ✅ AÑADIDO
    "Zone",
    "PlatformSetting",
    "Order",
    "Delivery",
    "DeliveryStatus",
    "ProofType",
    "Payout",
    "PayoutStatus",
    "PayoutMethod",
    "PayoutStatusHistory",
    "Route",
    "RoutePoint",
    "RouteDeviation",
    "RouteStatus",
    # Modelos requeridos
    "Shift",
    "ShiftStatus",
    "CheckInOut",
    "Financial",
    "FinancialTransaction",
    "TransactionType",
    "PaymentStatus",
    "ProductivityRecord",
    "MetricType",
    "AuditLog",
    "AuditAction",
    "ActionType",
    "Notification",
    "NotificationType",
    "NotificationPriority",
    "Alert",
    "Integration",
    "IntegrationType",
    "IntegrationStatus",
]

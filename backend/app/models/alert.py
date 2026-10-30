"""
Delivery360 - Modelo de Alerta (Alias de Notification para compatibilidad)
Las alertas operacionales se almacenan en la tabla de notificaciones con tipo específico.
"""

from enum import Enum


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    NUEVA = "NUEVA"
    EN_PROCESO = "EN_PROCESO"
    RESUELTA = "RESUELTA"
    DESCARTADA = "DESCARTADA"


class AlertType(str, Enum):
    RETRASO_SLA = "RETRASO_SLA"
    ENTREGA_FALLIDA = "ENTREGA_FALLIDA"
    INCIDENCIA_VEHICULO = "INCIDENCIA_VEHICULO"
    SISTEMA = "SISTEMA"
    PAGO = "PAGO"
    RIDER = "RIDER"


# One canonical mapping: importing this compatibility path must not declare a
# second alerts table or the reserved DeclarativeBase.metadata attribute.
from app.models.notification import Alert as Alert

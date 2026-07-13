"""
Configuración de Sentry para error tracking
"""
from typing import Any, Optional, Union, Dict, List
from datetime import datetime, date, timedelta
from decimal import Decimal
import sentry_sdk
from app.core.config import settings


def setup_sentry(
    dsn: Optional[str] = None,
    environment: str = "development",
    traces_sample_rate: float = 0.1,
    send_default_pii: bool = False
):
    """
    Configurar Sentry para monitoreo de errores
    
    Args:
        dsn: DSN de Sentry (URL del proyecto)
        environment: Entorno (development, staging, production)
        traces_sample_rate: Porcentaje de transacciones a muestrear (0.0 a 1.0)
        send_default_pii: Enviar información personal identificable
    """
    
    dsn = dsn or settings.SENTRY_DSN
    
    if not dsn:
        print("Sentry DSN no configurado. Error tracking deshabilitado.")
        return
    
    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            RedisIntegration(),
            CeleryIntegration(),
        ],
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=send_default_pii,
        profiles_sample_rate=0.1,  # Performance profiling
        _experiments={
            "continuous_profiling_auto_start": True,
        },
    )
    
    print(f"Sentry configurado: environment={environment}")


def set_user_context(user_id: str, email: Optional[str] = None, username: Optional[str] = None):
    """Establecer contexto de usuario para debugging"""
    sentry_sdk.set_user({
        "id": user_id,
        "email": email,
        "username": username,
    })


def set_tag(key: str, value: str):
    """Agregar tag para filtrado de eventos"""
    sentry_sdk.set_tag(key, value)


def set_extra(key: str, value: Any):
    """Agregar información adicional al evento"""
    sentry_sdk.set_extra(key, value)


def capture_exception(exception: Exception, **kwargs):
    """Capturar excepción manualmente"""
    sentry_sdk.capture_exception(exception, **kwargs)


def capture_message(message: str, level: str = "info"):
    """Capturar mensaje manualmente"""
    sentry_sdk.capture_message(message, level=level)

"""Configuración de Sentry para monitoreo y tracking de errores en producción"""

import sentry_sdk
from app.core.config import settings


def init_sentry():
    """Inicializar SDK de Sentry para capturar errores y métricas de rendimiento
    
    # environment: Entorno donde se ejecuta la aplicación (development, staging, production)
    # traces_sample_rate: Porcentaje de transacciones a muestrear (0.0 a 1.0)
    # profiles_sample_rate: Porcentaje de perfiles de rendimiento a capturar
    # send_default_pii: Enviar información personal identificable (debe ser False en prod)
    """
    if not settings.SENTRY_DSN:
        return
    
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=1.0 if settings.ENVIRONMENT == "development" else 0.1,
        profiles_sample_rate=1.0 if settings.ENVIRONMENT == "development" else 0.1,
        send_default_pii=False,
        integrations=[
            sentry_sdk.integrations.fastapi.FastApiIntegration(),
            sentry_sdk.integrations.sqlalchemy.SqlalchemyIntegration(),
        ],
    )

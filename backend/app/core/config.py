from pydantic_settings import BaseSettings
from typing import List, Optional
import json
from pydantic import Field


class Settings(BaseSettings):
    """
    Clase de configuración global de la aplicación
    """

    # --- CONFIGURACIÓN GENERAL DE LA APLICACIÓN ---
    APP_NAME: str = "Delivery360"
    APP_VERSION: str = "1.2.3"  # Actualizado con los nuevos lotes
    APP_ENV: str = "development"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False  # Cambiado a False para producción
    SECRET_KEY: str

    # --- NUEVO: URL del Frontend para enlaces de recuperación ---
    FRONTEND_URL: str = "http://localhost:3000"

    @property
    def is_secret_key_default(self) -> bool:
        return (
            self.SECRET_KEY
            == "CHANGE-THIS-SECRET-KEY-IN-PRODUCTION-MIN-32-CHARS-RANDOM!"
        )

    # --- CONFIGURACIÓN DE API ---
    API_V1_STR: str = "/api/v1"
    BACKEND_CORS_ORIGINS: str = '["http://localhost:3000"]'

    @property
    def cors_origins(self) -> List[str]:
        try:
            return json.loads(self.BACKEND_CORS_ORIGINS)
        except (json.JSONDecodeError, TypeError):
            return ["http://localhost:3000"]

    # --- CONFIGURACIÓN DE BASE DE DATOS ---
    POSTGRES_DB: str = "delivery360"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5432"
    DATABASE_URL: str = ""
    DATABASE_URL_SYNC: str = ""

    @property
    def database_url_computed(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def database_url_sync_computed(self) -> str:
        if self.DATABASE_URL_SYNC:
            return self.DATABASE_URL_SYNC
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # --- CONFIGURACIÓN DE REDIS ---
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: str = "6379"

    # --- CONFIGURACIÓN DE CACHÉ ---
    CACHE_ENABLED: bool = True
    CACHE_DEFAULT_TTL_SECONDS: int = 300  # 5 minutos
    CACHE_ORDER_TTL_SECONDS: int = 120  # 2 minutos para órdenes
    CACHE_RIDER_TTL_SECONDS: int = 60  # 1 minuto para repartidores
    CACHE_DASHBOARD_TTL_SECONDS: int = 180  # 3 minutos para dashboard

    # --- CONFIGURACIÓN DE AUTENTICACIÓN JWT ---
    ALGORITHM: str = "HS256"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @property
    def jwt_algorithm_computed(self) -> str:
        return self.JWT_ALGORITHM or self.ALGORITHM

    # --- CONFIGURACIÓN DE CELERY ---
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # --- CONFIGURACIÓN DE PROTECCIÓN DE DATOS (LGPD) ---
    LGPD_RETENTION_DAYS: int = 1825
    DATA_RETENTION_DAYS: int = 90

    @property
    def retention_days_computed(self) -> int:
        return (
            self.LGPD_RETENTION_DAYS
            if self.LGPD_RETENTION_DAYS
            else self.DATA_RETENTION_DAYS
        )

    # --- CONFIGURACIÓN DE RATE LIMITING ---
    RATE_LIMIT_PER_MINUTE: int = 60

    # --- CONFIGURACIÓN DE USUARIO INICIAL (SEED) ---
    FIRST_SUPERUSER_EMAIL: str = "admin@delivery360.com"
    FIRST_SUPERUSER_PASSWORD: Optional[str] = None
    FIRST_SUPERUSER_NAME: str = "Administrador"

    # --- CONFIGURACIÓN DE MONITOREO Y LOGGING ---
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: Optional[str] = None

    # --- CONFIGURACIONES OPCIONALES ---
    GOOGLE_MAPS_API_KEY: Optional[str] = None
    MAPBOX_API_KEY: Optional[str] = None

    # --- FASE 8: MAPAS & TRACKING REAL-TIME ---
    WS_HEARTBEAT_INTERVAL_SEC: int = 30
    # Alias con nombre de especificación (WEBSOCKET_...) para compatibilidad.
    WEBSOCKET_HEARTBEAT_INTERVAL_SEC: int = 30
    # Límite de tiempo del solver VRP (ms) usado por route_optimizer.
    ROUTE_OPTIMIZER_TIME_LIMIT_MS: int = 5000
    WS_MAX_CONNECTIONS: int = 1000
    REDIS_PUBSUB_CHANNEL_PREFIX: str = "rider_location_updates"
    LIVE_LOCATION_RETENTION_DAYS: int = 7
    ROUTE_SNAPSHOT_EXPIRY_HOURS: int = 24
    VRP_CACHE_TTL_MINUTES: int = 30
    ROUTE_OPTIMIZATION_INTERVAL_SEC: int = 300  # cron interno VRP: 5 min
    MAX_POSITION_UPDATES_PER_MINUTE: int = 20
    AVG_RIDER_SPEED_KMH: float = 18.0  # fallback ETA sin Google Distance Matrix
    EMAILS_ENABLED: bool = False
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    # Recuperación: STARTTLS (587) o TLS implícito (465), nunca ambos ni texto plano.
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: float = 10.0
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAIL_FROM: str = "noreply@delivery360.com"

    # --- FASE 9: NOTIFICACIONES & COMUNICACIÓN OMNICANAL ---
    # External channels never claim success without provider acceptance.
    NOTIFICATIONS_ENABLED: bool = True
    NOTIFICATION_PROVIDER_TIMEOUT_SECONDS: float = Field(
        default=10.0, ge=1, le=60, allow_inf_nan=False
    )
    NOTIFICATION_PROVIDER_CONCURRENCY: int = Field(default=4, ge=1, le=16)
    NOTIFICATION_MAX_RETRIES: int = 3
    NOTIFICATION_RETRY_BACKOFF_SEC: int = 60  # base exponencial: 60,120,240s
    NOTIFICATION_RETENTION_DAYS: int = 30  # purge_old_logs
    NOTIFICATION_TEMPLATE_CACHE_TTL_SEC: int = 3600  # cache Redis plantillas 1h
    NOTIFICATION_RATE_LIMIT_PER_MIN: int = 10  # eventos/min por usuario
    # Canal Pub/Sub de fan-out WS: notifications:user:{id}
    REDIS_NOTIF_CHANNEL_PREFIX: str = "notifications:user"
    # Push (FCM) — opcionales
    FCM_PROJECT_ID: Optional[str] = None
    FCM_CREDENTIALS_JSON_PATH: Optional[str] = None
    # SMS (Twilio) — opcionales
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM_NUMBER: Optional[str] = None
    # Email transaccional Fase 9 — reutiliza SMTP_*; FROM propio con fallback
    NOTIFICATION_EMAIL_FROM: Optional[str] = None

    @property
    def notification_email_from_computed(self) -> str:
        return self.NOTIFICATION_EMAIL_FROM or self.EMAIL_FROM

    # ════════════════════════════════════════════════════════════
    # FASE 10 — Facturación Electrónica & Motor Fiscal
    # No se emite ni simula aceptación fiscal por defecto.
    ENABLE_ELECTRONIC_INVOICING: bool = False
    FISCAL_SANDBOX_ENABLED: bool = False  # previews explícitos, nunca en producción
    FISCAL_DEFAULT_COUNTRY: str = "CO"  # régimen por defecto (ISO alfa-2)
    COMPANY_NIT: str = "900000000-1"  # NIT/RFC emisor demo
    COMPANY_NAME: str = "Delivery360 S.A.S."
    COMPANY_ADDRESS: str = "Bogotá D.C., Colombia"
    COMPANY_CITY_CODE: str = "11001"  # código DANE Bogotá
    INVOICE_DAILY_LIMIT: int = 500  # protección anti-fraude emisión/día
    # Material configurado para futuras integraciones homologadas; no activa transporte.
    DIAN_API_KEY: Optional[str] = None
    DIAN_CERTIFICATE_PATH: Optional[str] = None
    DIAN_PASSWORD: Optional[str] = None
    SAT_API_ENDPOINT: Optional[str] = None
    SAT_CERT_FILE: Optional[str] = None
    SAT_KEY_FILE: Optional[str] = None
    # Multi-moneda / FX
    EXCHANGE_RATE_PROVIDER: str = "stub"  # stub | openexchangerates
    OPEN_EXCHANGE_RATES_APP_ID: Optional[str] = None
    FX_CACHE_TTL_MINUTES: int = 60
    FX_FALLBACK_RATES_JSON: str = (
        '{"COP":3900.0,"MXN":17.0,"CLP":950.0,"PEN":3.75,"USD":1.0}'
    )
    # Split payments (regla global; override por zona vía platform_settings)
    PLATFORM_COMMISSION_PCT: float = 20.0  # % de la tarifa de envío para plataforma
    # Reconciliación bancaria
    RECONCILIATION_VARIANCE_ALERT_CENTS: int = 100  # variance > 1.00 → VARIANCIA
    # Cifrado de secretos locales (AES-256-GCM); dev default NO es seguro
    ENCRYPTION_MASTER_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()  # type: ignore[call-arg]

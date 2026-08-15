
### 13.4 Protección de Datos Sensibles

**Encriptación de datos sensibles:**
```python
from cryptography.fernet import Fernet

# Para datos como números de cuenta bancaria, documentos
cipher = Fernet(ENCRYPTION_KEY)

# Encriptar
encrypted = cipher.encrypt(b"datos-sensibles")

# Desencriptar
decrypted = cipher.decrypt(encrypted)
```

**Campos encriptados en BD:**
- `riders.cpf` - Número de documento
- `riders.cnh` - Licencia de conducción
- `wallets.bank_account_number` - Cuenta bancaria

### 13.5 Logs de Auditoría

Todas las operaciones críticas se registran en tabla `audit_logs`:

| Campo | Descripción |
|-------|-------------|
| id | UUID único |
| user_id | Usuario que realizó acción |
| action | Tipo de acción (CREATE, UPDATE, DELETE) |
| resource | Recurso afectado (orders, riders, etc.) |
| resource_id | ID del recurso |
| old_value | JSON con valores anteriores |
| new_value | JSON con valores nuevos |
| ip_address | IP del cliente |
| user_agent | User agent del navegador |
| timestamp | Fecha/hora de la acción |

---

## 14. Monitoreo y Logs

### 14.1 Sistema de Logging

**Configuración en `backend/app/core/logging_config.py`:**

```python
import logging
import sys

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s | %(levelname)-8s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S"
        },
        "detailed": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": sys.stdout,
            "level": "INFO"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "detailed",
            "filename": "/var/log/delivery360/app.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "level": "DEBUG"
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file"]
    },
    "loggers": {
        "delivery360": {
            "level": "DEBUG",
            "propagate": False
        },
        "sqlalchemy.engine": {
            "level": "WARNING"
        }
    }
}
```

### 14.2 Logs Estructurados

**Ejemplos de logs por módulo:**

**Autenticación:**
```
[AUTH] Login exitoso: user@example.com | Role: ADMIN | IP: 192.168.1.100
[AUTH] Login fallido: user@example.com | Intentos: 3/5 | IP: 192.168.1.100
[AUTH] Token refresh: user_id=uuid | exp: 2026-08-16T14:00:00Z
```

**Órdenes:**
```
[ORDER] Creada: ORD-A1B2C3D4 | Total: $55000 | Zona: CENTRO
[ORDER] Estado cambiado: ORD-A1B2C3D4 | PENDIENTE → ASIGNADA | Rider: uuid
[ORDER] Cancelada: ORD-A1B2C3D4 | Causa: CLIENTE_ARREPIENTIDO | Por: admin
```

**Bonos:**
```
[BONUS_CALC] Type: SUCCESS, Base: $2500, Zone: 1.5x, Tier: 1.10x, Final: $4125
[BONUS_CALC] Type: FAILED_ATTEMPT, Base: $1500, Zone: 1.0x, Tier: 1.00x, Final: $1500
[BONUS] Snapshot guardado: delivery_id=uuid, amount=4125, config_version=2026-08-15
```

**Financiero:**
```
[WALLET] Acreditado: rider_id=uuid, amount=4125, type=PAGO_ENTREGA, new_balance=125000
[PAYOUT] Solicitado: payout_id=uuid, rider_id=uuid, amount=50000
[PAYOUT] Aprobado: payout_id=uuid, approved_by=admin_uuid, status=PROCESADO
```

### 14.3 Métricas Clave (KPIs)

**Dashboard de métricas en tiempo real:**

| Métrica | Descripción | Fuente |
|---------|-------------|--------|
| orders_per_hour | Órdenes completadas por hora | COUNT(orders WHERE delivered_at) |
| avg_delivery_time | Tiempo promedio de entrega | AVG(deliveries.total_time) |
| rider_utilization | % de tiempo riders activos | SUM(active_time) / SUM(online_time) |
| success_rate | % de entregas exitosas | COUNT(ENTREGADO) / COUNT(total) |
| avg_bonus_per_delivery | Bono promedio por entrega | AVG(locked_bonus_amount) |
| total_payouts_today | Total retirado hoy | SUM(payouts WHERE status=PAGADO) |

### 14.4 Alertas Configurables

**Tipos de alertas:**

| Alerta | Condición | Acción |
|--------|-----------|--------|
| ORDER_STUCK | Orden en mismo estado > 30 min | Notificar manager |
| RIDER_INACTIVE | Rider online sin movimiento > 15 min | Verificar estado |
| LOW_BALANCE | Wallet empresa < mínimo configurado | Alertar finanzas |
| HIGH_FAILURE_RATE | Fallidas > 20% en última hora | Investigar causa |
| API_ERROR_RATE | Errores 5xx > 5% en 5 min | Alertar equipo técnico |

### 14.5 Health Checks

**Endpoints de monitoreo:**

```bash
# Health check básico
GET /health
→ {"status": "healthy"}

# Health check detallado
GET /health/detailed
→ {
    "status": "healthy",
    "database": "connected",
    "redis": "connected",
    "uptime_seconds": 86400,
    "version": "1.0.0"
  }

# Readiness check (para Kubernetes)
GET /ready
→ Valida dependencias antes de recibir tráfico
```

---

## Apéndice A: Glosario de Términos

| Término | Definición |
|---------|------------|
| Order | Solicitud de delivery creada por cliente |
| Pickup | Lugar donde se recoge el pedido (restaurante) |
| Delivery | Lugar donde se entrega el pedido (cliente) |
| Rider | Repartidor que transporta el pedido |
| Zone | Área geográfica delimitada por polígono |
| Tier | Nivel del repartidor (Bronce, Plata, Oro, Platino) |
| Bonus Multiplier | Factor multiplicador aplicado al bono base |
| SLA | Tiempo máximo esperado para completar entrega |
| Proof of Delivery | Evidencia de entrega (foto, OTP, firma) |
| Wallet | Billetera virtual del repartidor |
| Payout | Retiro de fondos de wallet a cuenta bancaria |
| Snapshot | Registro inmutable de configuración al momento del cálculo |

---

## Apéndice B: Códigos de Error Comunes

| Código | Significado | Solución |
|--------|-------------|----------|
| ORD_001 | Orden no encontrada | Verificar ID de orden |
| ORD_002 | Transición de estado inválida | Revisar máquina de estados |
| ORD_003 | No hay riders disponibles | Expandir radio de búsqueda |
| RDR_001 | Rider no encontrado | Verificar ID de rider |
| RDR_002 | Rider no está online | Esperar a que se conecte |
| RDR_003 | Rider ya tiene orden asignada | Esperar a que complete |
| ZONE_001 | Zona no encontrada | Verificar ID de zona |
| ZONE_002 | Coordenadas fuera de zonas activas | Crear zona o expandir existente |
| FIN_001 | Saldo insuficiente | Rider debe acumular más entregas |
| FIN_002 | Monto de retiro inválido | Verificar mínimos y máximos |
| AUTH_001 | Credenciales inválidas | Verificar email/password |
| AUTH_002 | Token expirado | Solicitar nuevo login |
| AUTH_003 | Usuario bloqueado | Esperar 15 min o contactar admin |
| SYS_001 | Error de base de datos | Revisar logs detallados |
| SYS_002 | Redis no disponible | Verificar conexión Redis |
| SYS_003 | Error externo (API terceros) | Reintentar o fallback |

---

## Apéndice C: Comandos Útiles de Mantenimiento

```bash
# Resetear password de admin
python scripts/reset_admin_password.py --email admin@delivery360.com

# Limpiar órdenes antiguas (> 90 días)
python scripts/cleanup_old_orders.py --days 90

# Recalcular bonuses mal calculados
python scripts/recalculate_bonuses.py --from-date 2026-08-01

# Exportar reporte financiero
python scripts/export_financial_report.py --month 2026-08 --format csv

# Validar integridad de datos
python scripts/validate_data_integrity.py

# Backup de base de datos
pg_dump -h localhost -U delivery360 delivery360_db > backup_$(date +%Y%m%d).sql

# Restaurar backup
psql -h localhost -U delivery360 delivery360_db < backup_20260815.sql

# Migrar datos de riders sin tier
python scripts/migrate_rider_tiers.py

# Actualizar multiplicadores de zona
python scripts/update_zone_multipliers.py --zone CENTRO --multiplier 1.2
```

---

## Apéndice D: Referencias Externas

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [PostGIS Documentation](https://postgis.net/documentation/)
- [Next.js Documentation](https://nextjs.org/docs)
- [JWT.io](https://jwt.io/)
- [AsyncPG Documentation](https://magicstack.github.io/asyncpg/current/)

---

**Fin del Manual de Ingeniero - Delivery360**

*Documento generado automáticamente el 2026-08-15*
*Para actualizaciones, crear Pull Request con cambios en este archivo*

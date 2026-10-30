# Delivery360 Backend

Backend API para el sistema de gestión de entregas Delivery360.

## Tecnologías

- **FastAPI** - Framework web moderno
- **SQLAlchemy** - ORM para base de datos
- **PostgreSQL** - Base de datos principal
- **Redis** - Cache y colas
- **Celery** - Tareas asíncronas
- **Alembic** - Migraciones de base de datos
- **JWT** - Autenticación

## Inicio Rápido

### Desarrollo local

```bash
# Instalar dependencias
pip install -r requirements.txt

# Copiar variables de ambiente
cp .env.example .env

# Ejecutar migraciones
alembic upgrade head

# Iniciar servidor
uvicorn app.main:app --reload
```

### Docker

```bash
docker-compose up -d
```

## Documentación API

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Estructura del Proyecto

```
backend/
├── app/
│   ├── api/v1/          # Endpoints API
│   ├── core/            # Configuración, seguridad, DB
│   ├── crud/            # Operaciones CRUD
│   ├── middleware/      # Middlewares personalizados
│   ├── models/          # Modelos SQLAlchemy
│   ├── monitoring/      # Health checks, métricas
│   ├── schemas/         # Schemas Pydantic
│   ├── services/        # Lógica de negocio
│   └── workers/         # Tareas Celery
├── alembic/             # Migraciones DB
├── tests/               # Tests automatizados
└── requirements.txt     # Dependencias
```

## Comandos Útiles

```bash
# Crear migración
alembic revision --autogenerate -m "descripcion"

# Aplicar migraciones
alembic upgrade head

# Rollback
alembic downgrade -1

# Ejecutar tests
pytest

# Linting
black .
flake8
```


## Revocación JWT y despliegue

La entrega 48 incorpora una versión de credenciales por cuenta. Requiere aplicar
la migración `20261028_auth_version` antes de desplegar el código nuevo y retirar
los workers antiguos para que la revocación sea uniforme. Logout confirmado,
contraseñas y cambios administrativos de rol/estado retiran credenciales previas.
El logout tiene alcance de todas las sesiones de esa cuenta. Consulte
[contrato, migración, rollback y límites](AUTH_TOKEN_REVOCATION.md).

## Integridad fiscal y previews

La entrega 50 requiere la revisión `20261029_fiscal_integrity` antes del código
nuevo. Emisión y sandbox están deshabilitados por defecto. Los adaptadores
DIAN/SAT actuales no tienen transporte homologado y rechazan la emisión real;
las previsualizaciones son explícitas, solo fuera de producción y con resolución
sandbox, sin aceptación ni identificadores oficiales simulados. Consulte
[configuración, diccionario, numeración, migración y límites](FISCAL_INTEGRITY.md).

## Rutas GPS y ETA

La entrega 51 conecta `/api/v1/routes` con rutas y puntos persistidos, añade
planificación manual, historial, métricas y revisión de desvíos con permisos.
Conserva el alias GPS anterior y el esquema SQL; no requiere migración nueva.
El ETA conserva destinos con coordenadas cero y no usa la posición del rider como
destino. Consulte [contratos, diccionario, concurrencia y límites](ROUTE_ANALYSIS.md),
incluidas las tareas pendientes del conjunto de workers y la unificación de trazas.

## Paneles operativos y productividad

La entrega 53 conecta los paneles de gerente y operador con agregados SQL reales,
calendarios locales, permisos y estados de datos desconocidos. Corrige las rutas
de productividad para leer consolidaciones existentes y ofrece ranking de volumen.
No requiere migración ni activa tareas. Consulte [contratos, diccionario,
compatibilidad, sesiones y límites](OPERATIONAL_DASHBOARDS.md).

## Registro de integraciones

La entrega 54 corrige las rutas de integraciones y permite consultar metadatos,
registrar proveedores inactivos, modificar etiquetas y pausar su programación
con permisos y auditoría transaccional. Los diagnósticos son locales y no anuncian
una conexión externa verificada. No requiere migración. Consulte
[contratos, diccionario, conservación y adaptadores pendientes](INTEGRATION_REGISTRY.md).

## Workers y programación operativa

La entrega 52 normaliza ocho módulos y doce tareas Celery, incorpora productividad
de días cerrados y vigilancia SLA con evidencia/bandeja local. La agenda y los jobs
nuevos están deshabilitados por defecto y se habilitan explícitamente. Los antiguos
envíos simulados, la liquidación sin evidencia y el borrado global ya no declaran
éxito ni se programan. No requiere migración nueva. Consulte
[configuración, arranque, contratos y límites](WORKER_OPERATIONS.md).

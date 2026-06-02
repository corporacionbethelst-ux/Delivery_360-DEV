# 🏗️ Arquitectura Delivery360

## Descripción General

Delivery360 es un sistema de gestión de entregas de última milla inspirado en Yummy SuperApp Rides, diseñado para conectar restaurantes, clientes y repartidores en una plataforma unificada.

## Stack Tecnológico

### Backend
- **Framework**: FastAPI 0.111.0 (Python 3.11+)
- **Base de Datos**: PostgreSQL 16 con PostGIS 3.4 (geolocalización)
- **ORM**: SQLAlchemy 2.0.31 (asíncrono con asyncpg)
- **Migraciones**: Alembic 1.13.2
- **Cola de Tareas**: Celery 5.4.0 + Redis 7
- **Autenticación**: JWT con python-jose, bcrypt
- **Validación**: Pydantic 2.8.2

### Frontend
- **Framework**: Next.js 14.2.5 (React 18.3.1)
- **Lenguaje**: TypeScript 5.5.4
- **UI**: TailwindCSS 3.4.7 + Radix UI
- **Estado**: Zustand 4.5.4
- **Mapas**: Leaflet 1.9.4
- **Gráficos**: Recharts 2.12.7

### Infraestructura
- Docker Compose para desarrollo
- Kubernetes para producción (configuración pendiente)
- Terraform para IaC (scripts pendientes)
- Monitoring: Prometheus, Grafana, Sentry, Logstash

## Estructura del Proyecto

```
/workspace/
├── backend/                 # API REST FastAPI
│   ├── app/
│   │   ├── api/v1/         # Endpoints REST (18 rutas)
│   │   ├── core/           # Configuración y seguridad
│   │   ├── crud/           # Capa de acceso a datos
│   │   ├── models/         # Modelos SQLAlchemy (14 modelos)
│   │   ├── schemas/        # Schemas Pydantic (13 schemas)
│   │   ├── services/       # Lógica de negocio (13 servicios)
│   │   ├── workers/        # Tareas Celery (9 workers)
│   │   ├── middleware/     # Middlewares (auth, rate-limit, etc.)
│   │   ├── integrations/   # Conectores externos (ERP, POS, Webhooks)
│   │   └── monitoring/     # Health checks, métricas, logging
│   ├── alembic/            # Migraciones de base de datos
│   └── scripts/            # Scripts de utilidad (seed, setup)
├── frontend/               # Aplicación Next.js
│   ├── src/
│   │   ├── app/            # Rutas y páginas
│   │   ├── components/     # Componentes React (60+)
│   │   ├── services/       # Clientes API (14 servicios)
│   │   ├── stores/         # Estado global Zustand (8 stores)
│   │   ├── hooks/          # Custom hooks (8 hooks)
│   │   ├── lib/            # Utilitarios
│   │   └── types/          # Tipos TypeScript (12 definiciones)
│   └── public/             # Assets estáticos
├── docs/                   # Documentación
├── infrastructure/         # K8s, Terraform, Docker
└── monitoring/             # Configs de monitoreo
```

## Modelo de Datos

### Entidades Principales

1. **User**: Usuarios del sistema (clientes, repartidores, operadores, gerentes, superadmin)
2. **Rider**: Perfil extendido de repartidores con información laboral y vehicular
3. **Vehicle**: Flota de vehículos asociados a usuarios/repartidores
4. **Order**: Pedidos de clientes con items y estados
5. **Delivery**: Entregas asignadas a repartidores con tracking
6. **Route**: Rutas planificadas con puntos GPS
7. **Shift**: Turnos laborales de repartidores
8. **Financial**: Transacciones financieras (pagos, bonos, ajustes)
9. **Payout**: Retiros de dinero de repartidores
10. **ProductivityRecord**: Métricas de rendimiento de repartidores
11. **Alert**: Alertas operacionales (retrasos, incidencias)
12. **Notification**: Notificaciones push/email a usuarios
13. **RiderDocument**: Documentos de repartidores (licencia, seguro, etc.)
14. **AuditLog**: Registro de auditoría de acciones

### Relaciones Clave

- **User → Rider**: Uno-a-uno (un usuario puede tener un perfil de repartidor)
- **User → Vehicle**: Uno-a-muchos (un usuario puede poseer múltiples vehículos)
- **Rider → Delivery**: Uno-a-muchos (un repartidor realiza múltiples entregas)
- **Order → Delivery**: Uno-a-uno (cada orden genera una entrega)
- **Delivery → Route**: Uno-a-muchos (una entrega puede tener múltiples rutas de tracking)

## Flujo de Entrega Típico

```
1. Cliente crea Order → Estado: PENDIENTE
2. Sistema asigna Rider → Estado: ASIGNADO
3. Rider recoge en restaurante → Estado: EN_RECOLECCION
4. Rider inicia ruta → Estado: EN_RUTA
5. Rider entrega al cliente → Estado: ENTREGADO
6. Se registra Financial Transaction → Pago al rider
7. Se actualiza ProductivityRecord → Métricas del rider
```

## Seguridad

- Autenticación JWT con access tokens y refresh tokens
- Hash de contraseñas con bcrypt
- Rate limiting por IP y usuario
- CORS configurado para dominios específicos
- Security headers (HSTS, X-Frame-Options, etc.)
- Roles y permisos: SUPERADMIN, GERENTE, OPERADOR, REPARTIDOR, CLIENTE

## Escalabilidad

- Base de datos con índices en campos críticos (email, plate, status)
- Conexiones asíncronas a PostgreSQL y Redis
- Cola Celery para tareas pesadas (emails, cálculos, webhooks)
- Cache Redis para consultas frecuentes
- Health checks en todos los servicios

## Monitorización

- Health endpoints: `/health`, `/health/db`, `/health/redis`
- Métricas Prometheus en `/metrics`
- Logging estructurado con structlog
- Integración con Sentry para errores
- Dashboards Grafana para operaciones

## Variables de Ambiente Críticas

Ver `.env.example` para lista completa. Las más importantes:

- `DATABASE_URL`: Conexión a PostgreSQL
- `REDIS_URL`: Conexión a Redis
- `SECRET_KEY`: Clave para JWT (generar única para producción)
- `SMTP_USER/PASSWORD`: Credenciales de email
- `ENVIRONMENT`: development/staging/production

---

*Documento generado como parte de la Fase 1 de preparación para producción*

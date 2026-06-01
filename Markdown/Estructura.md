ESTRUCTURA COMPLETA DEL PROYECTO DELIVERY360
TOTAL: 546 elementos (directorios + archivos)
📂 RAÍZ DEL PROYECTO (/workspace/)
Archivos de Configuración y Documentación:

/workspace/
├── .env                          # Variables de entorno globales
├── .dockerignore                 # Ignorar archivos Docker
├── .gitignore                    # Ignorar archivos Git
├── LICENSE                       # Licencia del proyecto
├── README.md                     # README principal
├── MANUAL_INSTALACION_DELIVERY360.md   # Manual de instalación
├── docker-compose.yml            # Orquestación Docker completa
├── package.json                  # Dependencias raíz
├── tree_code.py                  # Script utilitario
└── Markdown/
    └── Data.ipynb                # Notebook de análisis de datos

📂 BACKEND (/workspace/backend/)
Archivos Principales:

backend/
├── .env                          # Variables de entorno backend
├── .env.example                  # Ejemplo de variables de entorno
├── README.md                     # Documentación backend
├── pyproject.toml                # Configuración proyecto Python
├── requirements.txt              # Dependencias Python (35 paquetes)
├── Dockerfile                    # Contenedor backend
├── alembic.ini                   # Configuración migraciones DB
├── main.py                       # Punto de entrada FastAPI
└── app/                          # Código fuente principal

Módulo API (/workspace/backend/app/api/v1/):

api/v1/
├── __init__.py
├── auth.py                       # Autenticación JWT (login, refresh, register)
├── users.py                      # CRUD usuarios
├── riders.py                     # Gestión repartidores (35KB)
├── orders.py                     # Gestión pedidos (18KB)
├── deliveries.py                 # Seguimiento entregas
├── shifts.py                     # Turnos repartidores
├── financial.py                  # Módulo financiero
├── productivity.py               # Métricas productividad
├── dashboard.py                  # Endpoints dashboard
├── routes.py                     # Rutas combinadas
├── routers_combined.py           # Rutas adicionales
├── alerts.py                     # Alertas del sistema
├── integrations.py               # Integraciones externas
├── audit.py                      # Logs de auditoría
└── payouts.py                    # Pagos a riders

Modelos de Datos (/workspace/backend/app/models/):

models/
├── __init__.py
├── all_models.py                 # Importación todos modelos
├── user.py                       # Modelo Usuario + roles
├── rider.py                      # Modelo Repartidor + geolocalización
├── order.py                      # Modelo Pedido + estados
├── delivery.py                   # Modelo Entrega + pruebas
├── route.py                      # Modelo Ruta + desvíos
├── shift.py                      # Modelo Turno + check-in/out
├── financial.py                  # Modelo Transacciones
├── productivity.py               # Modelo Métricas rendimiento
├── audit_log.py                  # Modelo Logs auditoría
├── notification.py               # Modelo Notificaciones + alertas
├── integration.py                # Modelo Integraciones
├── payout.py                     # Modelo Pagos
└── rider_document.py             # Modelo Documentos riders

Esquemas de Validación (/workspace/backend/app/schemas/):

schemas/
├── __init__.py
├── user.py                       # Pydantic schemas usuario
├── rider.py                      # Pydantic schemas repartidor
├── order.py                      # Pydantic schemas pedido
├── delivery.py                   # Pydantic schemas entrega
├── shift.py                      # Pydantic schemas turno
├── financial.py                  # Pydantic schemas financiero
├── productivity.py               # Pydantic schemas productividad
├── audit.py                      # Pydantic schemas auditoría
├── dashboard.py                  # Pydantic schemas dashboard
├── auth.py                       # Pydantic schemas autenticación
├── error.py                      # Pydantic schemas errores
└── payout.py                     # Pydantic schemas pagos

Servicios de Negocio (/workspace/backend/app/services/):

services/
├── __init__.py
├── auth_service.py               # Lógica autenticación
├── user_service.py               # Lógica usuarios
├── rider_service.py              # Lógica repartidores
├── order_service.py              # Lógica pedidos
├── delivery_service.py           # Lógica entregas
├── shift_service.py              # Lógica turnos
├── financial_service.py          # Lógica financiera
├── productivity_service.py       # Lógica productividad
├── audit_service.py              # Lógica auditoría
├── notification_service.py       # Lógica notificaciones
├── alert_service.py              # Lógica alertas
├── route_service.py              # Lógica rutas
├── integration_service.py        # Lógica integraciones
└── dashboard_service.py          # Lógica dashboard

Operaciones CRUD (/workspace/backend/app/crud/):

crud/
├── __init__.py
├── base.py                       # Clase base CRUD
├── user.py                       # Operaciones DB usuario
├── rider.py                      # Operaciones DB repartidor
├── order.py                      # Operaciones DB pedido
├── delivery.py                   # Operaciones DB entrega
├── shift.py                      # Operaciones DB turno
├── financial.py                  # Operaciones DB financiero
├── route.py                      # Operaciones DB ruta
└── productivity.py               # Operaciones DB productividad

Tareas Asíncronas - Workers (/workspace/backend/app/workers/):

workers/
├── __init__.py
├── celery_app.py                 # Configuración Celery + Beat
├── sla_monitor_worker.py         # Monitoreo SLA
├── liquidation_worker.py         # Liquidación automática
├── productivity_worker.py        # Cálculo productividad
├── notification_worker.py        # Envío notificaciones
├── cleanup_worker.py             # Limpieza datos temporales
├── route_analysis_worker.py      # Análisis de rutas
├── alert_worker.py               # Procesamiento alertas
└── report_worker.py              # Generación reportes

Configuración Core (/workspace/backend/app/core/):

core/
├── __init__.py
├── config.py                     # Configuración con Pydantic Settings
├── database.py                   # Conexión async SQLAlchemy
├── security.py                   # JWT + bcrypt password hashing
├── email_service.py              # Servicio SMTP emails
├── rate_limiter.py               # Rate limiting middleware
├── audit_logger.py               # Logger de auditoría
├── exception_handlers.py         # Manejo excepciones global
├── websocket.py                  # WebSocket manager
└── seed.py                       # Seed inicial datos

Middlewares (/workspace/backend/app/middleware/):

middleware/
├── __init__.py
├── auth_middleware.py            # Autenticación requests
├── cors_middleware.py            # CORS configuration
├── rate_limit_middleware.py      # Rate limiting
├── audit_middleware.py           # Logging auditoría
└── security_headers.py           # Security headers HTTP

Utilidades (/workspace/backend/app/utils/):

utils/
├── __init__.py
├── sla_checker.py                # Verificación SLA
├── cost_calculator.py            # Cálculo costos
├── geolocation.py                # Funciones geolocalización
├── lgpd_compliance.py            # Cumplimiento LGPD
├── time_calculator.py            # Cálculos temporales
├── validators.py                 # Validadores personalizados
└── data_exporter.py              # Exportación datos CSV/Excel

Integraciones (/workspace/backend/app/integrations/):

integrations/
├── __init__.py
├── pos_connector.py              # Conector POS (Punto de Venta)
├── erp_connector.py              # Conector ERP
└── webhook_handler.py            # Manejador webhooks

Monitoreo (/workspace/backend/app/monitoring/):

monitoring/
├── __init__.py
├── sentry_config.py              # Configuración Sentry
├── health_check.py               # Health checks básicos
├── health_checks.py              # Health checks avanzados
├── metrics.py                    # Métricas Prometheus
└── logging_config.py             # Configuración logging

Migraciones de Base de Datos (/workspace/backend/alembic/):

alembic/
├── env.py                        # Ambiente Alembic
├── script.py.mako                # Template migraciones
├── versions/
│   ├── a617d286d3d0_initial_schema_complete.py  # Schema inicial completo
│   └── schema_completo.sql       # SQL schema completo
└── ..

Scripts (/workspace/backend/scripts/):

scripts/
├── setup_dev.sh                  # Setup entorno desarrollo
├── run_migrations.sh             # Ejecutar migraciones
├── validate_secret_key.py        # Validar SECRET_KEY
└── seed_data.py                  # Poblar datos iniciales

📂 FRONTEND (/workspace/frontend/)
Archivos de Configuración:

frontend/
├── package.json                  # Dependencias npm (42 paquetes)
├── package-lock.json             # Lock dependencies
├── tsconfig.json                 # Configuración TypeScript
├── next.config.js                # Configuración Next.js
├── tailwind.config.ts            # Configuración Tailwind CSS
├── postcss.config.js             # Configuración PostCSS
├── next-env.d.ts                 # Tipos Next.js
├── .dockerignore                 # Ignorar Docker
├── .gitignore                    # Ignorar Git
├── Dockerfile                    # Contenedor frontend
└── public/
    ├── manifest.json             # PWA manifest
    └── sw.js                     # Service Worker

Aplicación Principal (/workspace/frontend/src/app/):

app/
├── layout.tsx                    # Root layout
├── page.tsx                      # Landing page
├── globals.css                   # Estilos globales
│
├── (auth)/                       # Módulo autenticación (rutas agrupadas)
│   ├── login/
│   │   └── page.tsx              # Página login
│   ├── register-rider/
│   │   └── page.tsx              # Registro repartidores
│   ├── forgot-password/
│   │   └── page.tsx              # Recuperar contraseña
│   └── reset-password/
│       └── page.tsx              # Resetear contraseña
│
├── (dashboard)/                  # Módulo dashboard (rutas protegidas)
│   ├── layout.tsx                # Layout dashboard
│   │
│   ├── operator/                 # Dashboard operador
│   │   ├── page.tsx
│   │   ├── orders/
│   │   │   └── page.tsx
│   │   ├── deliveries/
│   │   │   ├── page.tsx
│   │   │   └── [id]/
│   │   │       └── page.tsx
│   │   ├── live-map/
│   │   │   └── page.tsx
│   │   ├── shifts/
│   │   │   ├── page.tsx
│   │   │   └── [id]/
│   │   │       └── page.tsx
│   │   ├── alerts/
│   │   │   └── page.tsx
│   │   └── settings/
│   │       └── page.tsx
│   │
│   ├── rider/                    # App repartidor
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── my-orders/
│   │   │   ├── page.tsx
│   │   │   └── [id]/
│   │   │       └── page.tsx
│   │   ├── earnings/
│   │   │   ├── page.tsx
│   │   │   ├── withdraw/
│   │   │   │   └── page.tsx
│   │   │   └── payouts/
│   │   │       └── page.tsx
│   │   ├── profile/
│   │   │   ├── page.tsx
│   │   │   └── documents/
│   │   │       └── page.tsx
│   │   ├── productivity/
│   │   │   └── page.tsx
│   │   └── notifications/
│   │       └── page.tsx
│   │
│   └── manager/                  # Dashboard gerente/admin
│       ├── page.tsx
│       ├── [...catchall]/
│       │   └── page.tsx
│       │
│       ├── admin/                # Administración
│       │   ├── users/
│       │   │   ├── page.tsx
│       │   │   ├── new/
│       │   │   │   └── page.tsx
│       │   │   └── [id]/
│       │   │       └── page.tsx
│       │   ├── roles/
│       │   │   └── page.tsx
│       │   ├── audit/
│       │   │   └── page.tsx
│       │   └── settings/
│       │       └── page.tsx
│       │
│       ├── fleet/                # Gestión flota
│       │   ├── riders/
│       │   │   ├── page.tsx
│       │   │   ├── new/
│       │   │   │   └── page.tsx
│       │   │   ├── [id]/
│       │   │   │   └── page.tsx
│       │   │   │   └── documents/
│       │   │   │       └── page.tsx
│       │   │   └── map/
│       │   │       └── page.tsx
│       │   ├── vehicles/
│       │   │   ├── page.tsx
│       │   │   ├── new/
│       │   │   │   └── page.tsx
│       │   │   └── [id]/
│       │   │       └── page.tsx
│       │   └── zones/
│       │       ├── page.tsx
│       │       └── [id]/
│       │           └── page.tsx
│       │
│       ├── operations/           # Operaciones
│       │   ├── orders/
│       │   │   ├── page.tsx
│       │   │   ├── new/
│       │   │   │   └── page.tsx
│       │   │   └── [id]/
│       │   │       └── page.tsx
│       │   ├── deliveries/
│       │   │   └── page.tsx
│       │   ├── live-map/
│       │   │   └── page.tsx
│       │   └── alerts/
│       │       └── page.tsx
│       │
│       └── financial/            # Financiero
│           ├── resumen/
│           │   └── page.tsx
│           ├── transactions/
│           │   ├── page.tsx
│           │   └── [id]/
│           │       └── page.tsx
│           ├── payouts/
│           │   ├── page.tsx
│           │   └── [id]/
│           │       └── page.tsx
│           └── reports/
│               └── page.tsx

Componentes (/workspace/frontend/src/components/):

components/
├── ui/                           # Componentes base (shadcn/ui)
│   ├── alert.tsx
│   ├── avatar.tsx
│   ├── badge.tsx
│   ├── button.tsx
│   ├── card.tsx
│   ├── dialog.tsx
│   ├── dropdown-menu.tsx
│   ├── form.tsx
│   ├── input.tsx
│   ├── label.tsx
│   ├── progress.tsx
│   ├── radio-group.tsx
│   ├── select.tsx
│   ├── separator.tsx
│   ├── skeleton.tsx
│   ├── slider.tsx
│   ├── switch.tsx
│   ├── table.tsx
│   ├── tabs.tsx
│   ├── textarea.tsx
│   └── ... (más componentes UI)
│
├── layout/                       # Componentes layout
│   ├── NotificationCenter.tsx
│   └── NotificationBell.tsx
│
├── dashboard/                    # Widgets dashboard
│   ├── StatsCards.tsx
│   ├── ManagerDashboard.tsx
│   ├── OperatorDashboard.tsx
│   ├── RiderDashboard.tsx
│   ├── ActiveRiders.tsx
│   ├── ActiveRidersMap.tsx
│   ├── RecentOrders.tsx
│   └── RecentOrdersTable.tsx
│
├── orders/                       # Componentes pedidos
│   ├── OrderCard.tsx
│   ├── OrderList.tsx
│   ├── OrderDetailPanel.tsx
│   ├── OrderStatusBadge.tsx
│   └── AssignRiderModal.tsx
│
├── deliveries/                   # Componentes entregas
│   ├── DeliveryTracker.tsx
│   ├── StartDeliveryButton.tsx
│   ├── FinishDeliveryForm.tsx
│   └── ProofOfDelivery.tsx
│
├── riders/                       # Componentes repartidores
│   ├── RiderCard.tsx
│   ├── RiderList.tsx
│   ├── RiderRegistrationForm.tsx
│   ├── RiderProductivityChart.tsx
│   └── PerformanceRanking.tsx
│
├── shifts/                       # Componentes turnos
│   ├── ShiftControl.tsx
│   ├── CheckInOut.tsx
│   └── ShiftCalendar.tsx
│
├── financial/                    # Componentes financieros
│   ├── FinancialSummary.tsx
│   ├── FinancialFilters.tsx
│   ├── TransactionTable.tsx
│   ├── PaymentStatusBadge.tsx
│   └── RiderPayoutList.tsx
│
├── maps/                         # Componentes mapas
│   ├── DeliveryMap.tsx
│   ├── LiveTrackingMap.tsx
│   ├── RouteViewer.tsx
│   ├── RiderMarker.tsx
│   └── RouteDeviationAlert.tsx
│
├── charts/                       # Gráficos
│   ├── AreaChartCustom.tsx
│   └── SimpleBarChart.tsx
│
├── alerts/                       # Alertas
│   ├── AlertList.tsx
│   ├── AlertItem.tsx
│   ├── AlertPanel.tsx
│   └── AlertBadge.tsx
│
├── productivity/                 # Productividad
│   ├── SLAMeter.tsx
│   ├── TimeMetrics.tsx
│   ├── OrdersPerHour.tsx
│   ├── ShiftComparison.tsx
│   └── PerformanceRanking.tsx
│
├── loaders/                      # Loading states
│   ├── FullPageLoader.tsx
│   ├── DashboardStatsSkeleton.tsx
│   ├── TableSkeleton.tsx
│   └── OrderSkeleton.tsx
│
├── audit/                        # Auditoría
│   ├── AuditLogTable.tsx
│   └── AccessHistory.tsx
│
└── integrations/                 # Integraciones
    └── WebhookConfig.tsx

Servicios API (/workspace/frontend/src/services/):

services/
├── auth.service.ts               # Autenticación
├── user.service.ts               # Usuarios
├── rider.service.ts              # Repartidores
├── order.service.ts              # Pedidos
├── delivery.service.ts           # Entregas
├── shift.service.ts              # Turnos
├── financial.service.ts          # Financiero
├── transaction.service.ts        # Transacciones
├── payout.service.ts             # Pagos
├── alert.service.ts              # Alertas
├── notification.service.ts       # Notificaciones
├── zone.service.ts               # Zonas
├── vehicle.service.ts            # Vehículos
├── role.service.ts               # Roles
└── settings.service.ts           # Configuración

State Management - Stores (/workspace/frontend/src/stores/):

stores/
├── authStore.ts                  # Estado autenticación
├── ridersStore.ts                # Estado repartidores
├── riderPersonalStore.ts         # Estado perfil rider
├── ordersStore.ts                # Estado pedidos
├── deliveriesStore.ts            # Estado entregas
├── financialStore.ts             # Estado financiero
├── realtimeStore.ts              # Estado tiempo real
└── notificationStore.ts          # Estado notificaciones

Contextos React (/workspace/frontend/src/contexts/):

contexts/
├── NotificationContext.tsx       # Contexto notificaciones
└── WebSocketContext.tsx          # Contexto WebSocket

Hooks Personalizados (/workspace/frontend/src/hooks/):

hooks/
├── useSidebar.ts                 # Control sidebar
├── useRole.ts                    # Hook roles
├── useSocket.ts                  # WebSocket hook
├── useGeolocation.ts             # Geolocalización
├── useRiderLocation.ts           # Ubicación rider
├── useRealtimeUpdates.ts         # Actualizaciones tiempo real
└── useProductivity.ts            # Métricas productividad

Tipos TypeScript (/workspace/frontend/src/types/):

types/
├── index.ts                      # Exportación tipos
├── auth.ts                       # Tipos autenticación
├── user.ts                       # Tipos usuario
├── rider.ts                      # Tipos repartidor
├── order.ts                      # Tipos pedido
├── delivery.ts                   # Tipos entrega
├── financial.ts                  # Tipos financiero
├── productivity.ts               # Tipos productividad
├── alerts.ts                     # Tipos alertas
├── common.ts                     # Tipos comunes
└── leaflet.d.ts                  # Tipos Leaflet

Librerías y Utilidades (/workspace/frontend/src/lib/):

lib/
├── api.ts                        # Wrapper axios API
├── auth.ts                       # Funciones autenticación
├── websocket.ts                  # Cliente WebSocket
├── geolocation.ts                # Funciones geolocalización
├── formatters.ts                 # Formateadores
├── utils.ts                      # Utilidades generales
├── time-utils.ts                 # Utilidades tiempo
├── csv-export.ts                 # Exportación CSV
├── financial-utils.ts            # Utilidades financieras
└── lgpd-utils.ts                 # Utilidades LGPD

Configuración (/workspace/frontend/src/config/):

config/
└── navigation.config.ts          # Configuración menús navegación

Middleware (/workspace/frontend/src/):

middleware.ts                     # Auth middleware Next.js

📂 INFRAESTRUCTURA (/workspace/infrastructure/)

Kubernetes (/workspace/infrastructure/kubernetes/):

kubernetes/
├── namespace.yaml                # Namespace delivery360
├── configmap.yaml                # ConfigMaps
├── secrets.yaml                  # Secrets (placeholder)
├── backend-deployment.yaml       # Deployment backend
├── frontend-deployment.yaml      # Deployment frontend
├── celery-deployment.yaml        # Deployment workers Celery
├── celery-beat-deployment.yaml   # Deployment Celery Beat
├── postgres-statefulset.yaml     # StatefulSet PostgreSQL
├── redis-statefulset.yaml        # StatefulSet Redis
├── services.yaml                 # Services Kubernetes
├── ingress.yaml                  # Ingress controller
├── hpa.yaml                      # Horizontal Pod Autoscaler
└── network-policy.yaml           # Network Policies

Docker (/workspace/infrastructure/docker/):

docker/
├── backend.Dockerfile            # Dockerfile backend prod
├── frontend.Dockerfile           # Dockerfile frontend prod
├── celery.Dockerfile             # Dockerfile workers Celery
└── nginx.conf                    # Configuración Nginx

Terraform (/workspace/infrastructure/terraform/):

terraform/
└── scripts/
    ├── init.sh                   # Inicializar Terraform (placeholder)
    ├── apply.sh                  # Aplicar infraestructura (placeholder)
    └── destroy.sh                # Destruir infraestructura (placeholder)

Scripts (/workspace/infrastructure/scripts/):

scripts/
├── setup_infra.sh                # Setup infraestructura (placeholder)
├── deploy.sh                     # Deploy automático (placeholder)
├── health_check.sh               # Health check (placeholder)
├── backup_db.sh                  # Backup DB (placeholder)
└── restore_db.sh                 # Restore DB (placeholder)

📂 MONITOREO (/workspace/monitoring/)

Prometheus (/workspace/monitoring/prometheus/):

prometheus/
├── prometheus.yml                # Configuración Prometheus
└── alerts.yml                    # Reglas de alerta

Grafana (/workspace/monitoring/grafana/):

grafana/
└── dashboards/
    ├── operations-dashboard.json     # Dashboard operaciones
    ├── sla-monitoring.json           # Dashboard SLA
    ├── financial-metrics.json        # Dashboard financiero
    └── rider-productivity.json       # Dashboard productividad riders

Logstash (/workspace/monitoring/logstash/):

logstash/
└── pipeline.conf                 # Pipeline Logstash

Sentry (/workspace/monitoring/sentry/):

sentry/
└── config.py                     # Configuración Sentry

📂 DOCUMENTACIÓN (/workspace/docs/)

docs/
├── architecture.md               # Documentación arquitectura
├── api-documentation.md          # Documentación API
├── deployment-guide.md           # Guía despliegue
├── lgpd-compliance.md            # Compliance LGPD
└── user-manuals/
    ├── manager-guide.md          # Manual gerente
    ├── operator-guide.md         # Manual operador
    └── rider-guide.md            # Manual repartidor


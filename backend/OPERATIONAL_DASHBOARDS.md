# Paneles operativos y productividad — entrega 53

## Finalidad y alcance

Los paneles de gerente y operador consultan hechos persistidos. Se eliminan el
crecimiento fijo del 12,5 %, la distribución artificial de ingresos por día, los
ceros financieros sin evidencia y los conteos obtenidos de listas limitadas.
Las dos páginas activas y los dos componentes reutilizables usan el mismo panel.

Este bloque es de lectura. No crea migraciones, modifica modelos SQL, añade
dependencias al proyecto, activa jobs, liquida dinero ni emite documentos fiscales.
Las barreras fiscales y los flags de workers de entregas anteriores se conservan.

## Contratos HTTP y permisos

Todas las rutas siguientes incluyen el prefijo `/api/v1`:

| Método y ruta | Acceso | Consulta |
| --- | --- | --- |
| `GET /dashboard/manager` | SUPERADMIN, GERENTE | `days`: 1–31; por defecto 1 |
| `GET /dashboard/operator` | SUPERADMIN, GERENTE, OPERADOR | `days`: 1–31; por defecto 1 |
| `GET /productivity/rider/{rider_id}` | Operaciones, AUDITOR, repartidor propietario | `limit`: 1–100; por defecto 30 |
| `GET /productivity/ranking` | SUPERADMIN, GERENTE, OPERADOR | `days`: 1–31, defecto 7; `limit`: 1–100, defecto 50 |

Los permisos usan el usuario y rol vigentes en la base de datos, no un rol
enviado por el cliente. Se mantienen validación JWT, versión de credenciales,
cuenta activa y política de estado del repartidor. CLIENTE no tiene autorización
para estos datos; el identificador de historial es `riders.id`, no `users.id`.
AUDITOR puede consultar historial de productividad, pero no paneles ni ranking.

Se conservan, fuera de OpenAPI, los alias históricos de prefijo duplicado:
`/dashboard/dashboard/manager`, `/dashboard/dashboard/operator`,
`/productivity/productivity/rider/{rider_id}` y
`/productivity/productivity/ranking`. Comparten los mismos handlers y controles.
El montaje canónico funciona sin repetir el prefijo.

## Calendario y significado de los resultados

`app/core/reporting_period.py` usa `CELERY_TIMEZONE` —IANA validada por la
configuración existente— para construir días calendario. No hay una nueva
configuración de zona horaria. El valor predeterminado del sistema sigue siendo
`America/Sao_Paulo`; debe revisarse al configurar cada instalación.

Un período de siete días comienza a medianoche local seis días antes de hoy y
termina en el instante de consulta. Hoy es parcial. Se consultan columnas UTC sin
zona horaria con intervalos semiabiertos `[inicio, fin)` y se devuelven timestamps
UTC con offset. Los días de 23 y 25 horas por cambio estacional se respetan.
Las agrupaciones SQL convierten explícitamente UTC al calendario local.

Hay tres conjuntos diferentes de datos:

1. Pedidos creados durante el período, agrupados por `orders.created_at`.
2. Entregas COMPLETADA finalizadas durante el período, por `deliveries.completed_at`,
   aunque su pedido se haya creado antes del período.
3. Estado actual de pendientes, actividad, conectividad, turnos, alertas y usuarios.
   Cambiar el período no convierte estos conteos actuales en estados históricos.

No se divide el segundo conjunto entre el primero para anunciar una tasa de
entrega: corresponden a cohortes distintas. No se presenta ingreso, costo,
rentabilidad o crecimiento sin una fuente contable compatible.

Las consultas se realizan bajo el aislamiento normal de la sesión. Son una
lectura operativa de varias sentencias; escrituras simultáneas pueden producir
pequeñas diferencias entre el resumen y las series. No constituyen un cierre
contable ni garantizan una fotografía transaccional con `REPEATABLE READ`.

## Diccionario del snapshot operativo

`app/schemas/operational_dashboard.py` define el DTO nuevo y conserva intactos
los DTO legacy de `app/schemas/dashboard.py`.

| Campo | Tipo | Fuente y significado |
| --- | --- | --- |
| `summary.orders_created` | entero | Pedidos creados en `[inicio, fin)` |
| `summary.cancelled_orders` | entero | Pedidos de ese conjunto cuyo estado actual es CANCELADO |
| `summary.completed_deliveries` | entero | Entregas COMPLETADA finalizadas en `[inicio, fin)` |
| `summary.pending_orders` | entero | Todos los pedidos actualmente PENDIENTE |
| `summary.in_progress_orders` | entero | ASIGNADO, EN_RECOLECCION, RECOLECTADO o EN_RUTA |
| `summary.active_deliveries` | entero | INICIADA, EN_PICKUP, EN_ROUTE o EN_DESTINO |
| `summary.riders_online` | entero | `is_online=true`, ACTIVO/OCUPADO y usuario activo |
| `summary.available_riders` | entero | Igual criterio de conectividad, con estado ACTIVO |
| `summary.active_shifts` | entero | EN_CURSO, entrada registrada y salida ausente |
| `summary.open_alerts` | entero | Alertas canónicas OPEN o ACKNOWLEDGED |
| `summary.active_users` | entero | Usuarios con `is_active=true` |
| `summary.avg_delivery_minutes` | número o null | Media de `(completed_at-started_at)/60` en entregas del período con inicio y duración no negativa |
| `summary.valid_duration_count` | entero | Entregas incluidas en esa media |
| `summary.sla_percent` | número o null | `100 × SLA verdadero / SLA no nulo` del conjunto completado |
| `summary.sla_known_count` | entero | Entregas completadas con `sla_compliant` verdadero o falso |
| `summary.sla_unknown_count` | entero | Entregas completadas sin resultado SLA |
| `series[]` | lista | Un registro por día, incluyendo días sin actividad |
| `series[].date` | fecha ISO | Día local |
| `series[].orders_created` | entero | Pedidos creados ese día en el período |
| `series[].completed_deliveries` | entero | Entregas completadas ese día en el período |
| `period_start`, `period_end` | timestamp UTC | Límites de la consulta |
| `timezone` | texto IANA | Calendario aplicado |
| `generated_at` | timestamp UTC | Reloj capturado al construir la consulta |
| `source` | texto | `database_snapshot` |
| `financials_available` | booleano | `false`; este contrato no expone contabilidad |

Sin entregas, el conteo es cero y SLA/duración son `null`. Una medición real de
cero minutos o un SLA conocido de 0 % se mantienen como cero. Un SLA desconocido
no se contabiliza como incumplido. Una duración negativa no se incluye en la media.

Los nombres legacy `orders_today`, `delivered_today`, `sla_compliance_pct` y
`sla_breached` se exponen para períodos de un día; en períodos mayores son `null`.
`delivered_today` conserva el criterio histórico de pedidos creados hoy cuyo
estado es ENTREGADO, mientras `summary.completed_deliveries` usa el criterio
explícito de finalización de entregas. `sla_breached` cuenta resultados falsos
conocidos del conjunto completado. `active_riders` y `avg_delivery_time_min` son
alias del resumen. Los clientes nuevos usan `summary` y `period_*`.

## Vistas previas del operador

| Campo | Contenido | Límite |
| --- | --- | --- |
| `pending_orders[]` | UUID, referencia externa nullable, estado, dirección de entrega y prioridad nullable | 20 |
| `queue_truncated` | Hay más resultados que la vista previa | booleano |
| `riders_online[]` | UUID, latitud, longitud y `recorded_at` UTC | 50 |
| `positions_truncated` | Hay más posiciones elegibles | booleano |

La cola incluye pedidos PENDIENTE/ASIGNADO de cualquier antigüedad y se ordena por
creación e ID. Se consulta un resultado extra para anunciar truncamiento. No se
usa su longitud como total de pedidos pendientes.

Las posiciones requieren los permisos y estado de conectividad indicados,
coordenadas válidas y timestamp dentro de los últimos cinco minutos, sin datos
del futuro. Se admiten coordenadas cero; se rechazan NaN y valores fuera de rango
en SQL. El orden es timestamp descendente e ID. El total conectado puede superar
la cantidad de posiciones recientes o el límite de cincuenta. El panel no afirma
que la bandera `is_online` pruebe una conexión WebSocket o presencia instantánea.
El panel de gerente devuelve las listas vacías; ofrece acceso al mapa existente.

## Historial consolidado y ranking

El historial lee `ProductivityMetrics`, no los eventos `ProductivityRecord`.
Selecciona registros sin `shift_id` para evitar sumar una consolidación diaria
junto con sus turnos. Ordena por inicio descendente e ID y limita a cien registros.
Devuelve UUID, repartidor, inicio/fin UTC, conteos de entregas, SLA conocido y
desconocido, duración media, distancia, importe histórico, origen y score nullable.

`sla_percent` se recalcula sobre on_time + late conocidos. Sin denominador
conocido devuelve null. Duración, distancia e importe nulos, no finitos o negativos
se exponen como null; el importe histórico no se certifica como ingreso conciliado
y no se agrega al panel financiero. `performance_score` es null.

Períodos duplicados de un repartidor generan HTTP 409, incluso con `limit=1`:
una función ventana detecta duplicados antes del límite. Períodos invertidos o
vacíos, conteos negativos o SLA conocido superior al total también generan 409.
No se elige silenciosamente un registro para reparar el historial.

El ranking consulta entregas COMPLETADA por fecha de finalización y ordena por
cantidad descendente, con UUID de repartidor como desempate estable. Retorna
puesto, repartidor, cantidad, SLA conocido, duración media válida,
`ranking_basis=completed_deliveries` y `performance_score=null`. Es un ranking
de volumen, sin ponderación ficticia de calidad, dinero o calificaciones.

Los helpers legacy de DashboardService mantienen sus nombres. El operador usa
enums existentes y cuenta riesgo a quince minutos del objetivo SLA positivo,
incluyendo vencidas, solo en entregas activas con inicio válido. El comparativo
usa `period_start` en lugar de `created_at`, rechaza duplicados y limita el trabajo
a diez mil consolidaciones. No inventa `deliveries_per_hour`, que no se almacena.

## Frontend, sesiones y recuperación

`operational-dashboard.service.ts` valida la respuesta antes de mostrarla: tipos,
conteos enteros seguros, valores finitos, nulabilidad, coherencia de conteos SLA,
fechas, calendario, límites y coordenadas. No convierte errores o cadenas en cero.

`useOperationalDashboard` identifica cada consulta por usuario, rol, revisión de
sesión, generación de credenciales, modo y período. Cancela al desmontar o cambiar
esa identidad y no publica respuestas de consultas retiradas. El timeout de
quince segundos funciona aunque un adaptador ignore AbortSignal. La rotación
normal de tokens de la misma sesión no invalida una respuesta legítima.

Al cerrar sesión, perder rol o cambiar de cuenta desaparecen los datos privados.
Una consulta fallida muestra un mensaje genérico, sin direcciones, tokens o
diagnósticos del servidor. Actualizar permite recuperar datos; al cambiar período
se retira el anterior. No hay polling ni actualización por WebSocket en este panel.

El selector ofrece hoy/siete/treinta días. La tabla accesible y sus barras usan
conteos diarios reales. Los accesos llevan a páginas existentes de pedidos,
entregas, mapa, repartidores, reportes, alertas y finanzas según el modo.

## Validación y pendientes

`tests/test_operational_dashboard.py` usa esquemas PostgreSQL privados y una base
explícita `test_*`, con JWT, dependencias, middleware y rutas de la aplicación real.
Comprueba permisos, revocación, alias, calendario/DST, cohortes, nulos/ceros,
truncamiento, conectividad, coordenadas, duplicados, ranking y contratos legacy.
Las tres suites nuevas del frontend cubren parser, sesión, cancelación y render.
El informe raíz de la entrega registra los resultados finales y las deudas globales.

Quedan pendientes carga con volúmenes productivos/planes SQL, índices derivados de
esa medición, estrategia de fotografía consistente o agregados materializados,
datos históricos depurados, actualización por outbox/WebSocket y observabilidad.
Las consultas agregadas requieren medir costo antes de aumentar su frecuencia.

El antiguo `hooks/useProductivity.ts` aún solicita contratos más amplios
(`/metrics`, `/riders`, `/time-metrics`, `/sla`) que este bloque no implementa ni
conecta a los paneles nuevos. El helper legacy de productividad del repartidor
conserva limitaciones históricas de su servicio; no se certifica aquí toda la UI
del rider ni una puntuación integral. Faltan gráficos/flujo de productividad
completos y filtros/exportación de grandes historiales.

También siguen pendientes las deudas globales de tipos y cobertura, pagos con
evidencia/conciliación, outbox, sesiones por dispositivo, operación de workers en
staging, unificación de trazas/rutas, móvil/offline y homologación fiscal. Este
bloque no constituye certificación del sistema al cien por ciento para producción.

La revisión identifica un candidato concreto para el siguiente bloque:
integraciones sigue montado desde `routers_combined` con prefijo repetido y
serializa `type`/`is_active`, mientras el modelo declara `integration_type`/`status`.
No se corrige aquí; requiere contrato y pruebas propios, conservando fuera de las
respuestas cualquier configuración sensible de los proveedores.

# Workers operativos y programación explícita — entrega 52

Fecha de usuario: 29 de octubre de 2026, America/Caracas. El entorno de ejecución
ya está en 30 de octubre UTC. Este bloque corrige el registro y la ejecución de
tareas; no constituye una autorización de despliegue, pagos ni borrado productivo.

## Fallos corregidos

- SLA, liquidación y limpieza importaban backend.app.workers aunque el servicio
  se ejecuta desde backend con el paquete app. Otros workers importaban la fábrica
  inexistente get_db_session, mezclaban SQL síncrono/asíncrono y podían cerrar una
  variable no inicializada.
- La productividad consultaba delivery_time, delivered_at o duration_minutes
  inexistentes, e intentaba construir métricas con campos ajenos al modelo. La
  tarea diaria estaba definida en otro módulo y utilizaba aliases inexistentes.
- El monitor SLA restaba fechas aware/naive, convertía UUID a enteros, repetía
  alertas y modificaba datos operativos mientras atrapaba errores de los avisos.
- La liquidación intentaba marcar como liquidados registros sin los campos
  consultados ni evidencia de un pago. La limpieza borraba auditoría/notificaciones
  por una única antigüedad, sin política por tabla o retención legal.
- PUSH/EMAIL/SMS legacy imprimían destinatarios/contenido y devolvían success=true
  sin transporte. Los reportes inventaban ceros, importaban DataExporter inexistente
  y construían una ruta de archivo con parámetros no validados.
- Había dos modelos de alerts; el módulo de compatibilidad declaraba además el
  atributo reservado metadata. Ahora reexporta el único modelo usado por la app.

## Registro y arranque

Hay ocho módulos canónicos y doce tareas registradas bajo app.workers.*. Los
imports por backend.app.* desaparecen de estos workers. Desde el directorio
backend y con la configuración real del entorno establecida:

```bash
celery -A app.workers.celery_app:celery_app worker --loglevel=INFO
```

La validación ejecuta un worker real de Celery con pool solo, un broker Redis
temporal y una cola exclusiva de pruebas. Comprueba ping, doce tareas registradas,
ejecución por la cola y resultado del envío legacy rechazado. No conecta al broker
productivo ni ejecuta pagos, limpieza o envío externo. No se certifica con esa prueba
todo pool/prefork/gevent, topología HA, backend de resultados o entorno operativo.

## Configuración y tareas

| Ajuste | Predeterminado | Efecto |
| --- | --- | --- |
| CELERY_TIMEZONE | America/Sao_Paulo | Zona IANA del calendario; mantiene el valor anterior, ahora configurable/validado |
| CELERY_BEAT_ENABLED | false | Permite construir la agenda aprobada, no habilita tareas por sí solo |
| WORKER_SLA_MONITOR_ENABLED | false | Habilita ejecución del monitor y la entrada de Beat si también se habilita Beat |
| WORKER_PRODUCTIVITY_ENABLED | false | Habilita cálculo por rider/diario y su entrada de Beat |
| WORKER_REPORTS_ENABLED | false | Habilita reportes operacionales de lectura; no tiene entrada Beat |
| WORKER_NOTIFICATION_RETRY_ENABLED | false | Habilita la tarea manual de la cola persistida; no tiene entrada Beat |

Una tarea deshabilitada devuelve success=false, reason=worker_disabled antes de
abrir BD o transporte. Estos ajustes se leen por proceso; cambiar el entorno
requiere reiniciar los procesos correspondientes y no es una pausa distribuida
atómica. Las llamadas internas run_* y WorkerJobs son código de confianza; no son
endpoints ni autentican al actor. Proteger productores, credenciales, colas y acceso
al broker sigue siendo responsabilidad del despliegue.

Para usar un calendario venezolano, definir CELERY_TIMEZONE=America/Caracas en el
entorno elegido y comprobarlo en staging. No se infiere la zona del servidor ni se
cambia silenciosamente el calendario existente. La agenda se construye al importar
la app; con los valores predeterminados está vacía. Cuando se activan los ajustes:

| Entrada | Tarea | Frecuencia |
| --- | --- | --- |
| check-sla-every-5-min | app.workers.sla_monitor_worker.check_sla_breaches | Cada cinco minutos |
| daily-productivity | app.workers.productivity_worker.calculate_daily_productivity | 01:00 local, sobre el día anterior ya cerrado |

No se incluyen liquidación, limpieza, envío directo, reportes, reintentos de
notificación ni análisis de rutas en Beat. No se inicia Beat durante las pruebas.
Un despliegue futuro debe controlar su liderazgo para no multiplicar productores;
los locks cooperantes no sustituyen esa coordinación.

## Recursos y errores

Cada invocación de los jobs nuevos abre su propio engine async con NullPool y su
sesión contextual, y dispone el engine al finalizar, incluso ante error. No se
comparte una conexión asyncpg de un event loop con otro creado por asyncio.run.
La sesión revierte excepciones/cancelación; los servicios confirman explícitamente
sus unidades de trabajo. Las lecturas no se presentan como escrituras confirmadas.

Entrada o datos que requieren revisión devuelven reason=manual_review_required.
Los fallos de infraestructura reintentan hasta tres veces con error genérico. Se
invoca retry fuera del bloque except, porque Celery.retry lanza por sí mismo: así
la excepción original no queda como contexto de la traza final. No se declara
auditada toda la salida de logs de dependencias o del sistema por esta medida.

## Productividad de día cerrado

calculate_rider_productivity recibe rider UUID en texto y fecha YYYY-MM-DD.
calculate_daily_productivity recibe una fecha opcional; sin fecha usa el día local
anterior. Se rechazan fecha actual/futura, formatos libres, mínimo de calendario
no utilizable y UUID inválido. Se construye el intervalo [medianoche, medianoche
siguiente), se convierte a UTC naive y se consulta con >= inicio y < fin. Hay
pruebas para días de 23, 24 y 25 horas; no se omite la fracción final del segundo.

La cohorte son entregas COMPLETADA cuyo completed_at cae en ese intervalo. Incluye
actividad histórica de riders que ya no están ACTIVO; no mezcla pedidos creados
ese día con entregas cerradas en otro. No incluye FALLIDA como entrega exitosa.

| Campo de productivity_metrics | Cálculo |
| --- | --- |
| total_deliveries | Cantidad de entregas completadas en el período |
| on_time_deliveries / late_deliveries | Solo SLA explícitamente true / false |
| sla_compliance_rate | Porcentaje sobre SLA conocidos; NULL si ninguno es conocido |
| avg_delivery_time_minutes | Diferencia completed_at-started_at de duraciones válidas; NULL sin observaciones válidas |
| total_distance_km | Suma solo si todas las distancias son finitas/no negativas/conocidas; NULL si falta alguna |
| total_earnings / customer_rating_avg / customer_rating_count | No calculados aquí: NULL en filas nuevas; valores anteriores conservados al recalcular |

La respuesta incluye unknown_sla_count, missing_duration_count y
missing_distance_count. No se convierte un SLA NULL en retraso ni un dato de
ingresos/calificación ausente en cero. Un día sin completadas sí tiene conteo cero;
no se inventa velocidad, salario, rating o duración.

Se bloquea Rider antes de buscar/escribir la métrica sin shift_id para el período.
Los reintentos cooperantes conservan el ID y no crean otra fila. Si ya hay más de
una fila histórica de ese tipo, se exige revisión y no se fusionan/borran datos.
El índice existente no es UNIQUE: no se garantiza exclusión con escritores ajenos
al lock. El cálculo usa hasta 10000 entregas por rider/día, rechaza exceso y no
guarda un resultado parcial. El job diario procesa hasta 1000 riders y confirma
cada rider; un fallo posterior puede dejar riders previos confirmados y el replay
los recalcula. No hay cursor durable ni recuperación de grandes lotes todavía.

Estas métricas van a productivity_metrics; no se inventan propiedades agregadas
en productivity_records ni se afirma conectada una interfaz nueva. No determinan
pagos, sanciones, niveles o bonos automáticamente.

## Vigilancia SLA y bandeja local

El monitor consulta entregas INICIADA, EN_PICKUP, EN_ROUTE o EN_DESTINO con
started_at y objetivo positivo. Solo crea evidencia si el reloj UTC supera el
plazo exacto; igualdad con el deadline no es exceso. Sin objetivo no supone
sesenta minutos. Cada lote admite hasta cien entregas y bloquea sus filas con
FOR UPDATE SKIP LOCKED. Se comprueba de nuevo el evento bajo el lock.

Crea un Alert canónico con alert_type=SLA_BREACH, severity=HIGH, status=OPEN y
UUID reales de entrega/pedido/rider. Un evento previo de ese tipo para la entrega
evita repetirlo. No modifica Delivery.sla_compliant, sla_actual_minutes, estado,
snapshots financieros o bonos. La observación de una entrega activa no sustituye
su resultado final de SLA o su cierre.

Se crean logs IN_APP para gerentes/superadministradores activos y el usuario
activo del rider. Se respeta NOTIFICATIONS_ENABLED y la preferencia desactivada
de sla_warning/IN_APP. Una pausa o preferencia no impide conservar el Alert; no
se reenvían retrospectivamente avisos al reactivar esos ajustes. Se limita la
consulta a doscientos supervisores y se exige revisión si se supera ese volumen.

Alert y logs se confirman juntos. Cada log usa dedupe_key de entrega+destinatario,
con la restricción UNIQUE ya existente; los analizadores cooperantes no duplican
el evento o su bandeja. No se añade UNIQUE a alerts ni se garantiza exactamente
una vez ante borrado externo o escritores no cooperantes.

Los logs quedan PENDIENTE, sin next_retry_at, como contenido local de la bandeja.
No significan un mensaje entregado a un proveedor. Este job no publica Redis/WS
ni llama PUSH/SMS/EMAIL; la lectura REST de la bandeja permite recuperarlos. Siguen
pendientes un outbox de eventos y la actualización instantánea de ese productor.

generate_operational_alert mantiene su nombre y firma legacy, pero solo admite
sla_warning/SLA_BREACH con severidad high y delivery_id UUID. Reevalúa los hechos
persistidos mediante el mismo monitor; no acepta texto arbitrario como evidencia
ni crea una notificación huérfana. Otros tipos requieren un flujo implementado.

## Notificaciones, reportes y acciones bloqueadas

process_notification_retries delega al servicio omnicanal existente, con su sesión
dedicada, locks, preferencias, pausa global y política de proveedores. Admite entre
1 y 100 logs, por defecto 50. processed_logs expresa trabajo procesado, no mensajes
entregados. Habilitarlo puede contactar proveedores configurados: aquí solo se
prueban dobles o SDK con HTTP sustituido, sin envíos externos.

Los entry points send_push_notification/send_email_notification/send_sms_notification
devuelven success=false, reason=persisted_notification_required y no imprimen sus
argumentos. Sus productores deben migrar al flujo persistido; no basta activar un
flag para recuperar el antiguo éxito simulado.

generate_daily_report admite operations y devuelve JSON con conteos SQL de pedidos
creados por estado y entregas terminales cerradas por estado en el día elegido,
además de los límites UTC y source=database_snapshot. Son cohortes distintas, no
un denominador de rentabilidad o SLA. Son consultas de lectura bajo el aislamiento
normal, no un cierre contable auditado. No crea archivos con nombres enviados por
el usuario. financial y tipos desconocidos devuelven rechazo explícito.

run_daily_liquidation devuelve verified_settlement_required y paid_records=0,
sin tocar tablas financieras. cleanup_old_data devuelve
reviewed_retention_policy_required y deleted_records=0, sin borrar auditoría o
notificaciones. No tienen entrada Beat ni un flag que habilite su simulación.
Un estado Celery SUCCESS puede indicar que el handler devolvió correctamente un
rechazo; no debe confundirse con success=true o una operación de negocio realizada.

## Esquema, pruebas y límites de producción

Se tipan 54 columnas existentes: 16 productivity_metrics, 11 sla_records,
nueve productivity_records y 18 alerts. El contrato compara DDL PostgreSQL,
defaults/onupdate, índices, claves foráneas y enums sin cambiar el esquema. No
hay migración nueva. Las relaciones Shift/ProductivityRecord se vinculan en ambas
direcciones; el import app.models.alert.Alert reexporta el modelo canónico sin
declarar otra tabla ni el atributo reservado metadata. Los enums legacy de ese
módulo se conservan como símbolos, sin convertir automáticamente estados antiguos.

El CI del PR #292 detectó un timeout de la prueba de dos sockets, mientras las
otras 1513 pruebas backend aprobaron. Starlette 0.37.2 usa un bucle sleep(0) en el
receive de TestClient. La prueba concurrente usa ahora la app ASGI real con colas
que esperan mensajes en un solo loop. Comprueba dos/cuatro conexiones propias y
una ajena, sin duplicados ni cruce de datos, conservando límites de espera. No se
relajan autenticación o autorizaciones productivas; no se cambia el WebSocket
productivo para ocultar el fallo. Se ejecuta diez veces en cinco tandas locales;
el resultado del nuevo CI se informa por separado.

Los tests nativos usan un PostgreSQL temporal y schemas privados, con sesiones
distintas para concurrencia, rollback, replay, días cerrados, NULL conocidos,
plazos exactos, preferencias, límites y loops sucesivos. También se prueba un
worker real con broker temporal. Los resultados del cierre están en
Implementacion_de_mejoras_V1.md. El test local usa Python 3.12; el CI usa 3.11.

Antes de desplegar: validar esquema/duplicados y zona horaria en staging, configurar
el broker y reiniciar todos los consumidores cooperantes. Siguen pendientes
liderazgo Beat, observabilidad, tiempos máximos/reclamación durable, idempotencia
global y grandes lotes, retención por tabla/legal hold, liquidación con proveedor
y conciliación, UI y outbox. Continúan Mypy/cobertura globales y la homologación
fiscal. No se declara producción completa ni se habilita ninguna operación real
en el entorno del usuario durante esta entrega.

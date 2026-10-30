# Cancelación coordinada de órdenes — entrega 58

## Finalidad y alcance

Cerrar una orden debe cerrar su operación asociada. Antes, el cambio genérico a
`CANCELADO` podía dejar una entrega activa y permitir su cierre posterior con un
bono. Ahora ambos endpoints de cancelación usan una operación transaccional común:
`Order.CANCELADO`, `Delivery.CANCELADA`, `Route.CANCELADA`, resolución de alertas
SLA pendientes y un recibo de auditoría. No se representa una cancelación como
un intento fallido del repartidor.

## Contrato de acceso y datos

- `PATCH /api/v1/orders/{id}/cancel`, JSON `{"reason":"Cliente solicita cancelar"}`:
  SUPERADMIN o GERENTE, cuenta activa. Motivo recortado, de 8 a 500 puntos de
  código Unicode, sin controles, caracteres de formato ni sustitutos. Para
  compatibilidad, omitir la propiedad conserva el motivo histórico del schema:
  «Solicitada por el administrador»; null o un texto inválido se rechazan.
  La interfaz exige escribir un motivo y no usa ese default.
- `PATCH /api/v1/orders/{id}/status?new_status=CANCELADO`: misma autorización;
  conserva sus parámetros y registra el motivo fijo «Cancelación solicitada
  mediante cambio de estado». Operadores/repartidores no pueden usarlo como
  bypass de cancelación. No cambia su permiso para otras operaciones autorizadas.
- El servicio común reconsulta rol, actividad y, si se proporciona, versión del
  token antes de bloquear y antes de modificar. No mantiene un bloqueo permanente
  del usuario: una revocación posterior a la última comprobación no queda
  serializada hasta el commit. La siguiente solicitud vuelve a autenticarse.
- Respuesta de orden: conserva los campos y añade los existentes
  `cancellation_reason` y `cancelled_by` al serializador.
- Errores: 400 entrada inválida, 401 cuenta/token no vigente, 403 rol insuficiente,
  404 orden inexistente, 409 conflicto que exige revisión, 503 falta el enum físico.

Los estados iniciales permitidos son PENDIENTE, ASIGNADO, EN_RECOLECCION,
RECOLECTADO y EN_RUTA. Una orden pendiente sin entrega también puede cancelarse.
Si existe entrega, debe estar activa y concordar su rider con la asignación de la
orden. Se bloquean entregas terminales, múltiples entregas, rutas múltiples o
terminales, más de cien alertas SLA pendientes y snapshots de bono congelado,
incluyendo un importe cero.

Se rechaza evidencia financiera por las claves `pago_entrega_{order_id}` y
`pago_fallido_{order_id}`, o por `reference_id`/`source_id` igual al ID de orden o
entrega. Cualquier ElectronicInvoice o PaymentDistributionSnapshot relacionado
también bloquea la operación. Es una barrera conservadora: una factura sandbox
o rechazada igualmente requiere revisión. No pretende descubrir referencias
históricas almacenadas con convenciones desconocidas.

## Atomicidad, concurrencia y reintentos

Orden de bloqueos: Order → Delivery → Rider asignado → Route → alertas SLA.
Las escrituras operativas de entrega cooperan bloqueando primero la orden. El
servicio usa `flush`; con `commit=False` el llamador es propietario de confirmar
o revertir toda la transacción. Los endpoints usan `commit=True`, con rollback
si falla la preparación o el commit. Las pruebas ejercitan fallos tardíos y
solicitudes concurrentes con sesiones PostgreSQL independientes.

Un reintento devuelve éxito sin otra auditoría únicamente si coinciden actor,
motivo normalizado, campos canónicos, entrega y asignaciones conservadas, IDs de
rutas, estados cancelados y recibo exitoso. Un motivo o actor diferente devuelve
409. Una cancelación histórica parcial sin recibo no se «repara» automáticamente.
Es necesario revisarla y definir un procedimiento de reparación explícito.

Se conservan asignaciones, instrucciones, OTP, pruebas y coordenadas. No se
inventa `completed_at`. Solo alertas SLA_BREACH OPEN/ACKNOWLEDGED pasan a RESOLVED
con actor, fecha y motivo; incidentes y notificaciones ya registradas se conservan.
El monitor SLA omite también órdenes históricas canceladas con entrega activa.

Los cierres, inicio, ubicación y asignación de entrega verifican la orden padre;
CRUD de orden/entrega y persistencia de rutas cierran caminos de reapertura. La
suscripción a tracking de una orden cancelada se rechaza. El canal general del
rider mantiene su política de acceso, porque puede servir a otras órdenes.
La emisión fiscal y el reparto de ingresos bloquean la orden y no crean nueva
evidencia para una cancelada. No se modifican facturas/snapshots anteriores.

## Dinero y reservas

La cancelación no genera bonos, débitos, créditos, devoluciones ni compensaciones.
Conserva ledger legacy, cache de rider, wallet moderna y solicitudes de retiro
pendientes. Una reserva de retiro pertenece al retiro, no se libera por cancelar
una orden. No hay integración de reembolso de cobros a clientes en este cambio.
Un pedido ya remunerado, facturado o distribuido exige revisión/compensación en
un flujo separado; no puede ser cancelado por esta operación.

## Diccionario y migración física

| Elemento | Cambio / significado |
| --- | --- |
| `deliverystatus` / `deliveries.status` | Añade el valor final `CANCELADA` a los siete valores anteriores, sin reescribir filas |
| `orders.status` | Usa el valor existente `CANCELADO` |
| `orders.cancellation_reason` | Campo existente: motivo normalizado |
| `orders.cancelled_by` | Campo existente: UUID del usuario en texto |
| `routes.status` | Usa `CANCELADA`, ya existente |
| `alerts` | Usa sus campos de resolución existentes únicamente para alertas SLA pendientes |
| `audit_logs` | `STATUS_CHANGE`, recurso `order_cancellation`, estados e identidades anteriores/nuevos, motivo, actor, `money_changed=false` |

Revisión Alembic `20261030_delivery_cancel`, padre `20261029_fiscal_integrity`.
Se inspecciona el enum real de `deliveries.status`, incluyendo su esquema, en vez
de crear un tipo paralelo. Se rechazan tipos/etiquetas inesperados. No añade
columnas, índices ni dependencias. No funciona como SQL offline: requiere acceso
al catálogo PostgreSQL para validar el destino.

**Despliegue coordinado obligatorio:** validar primero la revisión anterior,
respaldos y datos; ejecutar la migración en una transacción propia y confirmar;
desplegar lectores/escritores API, workers y frontend compatibles antes de admitir
la primera CANCELADA. PostgreSQL no permite usar un valor añadido al enum antes
de confirmar su transacción. Procesos antiguos pueden fallar al leer CANCELADA:
usar mantenimiento o despliegue coordinado sin lectores antiguos cuando haya
filas nuevas. La comprobación 503 protege una base sin migrar, pero no sustituye
ese orden operativo. Esta entrega no ejecuta migraciones ni despliegues productivos.

El downgrade toma bloqueo exclusivo y se niega si existe una fila CANCELADA,
consumidores adicionales del tipo, etiquetas desconocidas o un tipo temporal
conflictivo. Sin esos conflictos reconstruye el enum anterior, conserva filas y
restaura el default. Dependencias adicionales de PostgreSQL pueden impedirlo:
`DROP ... RESTRICT` y la transacción conservan la base ante el error. No hay
conversión automática de CANCELADA a FALLIDA ni eliminación de historial.

## Interfaz, pruebas y límites

El cliente reconoce CANCELADA y el alias histórico CANCELADO, los filtra y
presenta con estado neutral. La ficha del repartidor cierra acciones si la orden
o la entrega está cancelada y muestra el motivo recibido; no muestra un bono
proyectado como confirmado. Gerencia requiere motivo válido y no cambia al
endpoint genérico cuando el servidor rechaza la cancelación.

Pruebas nativas: ambos endpoints, roles, entradas, estados/evidencias conflictivos,
saldo y reservas conservados, auditoría e idempotencia, rollback, revocación antes
de la escritura, carreras, bloqueo de cierres/reasignación/ubicación, tracking,
reparto, fiscalidad sin consumir numeración y migración física. Pruebas de interfaz
incluyen cancelaciones históricas parciales y validación Unicode.

Los reportes históricos de entregas completadas/fallidas conservan sus reglas;
canceladas no reciben fecha ficticia ni se contabilizan como fallos. No se añade
en esta entrega un KPI independiente de cancelaciones. Sigue pendiente homologar
todo el grafo de estados, reparación histórica, compensaciones/reembolsos,
outbox/reintentos durables, políticas de bonos, monedas/libros y los demás hitos
del roadmap. Tampoco elimina por sí sola la deuda global de tipos/cobertura.

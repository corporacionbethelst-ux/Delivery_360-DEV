# Delivery360 — entrega 123

## Fallos y cancelaciones con avisos internos duraderos

Los fallos registrados mediante `POST /deliveries/{id}/fail` o
`PATCH /deliveries/{id}/status` guardan ahora el comprobante IN_APP
`entrega_fallida`. La cancelación coordinada guarda `orden_cancelada`, tanto
por la operación explícita como por el cambio de estado compatible. Los avisos
pertenecen a la cuenta del repartidor y se confirman junto con los estados,
la auditoría y los movimientos que correspondan a cada operación.

Se conserva el cálculo de bonos existente. Un intento sin bono también produce
su aviso operativo. El comprobante no acredita cobro, transferencia ni pago;
no contiene OTP, importes inferidos ni las observaciones privadas del intento.
Los nuevos eventos guardan la fecha UTC del registro, sin inventar una fecha
histórica de fallo o cancelación.

## Coherencia antes de cerrar

La pantalla `/manager/operations/orders` reemplaza el cambio rápido incompleto
a FALLIDO por un modal central con motivo obligatorio. Usa la operación existente
de entrega fallida; no cambia sólo la orden ni selecciona una causa por defecto.
El catálogo de causas se comparte con la pantalla del repartidor, conservando
sus etiquetas. Los errores permanecen dentro del modal y puede consultarse el
estado sin volver a emitir una escritura.

El cambio genérico de orden a FALLIDO devuelve 409 e indica usar la operación de
entrega con motivo. El servicio de órdenes anterior aplica la misma protección.
Las operaciones de fallo verifican, bajo los bloqueos existentes, que la orden
siga activa y corresponda a la asignación de la entrega. Una contradicción requiere
revisión: no se sobrescribe un cierre previo ni se calcula un bono para ocultarla.
Las observaciones aceptadas por la operación de fallo se conservan ahora en el
detalle de la entrega y en las notas de la orden; no se difunden en el aviso.

## Reintentos, historial y recuperación

La deduplicación conserva un aviso por orden, evento y canal, incluido su estado
de lectura. Un fallo del aviso o del commit revierte la unidad completa; no quedan
bonos, cambios de ruta o avisos anunciados de una operación revertida. La señal
WebSocket privada se publica después del commit exterior y sólo llega a su dueño.
La bandeja REST conserva la recuperación cuando falla el transporte.

La cancelación sin entrega puede avisar a una cuenta de repartidor realmente
asignada a la orden. Si no hay asignación, no inventa un destinatario. Los reintentos
de cancelaciones históricas verificadas no reconstruyen avisos ausentes ni reinician
la lectura. No se reescriben cancelaciones ni comprobantes anteriores.

## Validación y alcance

Las pruebas con PostgreSQL y Redis aislados cubren ambos puntos de fallo, ambas
entradas de cancelación, bono positivo/cero, cancelaciones sin entrega/asignación,
rollback de estados/saldos/auditoría/rutas/alertas, historial, deduplicación,
concurrencia entre fallo y cancelación, observaciones y privacidad WebSocket.
El frontend comprueba motivo obligatorio, errores, consulta, duplicados y respuestas
tardías tras cambiar credenciales o desmontar el modal.

No hay migración de esquema ni endpoint nuevo. La restricción 409 del cambio
genérico a FALLIDO es deliberada; los clientes deben usar la entrega con motivo.
Los canales externos de estos cierres, la conciliación de resultados ambiguos y
la homologación de proveedores continúan pendientes. Base: `3b798b1` (entrega 122).
La integración se condiciona a los controles completos de CI y preserva el historial.

# Delivery360 — entrega 119

## Avisos de asignación en la misma transacción

La asignación manual guardaba su aviso después de confirmar la orden, y la
asignación desde entregas dependía de una tarea en memoria. Una interrupción
podía dejar la asignación confirmada sin aviso recuperable. Los distintos
puntos de entrada tampoco compartían la misma bandeja.

Ahora `apply_order_assignment` prepara un comprobante IN_APP en
`notification_logs` junto con la orden, entrega y auditoría. Las asignaciones
manuales, automáticas, desde entregas y desde el servicio de órdenes utilizan
ese punto común. Si no se puede guardar el comprobante, se revierte la unidad
completa. No se confirma la orden con un aviso perdido por un fallo SQL.

La identidad del evento corresponde a su auditoría. Evento y canal determinan
la clave única del aviso. Un reintento de la misma asignación conserva el aviso,
las fechas y la auditoría anteriores; una reasignación real conserva su evento
nuevo y su destinatario propio. El aviso automático legacy se conserva por
compatibilidad, pero la bandeja visible utiliza el comprobante IN_APP.

## Canales externos y recuperación

Con notificaciones externas habilitadas, se consultan la plantilla activa y los
canales permitidos por rol y preferencias. Su texto queda capturado en filas
PENDIENTE dentro de la transacción. Los proveedores se contactan después por
el consumidor persistido existente, con bloqueo de filas y SKIP LOCKED.

Los avisos de asignación no deducen ganancias del precio de la orden. Una
plantilla que exige importes o variables no disponibles queda FALLIDO para
revisión. No se sobrescribe la plantilla ni se inventan cantidades. El aviso
interno sigue disponible aunque falte plantilla, haya una pausa operativa o los
canales externos estén deshabilitados.

La plantilla histórica de `nuevo_pedido_asignado` incluye `payment_cents` y
necesita revisión antes de esperar avisos externos. Un texto compatible es:
`Nuevo pedido asignado: entrega {{delivery_code}}. Consulta la orden para ver su estado actual.`
El código no sobrescribe automáticamente una plantilla personalizada.

Antes de cada intento externo se vuelven a comprobar cuenta, rol, destinatario,
asignación abierta y coherente, plantilla, preferencias y configuración. Un
evento que ya no corresponde al repartidor se detiene. El texto histórico del
comprobante interno permanece como evidencia de la asignación anterior; hay
que consultar la orden para conocer su estado actual.

La bandeja y el contador se recuperan al abrir la campana o mediante su lectura
REST. Esta entrega no añade una señal WebSocket de asignación tras el commit.
La aceptación de un proveedor no garantiza recepción en dispositivo. Permanece
la ventana ambigua si el proveedor acepta y el proceso cae antes de guardar el
resultado; no se promete exactamente un envío externo.

## Verificación y alcance

Las pruebas usan PostgreSQL aislado y proveedores controlados. Comprueban
permisos, fechas, auditoría, reintentos, solicitudes simultáneas, rollback,
persistencia entre sesiones y recuperación con cambios de política. No se han
enviado avisos a personas ni modificado bases originales. No hay cambio de
esquema, nuevo endpoint, activación de proveedores o cambio financiero.

La rama parte del commit `0308b6e` de la entrega 118. Conserva íntegro su flujo
OTP y sus mensajes. La revisión de esta entrega depende de esa base y no
fusiona ramas automáticamente.

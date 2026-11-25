# Delivery360 — entrega 122

## Comprobante interno de entrega completada

Las entregas asignadas a un repartidor ahora guardan un comprobante IN_APP al
cerrarse correctamente. El aviso pertenece a la cuenta del repartidor y conserva
la orden, la entrega, el origen de la operación y la fecha de cierre disponible.
Es un comprobante operativo; no acredita cobro de cliente, retiro ni transferencia.

Se incorpora al cierre desde órdenes, al endpoint de entrega completa y a la
actualización unificada de estado. Se conserva la validación OTP anterior al
cierre, incluidos los ceros iniciales, y el cálculo financiero existente.
Las entregas con bono cero también generan el aviso operativo.

## Atomicidad y reintentos

El comprobante se guarda junto con la orden, la entrega y el registro financiero.
Un fallo de persistencia revierte toda esa unidad. El identificador de deduplicación
corresponde a la orden, el evento y el canal: llamadas repetidas dentro de la misma
transacción o posteriores conservan el identificador y el estado de lectura.

Un comprobante previo con destinatario, entrega, canal u origen contradictorios
requiere revisión. No se sobrescribe el historial para ocultar la inconsistencia.
Los rechazos de repetición de cierre y de OTP incorrecto conservan los contratos
anteriores de la API. Cuando no existe una orden o un repartidor asociado no se
inventa un destinatario para el aviso.

## Señal privada posterior al commit

Se reutiliza la publicación posterior al commit exterior de la entrega 120,
ampliada explícitamente al evento `entrega_completada`. El alias de asignación
permanece compatible. La tarea consulta el comprobante confirmado en una sesión
propia y el WebSocket revalida su propiedad antes de enviarlo.

Un rollback no anuncia el cierre. Un fallo de Redis conserva el comprobante y
la recuperación REST; la reconciliación periódica de la entrega 121 sigue vigente.
Este bloque añade únicamente el canal interno. Los canales externos de cierre,
los avisos de fallo/cancelación y los resultados externos ambiguos siguen pendientes.

## Validación y alcance

La bandeja REST y las señales exponen las fechas UTC con un desplazamiento
explícito. Así el navegador puede mostrarlas correctamente en Caracas en lugar
de interpretar una fecha UTC sin zona como hora local. Se conservan los instantes
almacenados y las fechas ausentes; no se migran ni recalculan registros históricos.

Las pruebas usan PostgreSQL UTF-8 y Redis aislados. Cubren los tres puntos de
entrada, bono positivo/cero, OTP incorrecto, deduplicación, estado leído conservado,
inconsistencia de destinatario, fallo de aviso/commit y entrega por WebSocket
únicamente a su propietario después de confirmar el cierre.

No hay migración de esquema, nuevo endpoint o cambio del frontend. La base es
`a728b16`, con las entregas anteriores integradas. Se publicará en main después
de aprobar la revisión de código, las pruebas y los controles completos de CI.

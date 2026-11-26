# Delivery360 — entrega 126

## Cierre administrativo de bloqueos técnicos

En `/notifications`, Gerente y Superadmin pueden cerrar el seguimiento de un
aviso externo que requiere revisión técnica. La acción exige una referencia y
confirmación explícita en un modal central. El aviso se conserva y aparece en
«Cierres técnicos», con referencia, observaciones, acta y fecha de Caracas.

Cerrar el seguimiento no reenvía, reconstruye ni borra mensajes. Tampoco afirma
aceptación del proveedor, entrega, lectura o pago. No cambia órdenes, retiros,
movimientos contables, importes ni saldos. Un resultado incierto con intento
válido mantiene la revisión de proveedor de las entregas anteriores; no puede
cerrarse por este procedimiento técnico. Los avisos válidos en cola tampoco.

## Revisión vigente e idempotencia

La consulta conserva su ruta y añade `view=pending|resolved` (pending por defecto).
Los bloqueos técnicos incluyen una revisión SHA256 del registro conservado y
un diagnóstico limitado. No se exponen errores internos, cuerpos originales,
destinos completos ni credenciales en ese diagnóstico. Las referencias de
entrega/retiro provienen de sus claves persistidas.

POST `/api/v1/notifications/terminal-dispatch/{notification_id}/resolve` recibe
UUID de resolución, revisión, acción literal `close_without_resend`, referencia
y observaciones. El servidor bloquea la fila y revalida el rol vigente. Si el
aviso cambió desde la consulta, rechaza el cierre y exige volver a leer.

El cierre guarda un acta y detiene cualquier próxima ejecución en la misma
transacción. Conserva literalmente payload, cuerpo, título, error original,
contador de intentos y fecha de envío. No genera un UUID de intento ficticio ni
marca el aviso como ENVIADO. Un fallo de commit revierte cierre y acta juntos.

Repetir la misma resolución con el mismo actor y contenido devuelve el mismo
comprobante. Otra clave, actor o contenido no sustituye un cierre previo. Dos
solicitudes concurrentes producen un solo cierre. El frontend conserva la clave
y los datos tras una respuesta ambigua; un error definitivo de validación permite
corregirlos. Una sesión distinta no recibe confirmaciones tardías de la anterior.

## Historial y retención

El acta identifica el cierre sin reescribir payloads históricos malformados.
Pendientes y cierres tienen paginación independiente. La consulta de cierres es
solo lectura. Los controles anteriores de lectura/borrado personal siguen
protegiendo los registros externos y los recibos internos mantienen su contrato.

La limpieza de notificaciones conserva los registros técnicos según la política
de la entrega 125. La limpieza genérica de auditoría conserva el acta mientras
exista su aviso; otros eventos antiguos mantienen su limpieza normal. El worker
comprueba el cierre antes de enviar, incluso si una tarea de mantenimiento
volviera a colocar el registro en cola.

## Verificación y límites

Pruebas PostgreSQL cubren los siete eventos, permisos de los seis roles,
revocación de rol, revisión obsoleta, validación, reintentos, dos resoluciones,
rollback, competencia con el worker, retención, paginación y conservación del
libro financiero. Una prueba SQLite comprueba el vínculo de UUID canónico con
sus registros compactos de prueba. El frontend comprueba consentimiento,
referencia, reintento congelado, consulta de recuperación y aislamiento de sesión.

El delta explícito de API conserva los contratos históricos: una ruta nueva,
un esquema nuevo y un parámetro de vista. No hay migración de esquema ni envío
real a proveedores en las pruebas. Los SDK se simulan.

Sigue pendiente homologar proveedores/destinos reales y consultar sus resultados.
Un nuevo envío de un aviso antiguo necesita un procedimiento independiente que
acredite su seguridad; esta entrega no proporciona un botón de reenvío forzado.
Continúan la aceptación del negocio, infraestructura y recuperación productiva.
Base: `c3fc6d8` (entrega 125). La integración exige revisión y CI completo del
commit candidato. No se despliega la aplicación en esta entrega.

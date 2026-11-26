# Delivery360 — entrega 125

## Asignaciones y retiros sin reenvío automático ante incertidumbre

Los nuevos avisos `nuevo_pedido_asignado`, `payout_solicitado`,
`payout_aprobado` y `payout_rechazado` usan el protocolo persistente de la
entrega 124. Conservan su contenido dentro de la transacción de negocio y
registran un intento antes de llamar al adaptador externo. Una respuesta
negativa, excepción, cancelación o fallo al confirmar la aceptación deja el
aviso retenido, sin otra ejecución automática. La configuración o un destino
ausente difieren la consulta sin consumir intentos.

Se usa el canal base de la plantilla activa, filtrado por las preferencias.
No se añaden canales externos por el rol. Las plantillas con variables ausentes,
expresiones sin resolver, cuerpo vacío o uso ambiguo de `amount_cents` quedan
bloqueadas para revisión; el comprobante interno sigue disponible. Los datos
monetarios mantienen su denominación y precisión originales.

## Vigencia específica de cada evento

La asignación revalida orden, entrega, repartidor, cuenta y estado operativo.
Comprueba además el último evento de asignación auditado: una asignación vieja
no vuelve a ser válida porque el pedido regresó al mismo repartidor.

El retiro revalida su dueño, rol de repartidor, estado, importe exacto y moneda.
Una solicitud pendiente no se anuncia como vigente después de aprobarse o
rechazarse. Un aviso de aprobación contable no confirma una transferencia,
no modifica la solicitud y no crea movimientos financieros.

## Revisión y conservación

El panel de `/notifications` se denomina «Revisión de avisos externos» y muestra
asignaciones, cierres y retiros. Los retiros se identifican por su propia
solicitud. Se conservan el modal central, los mensajes informativos, el destino
enmascarado y las fechas en Caracas.

Las rutas `/notifications/terminal-dispatch/...` mantienen su nombre por
compatibilidad; ahora administran los siete eventos. Gerente/Superadmin pueden
registrar aceptación verificada o ausencia de confirmación. La acción no
reenvía, no acredita pagos y se audita con clave de revisión e intento. Los
nuevos eventos usan `external_notification_review`; los cierres conservan
`terminal_notification_review` y sus revisiones anteriores.

Los siete eventos requieren sus escritores transaccionales: no pueden emitirse
por `send` genérico o `test-send`. Sus registros externos tampoco pueden borrarse
o marcarse leídos desde la bandeja personal. Los recibos internos mantienen esas
acciones. Las pruebas del dispatcher genérico usan una plantilla genérica para
seguir verificando deduplicación, límites y errores sin eludir este requisito.

Un aviso histórico sin marcador versionado no demuestra ausencia de un envío
previo. Al consumirlo se conserva como revisión técnica sin inventar UUID de
intento ni reenviarlo. Los bloqueos técnicos externos y resultados inciertos se
conservan frente a la limpieza periódica. No se modifica ni reconstruye en masa
el historial. La resolución técnica o un eventual nuevo envío requieren un
procedimiento independiente; no se ofrece un botón para forzar el reenvío.

## Verificación y límites

Las pruebas PostgreSQL cubren los cuatro eventos por tres canales, dos workers,
respuesta perdida, fallos de commit antes/después del intento, revisión
idempotente, retención, rollback, cambios monetarios, asignación posterior y
protección de las rutas. Las regresiones comprueban cierres y contratos de API.
El frontend comprueba referencias de retiro, permisos y la misma clave al repetir
una revisión incierta. Los proveedores se simulan; no se envían mensajes reales.

CI conserva todas sus comprobaciones y comandos. El laboratorio dispone de 45
minutos para incluir instalación, recorridos y restauración; las instalaciones
de navegador tienen un límite de diez minutos para detectar una preparación
atascada. El trabajo del contenedor web dispone de treinta minutos. Este ajuste
responde a una ejecución que agotó su margen de treinta minutos después de
consumir ocho preparando el navegador; no convierte un timeout en éxito.

No hay migración de esquema, backfill ni modificación de saldos o importes.
La aceptación del adaptador no garantiza entrega al dispositivo. PUSH puede
abarcar varios dispositivos y los SDK pueden realizar operaciones de transporte.
El protocolo limita invocaciones de la aplicación; no promete exactamente una
entrega externa. Otros eventos genéricos conservan su política anterior.

Pendientes externos: proveedores y destinos reales, consulta de resultados,
homologación en Venezuela, aceptación del negocio y preparación de infraestructura.
Base: `63b87c1` (entrega 124). La integración exige verificación del código y CI
completo del commit candidato. No se despliega la aplicación en esta entrega.

# Avisos duraderos de retiros, asignaciones y cierres

La entrega 124 añade el canal externo base de una plantilla activa para los tres
cierres, respetando preferencias y la transacción de negocio. Antes de contactar
al proveedor conserva un marcador de intento: una aceptación que no pueda
confirmarse queda retenida sin reenvío automático. El panel de revisión en
`/notifications` permite a Gerente/Superadmin confirmar aceptación con referencia
o documentar que el resultado sigue incierto, con auditoría e idempotencia. No
expone tokens ni afirma lectura o pago. Los pendientes inciertos no se purgan ni
se eliminan/marcan leídos desde la bandeja personal. Ver ENTREGA_124.md para
alcance, límite de una invocación de aplicación y pruebas con proveedores simulados.
Los otros eventos conservan sus reintentos anteriores; su ambigüedad y la consulta
automática por proveedor continúan pendientes.

La entrega 123 incorpora `entrega_fallida` y `orden_cancelada` para la cuenta del
repartidor, junto con la operación de negocio. Los dos puntos de fallo y las dos
entradas de cancelación reutilizan el transporte privado posterior al commit.
Las observaciones quedan en el detalle autorizado; no se difunden ni se inventan
importes. Sin asignación no se inventa un destinatario, y los reintentos históricos
no reconstruyen avisos anteriores. El modal de gerencia exige motivo y usa la
entrega con sus controles; el cambio genérico incompleto a FALLIDO devuelve 409.
Ver ENTREGA_123.md para invariantes, reintentos y validación.

La entrega 122 incorpora el cierre operativo de entregas asignadas: el evento
`entrega_completada` queda en la bandeja del repartidor junto con la transacción
de cierre, aun cuando el bono sea cero. Repetir la operación no duplica el aviso
ni reinicia su lectura. El comprobante no contiene OTP ni importes inferidos.
Se publica la señal privada después del commit exterior y se conserva la lectura
REST ante un fallo de esa señal. La entrega 124 amplía los canales externos de estos cierres. Ver ENTREGA_122.md.

La entrega 119 incorpora las asignaciones: el aviso IN_APP y la cola externa
permitida se guardan junto con orden, entrega y auditoría. Cada asignación real
tiene un identificador de evento propio; repetirla sin cambios no crea otro
aviso. Se reutiliza el consumidor descrito aquí. Antes de un intento externo se
comprueban destinatario y asignación vigente, además de las políticas generales.
La entrega 120 añade la señal WebSocket privada después del commit exterior de
la asignación. Los savepoints siguen siendo provisionales y un rollback no
anuncia el evento. El publicador usa su propia sesión y cliente Redis; un fallo
de esa señal conserva la recuperación REST al abrir la campana. Ver
ENTREGA_119.md y ENTREGA_120.md para alcance y pruebas.

La entrega 121 añade una lectura de reconciliación aproximadamente cada cinco
minutos con WebSocket conectado para recuperar señales perdidas. Mantiene la
consulta alternativa más frecuente cuando falla el tiempo real, sin duplicarla.
Las respuestas siguen ligadas a la identidad y token vigentes; el temporizador
se retira al cambiar de sesión o desmontar el componente. Ver ENTREGA_121.md.

Las solicitudes y decisiones nuevas guardan sus comprobantes IN_APP en notification_logs, en la transacción del retiro. La solicitud conserva además su aviso legacy por compatibilidad. La campana lee la bandeja actual; no combina dos comprobantes del mismo origen. No se convierten avisos anteriores ni se reenvía automáticamente el historial.

Con notificaciones externas habilitadas, el evento captura los canales permitidos y el texto de una plantilla activa. No hay envío dentro del commit financiero. El consumidor procesa filas PENDIENTE vencidas con bloqueo por fila y SKIP LOCKED. Se vuelven a comprobar cuenta, plantilla, preferencias y pausa operativa antes de contactar al proveedor. Sin consumidor activo, los registros permanecen pendientes; la retención no los elimina.

## Activar el consumidor

El TrackingScheduler existente ya incluye un ciclo de reintentos cuando está habilitado. Como alternativa, Celery permite programar exclusivamente el consumidor persistido. Desde backend, con la configuración de laboratorio o entorno correspondiente:

```bash
celery -A app.workers.celery_app:celery_app worker --loglevel=INFO
celery -A app.workers.celery_app:celery_app beat --loglevel=INFO
```

Son procesos separados; ejecutar una instancia de Beat para esa programación. La configuración requiere CELERY_BEAT_ENABLED=true y WORKER_NOTIFICATION_RETRY_ENABLED=true. NOTIFICATION_RETRY_SCAN_INTERVAL_SEC tiene valor60 y rango1..3600. Reiniciar los procesos después de cambiar la configuración. Si ambos planificadores consumen la cola, SKIP LOCKED coordina el procesamiento normal, aunque se añade trabajo de escaneo.

NOTIFICATIONS_ENABLED=false mantiene los comprobantes internos y evita crear nuevos canales externos. Un registro externo previamente pendiente se difiere mientras la configuración lo mantiene pausado, sin inventar éxito. Habilitar proveedores y homologar sus credenciales es un trabajo operativo separado; las pruebas usan adaptadores controlados y no realizan envíos a personas.

## Lectura y recuperación

La bandeja y su contador se consultan con GET /api/v1/notifications/inbox y /unread-count, con la sesión del destinatario. Abrir la campana reconcilia los datos aunque falle el aviso WebSocket. Los reintentos no cambian importes, reservas ni estados contables del retiro.

El identificador de deduplicación corresponde al retiro, evento y canal. Repetir una solicitud con su misma clave no duplica el comprobante; repetir una decisión ya aceptada conserva el rechazo de estado previo de la API. Los cambios de plantilla posteriores no recalculan el texto capturado.

Una plantilla con amount_cents en su cuerpo o asunto queda registrada como FALLIDO para revisión, con texto financiero seguro y sin envío. No se sobrescribe la plantilla personalizada ni se asume que sus centavos son dólares. El aviso interno permanece disponible. Revisar esa configuración antes de esperar entrega externa de esos registros; esta entrega no añade una acción de reenvío administrativo.

ENVIADO de un canal externo acredita aceptación del adaptador/proveedor según su contrato, no entrega al dispositivo ni pago bancario. Una caída después de aceptación externa y antes de confirmar el resultado puede producir reintento ambiguo: no se garantiza exactamente una entrega externa. La eliminación por retención sigue aplicando a registros terminales sin reintento pendiente; el historial contable del retiro se conserva por sus propios contratos.

## Entrega 125 — asignaciones y retiros

Los cuatro eventos transaccionales de asignación/retiro comparten el protocolo
persistente de los cierres. Antes del adaptador se confirma el intento; ante
resultado incierto no hay reenvío automático. Se usa el canal de la plantilla
filtrado por preferencias. La asignación comprueba su último evento auditado;
el retiro conserva y revalida dueño, estado, moneda e importe. La revisión
administrativa registra evidencia del proveedor y no confirma pagos.

Los avisos antiguos sin protocolo se retienen como revisión técnica cuando el
consumidor los encuentra. Los bloqueos técnicos externos no se purgan por edad.
No hay backfill, reset automático ni emisión por test-send/send genérico para
estos eventos. Los recibos internos conservan su contrato. Ver ENTREGA_125.md.

## Entrega 126 — cierre técnico sin reenvío

Gerente/Superadmin pueden documentar el cierre administrativo de un bloqueo
mediante referencia, revisión del registro y UUID de resolución. La transacción
conserva el aviso y guarda un acta; no reenvía ni acredita aceptación o pago.
Los resultados inciertos válidos mantienen su revisión de proveedor. La vista
«Cierres técnicos» permite consultar el comprobante con hora de Caracas.

El worker respeta el cierre aunque otra tarea volviera a encolar el aviso.
La retención genérica de auditoría conserva el acta mientras exista el registro
relacionado. No se reescriben payloads históricos. Ver ENTREGA_126.md.

# Avisos duraderos de retiros

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

# Delivery360 — entrega 116

La solicitud de retiro ya conservaba un aviso legacy, pero la campana consulta notification_logs. Esta entrega agrega el comprobante visible y conserva la fila legacy de compatibilidad en la misma transacción. Aprobación y rechazo también persisten su aviso y los canales externos pendientes junto con decisión, historial y asiento correspondiente. No se cambia el cálculo de saldos ni se confirma una transferencia bancaria.

Los identificadores por retiro/evento/canal son estables, sin ventana de cinco minutos. El texto y contexto monetario se capturan al aceptar el evento. Las preferencias, cuenta activa y plantilla condicionan los canales externos; la campana conserva el comprobante interno. Plantillas antiguas que interpolan amount_cents requieren revisión: se registra un fallo explícito sin enviarlas ni sobrescribir la plantilla.

El productor no realiza envíos externos ni confirma transacciones. El consumidor existente usa bloqueo PostgreSQL SKIP LOCKED, reintentos y revisión de políticas. Se comprueba recuperación después de cancelar un proveedor y concurrencia entre consumidores. La retención ya no borra eventos PENDIENTE ni filas con próximo reintento. No se promete entrega externa exactamente una vez: una caída tras aceptación del proveedor y antes del commit puede exigir conciliación.

Un aviso WebSocket posterior al commit acelera la actualización, pero no es la fuente durable. Abrir la campana vuelve a consultar la bandeja; se mejora su etiqueta accesible y el ancho móvil. La aceptación real comprueba un recibo en la campana móvil y avisos únicos de rechazo/aprobación, con USD exactos y lenguaje contable correcto.

Se añade programación explícita del consumidor Celery mediante CELERY_BEAT_ENABLED y WORKER_NOTIFICATION_RETRY_ENABLED; NOTIFICATION_RETRY_SCAN_INTERVAL_SEC admite1..3600 segundos. No se habilitan automáticamente workers ni proveedores. Ver NOTIFICACIONES_DURABLES.md.

No hay nueva migración en116; se requiere la base actual con la migración aditiva de115. No se modifica el respaldo original ni se ejecuta migración/despliegue productivo. Siguen pendientes los otros eventos de negocio, conciliación de resultados externos ambiguos, portales/recorridos restantes y objetivos medibles de operación/recuperación/capacidad.

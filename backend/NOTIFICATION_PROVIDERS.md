# Operación de proveedores PUSH/SMS

PUSH y SMS requieren aceptación real del proveedor para marcar su log ENVIADO.
Un SDK ausente, datos incompletos, falta de dispositivo o fallo del proveedor
producen reintentos con el presupuesto existente y finalmente FALLIDO.
IN_APP conserva su persistencia independiente; no se crea una entrega interna
adicional para sustituir implícitamente un canal externo que haya fallado.

El endpoint administrativo test-send conserva sent como entero, pero ahora cuenta
solo ENVIADO/ENTREGADO/LEIDO. Añade created, queued y failed para distinguir la
creación de registros de su aceptación o fallo; un mensaje pendiente no aumenta sent.

## Instalación y configuración

Desde backend, instalar conjuntamente el runtime base y las dependencias opcionales:

```sh
python -m pip install -r requirements.txt -r requirements-notifications.txt
```

Los ejemplos de entorno dejan vacíos SECRET_KEY, credenciales y URL de base de
datos. Deben completarse fuera del repositorio con valores propios del entorno;
no reutilizar credenciales de ejemplo ni subir los archivos reales de configuración.

El archivo opcional fija firebase-admin 6.8.0 y Twilio 9.12.0. Firebase 6.8
ofrece send_each_for_multicast, que usa FCM HTTP v1. Las versiones recientes
de Firebase requieren HTTPX 0.28.1, mientras el runtime actual fija 0.27.0;
actualizar ambas dependencias será un trabajo separado con sus regresiones.
La resolución conjunta de los archivos se ha verificado con pip --dry-run.

| Variable | Uso |
|---|---|
| NOTIFICATIONS_ENABLED | false fuerza IN_APP en nuevos eventos y aplaza reintentos externos; configurar coherentemente en todos los workers |
| FCM_CREDENTIALS_JSON_PATH | Ruta accesible al JSON de cuenta de servicio, suministrado fuera del repositorio |
| FCM_PROJECT_ID | Proyecto opcional explícito; si falta, el SDK usa el proyecto de la credencial |
| TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN | Credenciales del cliente SMS |
| TWILIO_FROM_NUMBER | Número emisor habilitado en Twilio, en formato internacional + y dígitos |
| NOTIFICATION_PROVIDER_TIMEOUT_SECONDS | Timeout HTTP por solicitud del SDK, de 1 a 60 segundos; default 10 |
| NOTIFICATION_PROVIDER_CONCURRENCY | Operaciones SDK activas por bucle/proceso, de 1 a 16; default 4 |

Los números SMS deben usar +, prefijo internacional y entre 7 y 15 dígitos,
sin espacios ni formato nacional. El cuerpo mantiene el límite previo de
1600 caracteres. La credencial Firebase se inicializa de forma diferida en
una aplicación nombrada por configuración, sin usar ni sobrescribir el app
por defecto. Las credenciales, proyectos y límites se configuran por proceso;
rotaciones sobre el mismo archivo requieren reiniciar los procesos para
cargar el material nuevo. Este cambio no implementa recarga de secretos.

## Ejecución y resultado

Los SDK síncronos se ejecutan en hilos. Ningún hilo recibe una AsyncSession:
la persistencia continúa en el bucle y transacción del propietario. El límite
de concurrencia se comparte entre PUSH y SMS en el proceso; no es una cuota
distribuida del proveedor. Firebase se divide en lotes de 50 tokens, por debajo
de su máximo de 500 y para acotar también el fan-out de hilos de ese SDK.
Los tokens repetidos se envían una sola vez por esta llamada.

Una cancelación normal antes de obtener una plaza no inicia un SDK. Si el SDK
ya comenzó, se espera a que termine antes de propagar la cancelación y liberar
la plaza/transacción. Esto evita abandonar un hilo mientras otro trabajador
reclama inmediatamente el mismo log. El timeout HTTP es por solicitud: los
reintentos internos del SDK, autenticación y múltiples lotes pueden hacer que
la operación completa dure más. No se promete una duración total de 60 segundos.
Una pérdida de conexión SQL, caída del proceso o aceptación externa seguida
de rollback todavía puede duplicar mensajes: siguen pendientes idempotencia
por proveedor, outbox y conciliación.

ENVIADO significa aceptación: al menos un dispositivo en PUSH o una respuesta
SMS con SID y sin estado failed/undelivered/canceled. No significa recepción
por todos los dispositivos ni lectura. Una respuesta parcial no conserva aún
un ledger individual de cada dispositivo ni reintenta solo los no aceptados.
Los fallos de red/cuota y los lotes con respuesta malformada no invalidan todos
los dispositivos ni borran aceptaciones ya obtenidas en otros lotes.

Solo UnregisteredError de FCM alimenta ahora el contador de token inválido.
El umbral anterior de tres observaciones permanece; un fallo temporal no lo
incrementa. El helper conserva el bloqueo ordenado por token y hace flush:
el propietario confirma junto con el resultado del log. No se reinicia el
contador tras cada éxito ni se versiona todavía una transferencia/reactivación
del token. Los resultados tardíos de esas situaciones siguen pendientes.

Twilio usa timeout HTTP explícito y max_retries=0 en su transporte; la cola
controla los reintentos del sistema. La sesión HTTP se cierra al terminar,
incluso tras errores. Un error de limpieza no elimina una aceptación ya recibida.
Los errores de proveedor guardados y los avisos son genéricos; no incluyen
teléfono, token, credenciales, cuerpo ni diagnóstico privado del SDK.

## Verificación

Con el entorno de pruebas de backend configurado:

```sh
python -m pytest tests/test_notification_providers.py -q
python -m pytest tests/test_notification_sdk_contracts.py -q
```

Los contratos usan los SDK instalados y sustituyen sus transportes HTTP;
no envían mensajes externos ni necesitan una cuenta de proveedor real.
Si no se instalan los SDK opcionales, esos dos contratos se omiten y la
aplicación sigue arrancando: los canales externos no disponibles fallan de
forma controlada. Las pruebas de persistencia requieren TEST_DATABASE_URL
apuntando explícitamente a una base PostgreSQL test_* desechable.

Antes de una activación operativa real quedan por verificar las credenciales,
permisos del proyecto Firebase, número Twilio habilitado y su cobertura de
destinos, con mensajes de prueba autorizados fuera de esta entrega. No se
ejecuta aquí ningún despliegue ni prueba contra destinatarios reales.

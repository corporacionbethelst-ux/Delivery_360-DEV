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

Solo UnregisteredError de FCM alimenta el contador de token inválido.
El umbral de tres observaciones permanece; un fallo temporal no lo incrementa.
Una aceptación individual confirmada reinicia a cero el contador del dispositivo,
si todavía está activo y coincide con la revisión que tenía al comenzar el envío.
Una aceptación agregada sin dispositivos identificados no permite adivinar qué
contador reiniciar. Los resultados de una revisión antigua se ignoran.

## Ciclo de vida del dispositivo

POST /api/v1/notifications/register-device conserva el cuerpo device_token y
platform y la respuesta status/action (created o updated). La creación utiliza
INSERT ON CONFLICT DO NOTHING y la actualización bloquea/refresca la fila;
registros concurrentes del mismo token no crean duplicados ni abortan por una
violación UNIQUE. La cuenta se toma de la identidad autenticada, no del cuerpo.
Un mismo propietario activo conserva su contador; una transferencia o una
reactivación lo reinicia como antes.

DELETE /api/v1/notifications/unregister-device recibe el JSON device_token y
desactiva únicamente el token de la cuenta autenticada. Devuelve status=ok tanto
para baja efectiva como para inexistencia, otra cuenta o una baja ya realizada.
No elimina la fila, no borra otros dispositivos y no reactiva nada. Requiere
JWT válido y cuenta activa con rol vigente. Ambas rutas rechazan tokens de
longitud inválida, espacios y caracteres de control antes de almacenarlos.

La revisión usa id de fila, propietario y last_seen_at existentes. Registro,
refresco y baja efectiva avanzan last_seen_at de forma estrictamente creciente,
incluso ante un reloj que retroceda, con reloj UTC de PostgreSQL y un incremento
mínimo de un microsegundo. No se añade una columna ni se migra información.
El proveedor recibe strings, mientras el servicio conserva una copia inmutable
de la revisión observada. Al terminar, bloquea/refresca cada token y aplica
fallos o reinicios solo a la revisión activa que todavía coincide. Conserva
flush y el commit/rollback del propietario del despacho.

La garantía requiere todos los escritores de dispositivos actualizados sobre
PostgreSQL. SQLite sirve para pruebas secuenciales del contrato HTTP. Los
registros concurrentes de propietarios distintos conservan el comportamiento
anterior: quien posee el token puede registrarlo y el último cambio confirmado
define la cuenta asociada. No se implementa atestación de instalación ni prueba
criptográfica adicional de posesión del dispositivo.

La baja es local al sistema: no llama a Firebase para invalidar físicamente el
token. El frontend web actual solo retira los identificadores ficticios web-*
que generaba el prototipo, con el bearer capturado antes del logout o después
de verificar el perfil al iniciar/revalidar sesión. Un token real de Firebase
requiere que el cliente invoque esta ruta e implemente su rotación/eliminación
con el SDK cuando corresponda. No hay integración FCM web real en este lote. Un mensaje que ya esté en vuelo o aceptado externamente
no puede retirarse: la revisión protege los cambios de estado del dispositivo,
no garantiza que el proveedor no entregue un mensaje anterior tras un cambio
de cuenta. La revocación de JWT y el cierre de otras sesiones son independientes.

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

## Cliente web y aislamiento de sesión

Un UUID de navegador no es un token FCM. Se elimina la generación/registro
automático de web-* en el login; no se anuncia PUSH web funcional sin SDK,
permiso de notificaciones y service worker. El inbox IN_APP con WebSocket
y polling sigue disponible. El wrapper de contexto simulado, sin consumidores
en el dashboard, deja de montarse: no ejecuta su temporizador de órdenes ficticias.
El módulo antiguo permanece sin uso; no se presenta como transporte real.

La retirada de marcadores heredados usa DELETE autenticado, keepalive y aborto
a los 1500 ms. Solo procesa las dos claves del prototipo y cadenas web-*
compatibles con su formato; no toca otros tokens ni preferencias del navegador.
Se deduplican peticiones en vuelo para el mismo bearer/token y se conserva el
marcador ante fallos para otro intento. Un resultado tardío solo borra la clave
si todavía contiene el valor enviado. El backend decide la propiedad: una cuenta
B no puede retirar la fila de A. Por ello cambiar de cuenta sin completar la
baja anterior puede dejar una fila ficticia antigua, que requiere saneamiento
operativo posterior; no se ejecuta un borrado global ni una migración.

Las alertas /alerts se conservan solo en memoria para una sesión verificada.
Se descarta la antigua caché delivery360-notifications-v1 sin leer ni restaurar
su contenido. Login, revalidación y logout invalidan respuestas anteriores.
El hook omnicanal vincula REST, PATCH y callbacks WS al usuario y revisión de
sesión; aborta sus peticiones al desmontar, deshabilitar o cambiar de sesión,
y cierra el socket con sus temporizadores. Solo usa access_token del cliente
central, sin rescatar el antiguo token de localStorage. El render oculta datos
de otra revisión antes incluso de la limpieza del efecto.

Una respuesta vieja no reemplaza la más reciente. Los eventos en vivo invalidan
el snapshot pendiente y agrupan una lectura canónica de SQL en una ventana de
50 ms; el ACK de marcar leído también solicita conciliación. Los payloads sin
id o ajenos a IN_APP se ignoran; no se inventan identificadores. Los errores de
red del hook son genéricos. GET y PATCH tienen esperas acotadas a 15 segundos y
se cancelan al limpiar su contexto, incluso si el adaptador ignora AbortSignal.

Tras rotar correctamente el bearer, la señal central reemplaza inmediatamente
el socket y su contexto REST; conserva los items del mismo usuario/generación.
No espera al siguiente polling para adoptar el token nuevo. Los callbacks del
socket retirado y las acciones públicas guardadas de otra sesión no pueden
escribir ni enviar como la sesión actual. La apertura se limita a 10 segundos.

Los cierres 1008/4001 limpian items y contador, invalidan/cancelan GET y resultados
PATCH pendientes y retiran el temporizador de conciliación. No hay reconexión
WS automática con ese contexto; REST permanece como alternativa y puede
recuperar datos posteriormente si el servidor lo autoriza. El cierre de socket
no equivale a revocación global de JWT. Cancelar una espera PATCH no deshace una
lectura ya marcada por el servidor. Estos cambios son de cliente; no se altera
la lógica de proveedores ni de autorización del backend.

El POST de logout usa el bearer capturado antes de limpiar credenciales, sin
entrar al interceptor de refresh ni reintentar contra una cuenta nueva. El
logout local es inmediato; la petición es best effort y se aborta a los 1500 ms.
El endpoint del servidor sigue siendo una confirmación sin revocación de JWT.
No se garantiza la baja al cerrar la pestaña sin logout, con red ausente ni
entre todas las pestañas: sincronización global y revocación siguen pendientes.

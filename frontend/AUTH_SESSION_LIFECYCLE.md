# Ciclo de sesión del cliente HTTP

El cliente central `src/lib/api.ts` mantiene el contrato de los wrappers
`api.get/post/put/patch/delete` y de la instancia Axios por defecto. Los wrappers
siguen devolviendo `response.data`; la instancia sigue devolviendo respuestas
Axios. La autorización real continúa en el backend.

## Propiedad de las credenciales

`src/lib/auth-session.ts` conserva en memoria el par de credenciales y una
generación local. Login explícito, limpieza de credenciales y cambios observados
en las dos claves de almacenamiento invalidan la generación anterior. Guardar
otra vez exactamente los mismos valores también la invalida: un logout/login
no permite recuperar peticiones anteriores aunque los strings coincidan.

Un refresh válido rota los tokens dentro de la misma generación. Para persistir
exige que generación y par original sigan coincidiendo. El contador no se
persiste, no es una revisión de BD y no valida firmas ni permisos por sí mismo.
Los lectores reciben copias, no un objeto mutable compartido. En SSR no se
almacenan ni devuelven credenciales de navegador en una variable de proceso.

La interfaz de `api.ts` sigue reexportando getStoredTokens, storeTokens y
clearStoredTokens, de modo que los consumidores actuales conservan sus imports.

## Petición y renovación

1. El interceptor síncrono captura la generación al despachar la petición,
   antes de ceder al siguiente trabajo asíncrono. Se exige el origen y prefijo
   de la API configurada; no se reenvían credenciales a URLs externas ni a
   rutas que escapen de ese prefijo.
2. Las rutas públicas de login, registro, recuperación, reset y refresh no
   llevan Authorization, incluso si el caller la proporcionó. Un 401 de estas
   rutas no entra en renovación automática.
3. Un 401 privado puede renovar una vez. Los callers de la misma generación
   comparten una promesa y una petición de refresh. Cada petición conserva su
   límite de un reenvío; las que esperaban no recuperan un presupuesto nuevo.
4. El transporte de renovación usa timeout de 15 segundos y AbortController.
   Una carrera adicional termina la espera al vencer el plazo aunque un
   adaptador no respete el timeout. Un logout/login cancela inmediatamente la
   espera compartida y aborta el transporte. Un caller cancelado deja de esperar
   sin cancelar la renovación que aún necesitan los demás.
5. Un refresh solo acepta ambos tokens no vacíos, ASCII imprimibles sin espacios
   y de hasta 16384 caracteres. No interpreta los claims como autorización.
6. El resultado y cada reenvío comprueban la generación. Una respuesta antigua
   tampoco puede entregar un payload exitoso a un consumidor de otra sesión.
   La limpieza de una promesa antigua no elimina la renovación de una sesión
   nueva.

Un 401 tardío del token anterior, después de una rotación válida en esta sesión,
reutiliza el token actual sin abrir otro refresh. Si una petición ya reenviada
falla después de otra rotación, se rechaza sin borrar ese par más reciente.
Una petición ya enviada puede haber producido efectos en el servidor: descartar
su respuesta o abortar la espera no equivale a revertirla.

La metadata añadida a una petición privada contiene la generación y el bearer
usado, que ya es necesario en Authorization. No contiene refresh_token. El token
de renovación solo se pasa al transporte específico que lo necesita; sus
fallos se convierten en errores genéricos, sin imprimir config, cuerpos ni URLs.

## Errores y estado visible

| Situación | Credenciales y resultado |
|---|---|
| Logout o nuevo login durante refresh | Esperas antiguas rechazadas; resultados tardíos ignorados |
| Refresh 401/403 o bearer rechazado tras su único reenvío | Limpieza solo de la generación vigente y evento local de expiración |
| Sin refresh para un bearer rechazado | Expiración local, sin petición de renovación |
| Error de red, timeout, 429, 5xx o respuesta mal formada | Error genérico; se conserva el par para un intento posterior |
| Petición privada anónima rechazada | Se devuelve el fallo, sin ciclo de refresh ni navegación global |
| URL fuera de la API configurada | Se rechaza antes del adaptador HTTP |
| Otro par observado en localStorage | Se invalida la generación anterior; no se atribuye al mismo usuario |

SessionGate escucha la expiración y llama a forceLogout para retirar el contenido
protegido y limpiar el ámbito de notificaciones. El propio cliente HTTP no
navega ni interpreta roles. Una revalidación que no logra renovar por un fallo
temporal conserva credenciales, pero deja usuario/isAuthenticated sin verificar:
no habilita contenido privado sin perfil vigente.

Login invalida las credenciales anteriores antes de esperar la red. El perfil
se acepta solo si siguen vigentes tanto la revisión de authStore como la
generación de credenciales. La cookie de navegación usa el token vigente al
terminar, incluida una rotación ocurrida durante la lectura del perfil. Durante
refresh se actualiza una cookie auth-token ya existente; no se inventa una sesión
verificada desde una cookie ausente. La compatibilidad de `/auth/me` con
`/users/me` se activa solo por 404, sin rescatar fallos de autenticación, cambios
de sesión o errores de servidor mediante otra petición.

## Almacenamiento y limpieza

La memoria se limpia antes de intentar borrar localStorage. Se intentan eliminar
las claves de credenciales y perfil y las cookies de navegación aunque falle
otra eliminación. Si el navegador impide borrar datos, esta página deja de
leer esos restos hasta una escritura explícita completa posterior. No se
promete eliminar físicamente datos cuando el navegador lo prohíbe ni mantener
esa memoria de seguridad tras recargar la página.

Una escritura parcial falla sin conceder autenticación, intenta retirar los
restos, invalida esperas y notifica el cierre local. No conserva un access nuevo
con el refresh viejo. La persistencia vacía opcional de Zustand tolera denegación
de almacenamiento; no contiene perfiles ni tokens. No se eliminan preferencias
ajenas como el tema.

## Verificación y límites

Las suites `api-session-refresh`, `api-origin`, `auth-session`, `auth-session-ssr`
y `authSession.integration` ejercitan el código real de Axios y sus interceptores
con adaptadores de transporte sustituidos. La integración usa authService,
authStore, SessionGate, cookies y almacenamiento de JSDOM. No autentica contra
un backend desplegado ni comprueba criptográficamente JWT reales.

El alcance de cliente de las entregas 45–47 no incluía revocación del servidor.
La entrega 48 incorpora la versión de credenciales descrita al final de esta
guía. No incorpora sesiones por dispositivo, cookies HttpOnly, protección contra
XSS ni coordinación atómica entre pestañas.
Los cambios de storage se detectan al leer; no hay una garantía global frente a
cambios no observados o ABA externos entre lecturas. Nuevas pestañas/procesos
requieren su propia verificación. Los consumidores que usen fetch por su cuenta
no heredan estos interceptores y mantienen sus controles propios. La protección adicional de stores y caché se detalla a continuación; los
consumidores fuera de ese alcance conservan sus obligaciones de ciclo de vida.

El helper heredado authApi.registerRider continúa sin consumidores y conserva
su ruta histórica `/auth/register`; no se declara funcional contra el backend
actual. El registro activo usa authService.register y `/auth/register-rider` con
validación documental. La cobertura de compatibilidad comprueba que el helper
no borra una sesión por una respuesta sin tokens ni persiste una respuesta
obsoleta; alinear o retirar esa interfaz antigua queda como limpieza posterior.


## Datos de negocio y caché privada

La generación también se aplica a los stores globales de pedidos, entregas,
repartidores, datos personales del repartidor, finanzas, tiempo real y alertas.
Al cambiar credenciales, volver a guardar el mismo par o hacer logout se
restablecen los datos, selección, filtros y flags de carga del estado inicial.
Se mantienen las funciones de sus acciones. En alertas se avanza además la
revisión de peticiones que ya protegía las respuestas REST. No es necesario
que el cambio haya pasado por authStore para limpiar esos datos.

En los cinco stores que hacen HTTP se protegen 33 acciones y 36 continuaciones
de await. capturePrivateTask exige credenciales al comenzar y cada continuación
comprueba que todavía pertenece a esa generación antes de actualizar, devolver
datos o continuar con otra consulta. El catch comprueba lo mismo antes de
publicar errores/fallbacks. La comprobación pertenece al frame del store: cubre
el intervalo entre la aceptación del interceptor y la reanudación del caller.
Un error antiguo no puede quitar los flags de una operación de la cuenta nueva.

Una renovación normal conserva la generación: no vacía los stores ni la caché
del mismo usuario. El fallo de un suscriptor de invalidación se aísla para que
no detenga la limpieza de los demás ni la invalidación de credenciales.

### Caché de consultas

private-cache.ts conserva solo memoria de la página, con TTL en segundos y un
máximo de 500 entradas, expulsando la menos recientemente utilizada. No hay
serialización, restauración, timer periódico ni beforeunload de datos privados.
La clave heredada delivery360_cache se intenta retirar sin leer ni interpretar
su contenido; los nombres persist/restore se mantienen como limpieza compatible.
Si el navegador prohíbe borrarla, el cliente nuevo no la restaura; no se promete
su eliminación física ni proteger clientes antiguos que sigan ejecutándose.

Cada entrada tiene una generación; la lectura no devuelve datos sin credenciales
y el cambio de generación vacía el mapa. Los escritores asíncronos conocidos
proporcionan la generación esperada al guardar para no atribuir un resultado
antiguo a otra cuenta. Los valores 0, false y string vacío se conservan como
hits válidos; ttl cero no conserva una entrada. TTL negativos o no finitos se
rechazan. La cota es de entradas, no un presupuesto de bytes por respuesta.

useCachedQuery usa una suscripción React al contador puro de generación y
distingue clave, sesión, secuencia y montaje. Oculta datos ajenos a la clave o
generación durante render, descarta trabajo tras disable/unmount/StrictMode
y aplica solo el último refetch. Un callback queryFn inline no dispara un bucle;
la clave debe representar los parámetros de la consulta y refetch usa su función
actual. Conserva TTL, staleTime y fallback del ámbito vigente con error genérico.
queryFn no recibe señal de aborto en esta interfaz: el trabajo puede terminar,
pero su resultado obsoleto no se aplica ni vuelve a entrar en la caché.

El servicio de pedidos con caché conserva sus exports y captura también la tarea
privada. Se corrigen el prefijo duplicado /api/v1 y PUT/POST donde el servicio
principal usa PATCH para edición, cancelación y asignación. Los IDs se codifican
como componentes de URL. No se activa ese helper en pantallas que no lo usaban,
ni se certifican con sus pruebas los campos/estados exigidos por el backend: la
verificación de métodos/rutas se compara con el servicio principal y transportes
sustituidos. El backend continúa validando permisos y datos de cada operación.

### Alcance de las garantías

No se implementan revocación JWT ni coordinación atómica entre pestañas. Se
reacciona a cambios de almacenamiento cuando el gestor los observa. Estos
stores no sustituyen al control de acceso ni verifican en cada hit de caché si
el servidor ha cambiado el rol de la cuenta. Una revalidación de perfil sin
cambio de generación no equivale a un logout global de los datos de negocio.

La limpieza del store de tiempo real no cierra por sí misma los sockets de sus
productores. Los callbacks síncronos externos deben conservar/verificar su
propio contexto; no se certifican todos los productores WS desde este reset.
No se ordenan todas las operaciones concurrentes de una misma sesión en los
stores de negocio; la secuencia de useCachedQuery tiene ese alcance solo en su
instancia. Una mutación aceptada por el servidor no se revierte al descartar
su resultado. No se cancela la petición remota desde capturePrivateTask.


## Transporte en tiempo real y mapa (entrega ampliada 47)

`useRealtimeIdentity` combina perfil activo verificado, usuario, revisión de
`authStore`, generación de credenciales y una revisión independiente del access
token. `commitRefreshedTokens` emite la señal de rotación después de persistir el
par válido. Los errores de un suscriptor no impiden notificar a los demás. Una
rotación propia conserva la generación y los datos de negocio del mismo usuario;
login, logout o un par externo observado mantienen la invalidación anterior.
La señal no lleva tokens ni sustituye la autorización del servidor.

Los hooks activos `useTrackingWebSocket` y `useNotifications` reemplazan el socket
al recibir esa señal. Cada callback verifica además la instancia concreta y el
token capturado. La limpieza retira handlers, intervalos, reintentos y conexiones
incluso si siguen en CONNECTING. Los datos de otro usuario/revisión/generación se
ocultan durante render. Los callbacks públicos guardados de una sesión anterior
no pueden refrescar, marcar lecturas ni reconectar como una cuenta nueva.

Tracking limita la apertura a 10 segundos por defecto, reintenta con espera
exponencial hasta 15 segundos y conserva un presupuesto acotado por configuración
(máximo diez reintentos). Solo el mensaje CONNECTED reinicia el presupuesto.
Una reconexión manual retira antes el socket y temporizador anteriores. Los
cierres 1008/4001 limpian posiciones y no abren otro socket automáticamente con
ese contexto; una acción manual explícita puede intentar de nuevo. Se mantienen
pings y medición de latencia, incluido performance.now() igual a cero.

Las URLs se derivan de la configuración existente; los valores históricos
true/false de NEXT_PUBLIC_TRACKING_WS se interpretan como flags. Se conservan
prefijos de API y se codifican canal/token. Se rechazan protocolos ajenos a
WS/WSS, userinfo, query/hash en la URL base y WS inseguro desde una página HTTPS.
Los canales son dashboard o rider/order con UUID canónico. No se registra la
URL autenticada. El protocolo del backend continúa pasando el JWT en query;
esta entrega no modifica la política de logs del proxy ni migra autenticación.

El inbox tiene dos grupos de solicitudes: lecturas reemplazables y mutaciones.
`RequestScope` limita a 15 segundos fetch y consumo JSON cuando ambos forman la
misma operación; aborta al limpiar y termina la espera aunque un adaptador
ignore AbortSignal. Una respuesta anterior no sustituye una lectura más nueva.
Los eventos se muestran inmediatamente y agrupan la recuperación canónica de SQL
en una ventana de 50 ms. El ACK de marcar leído también reconcilia el historial.
El cierre de política limpia items/contador, invalida GET y resultados PATCH
pendientes y cancela la recuperación programada. No reintenta automáticamente
ese WS, pero conserva REST: una consulta posterior puede recuperar el inbox
si el servidor todavía la autoriza. No se equipara ese cierre a revocación JWT.

El mapa publica un snapshot completo de repartidores y pedidos, con estadísticas
opcionales. La última consulta iniciada prevalece, sin publicar resultados al
desmontar o cambiar ámbito. Un fallo transitorio conserva el snapshot anterior;
401/403 de las consultas principales limpia datos y muestra el error de acceso.
Se reconocen tanto AxiosError como el error normalizado del servicio real de
repartidores. La página oculta también las posiciones WS retenidas tras ese
rechazo; un fallo transitorio posterior no las restaura. Solo un snapshot
completo autorizado permite mostrarlas de nuevo. Las estadísticas opcionales fallidas pasan a null. El polling
usa 10 segundos sin WS abierto y 60 segundos con WS abierto. La rotación propia
no borra el snapshot ni recrea por sí sola ese intervalo.

Coordenadas cero son válidas; null, texto vacío, NaN y rangos imposibles no se
convierten en ubicaciones. REST conserva nombre, teléfono y estado al incorporar
WS. Se compara la fecha de posición y se evita retroceder con un snapshot/evento
antiguo; un punto sin fecha no reemplaza uno fechado. El escritor de tracking
actual guarda UTC sin tzinfo: se normalizan esas fechas a Z antes de comparar o
mostrar; los offsets explícitos se conservan. No se inventa una fecha actual.
RECOLECTADO se considera pedido activo. El límite de 50 pedidos solicitado por
la pantalla se mantiene y no representa el total de todos los pedidos del sistema.

La memoria WS se limita a 1000 repartidores por defecto (configurable hasta
5000), frames de 262144 caracteres y lotes procesados de hasta el doble del límite.
No es un presupuesto de bytes de toda la aplicación. La demostración de
movimiento local existente sigue requiriendo activación explícita; no escribe
ubicaciones en el servidor y no constituye seguimiento real.

Las pruebas de cliente no certifican redes móviles, gateways ni navegadores
físicos. La revocación del servidor se verifica por separado en la entrega 48. La comparación de fechas usa precisión de milisegundos;
no sustituye una secuencia durable ni ordena todos los eventos simultáneos. La
apertura de un WS no certifica que Redis esté sano y no hay watchdog de pongs
perdidos en una conexión ya abierta. El mapa no aborta las consultas Axios ya
enviadas: descarta sus resultados obsoletos. Los PATCH enviados pueden haberse
aplicado aunque se cancele la espera del navegador.

Los helpers heredados `useRealtimeUpdates`/`WebSocketContext` y
`useSocket`/`NotificationContext` no se activan con esta entrega. El primero
conserva una ruta genérica /api/v1/ws sin endpoint montado y dependencias que
pueden recrear conexiones; el segundo conserva demostración histórica. No se
presentan como transportes productivos. La revocación por cuenta se incorpora
en la entrega 48; siguen pendientes coordinación entre pestañas, sesiones individuales y revalidación integral de
permisos/cachés.


## Revocación de servidor y logout global (entrega ampliada 48)

El servidor comprueba ahora el claim ver de access/refresh contra
users.token_version. Un logout confirmado incrementa condicionalmente esa versión
y retira todos los JWT anteriores de la cuenta; la UI lo expresa como
**Cerrar todas las sesiones**. Un logout antiguo no incrementa una versión nueva
tras una revocación previa. Contraseña y revocación se confirman juntas en reset
y en el cambio administrativo, y los cambios efectivos de rol/is_active también
invalidan credenciales. Los JWT históricos sin ver pertenecen solo a versión 0.

El navegador sigue limpiando datos inmediatamente. Su POST capturado conserva el
plazo de 1500 ms y no intenta renovar ni reenvía bajo otra cuenta. Sin confirmación
no garantiza revocación del servidor. Las otras pestañas descubren el rechazo en
su próxima actividad; no se añade comunicación atómica entre ellas. Los sockets
se cierran al detectar la revocación en una comprobación de entrada/envío, no por
un broadcast instantáneo nuevo. Los refresh de una misma versión conservan su
semántica de rotación anterior y aún no son de un solo uso.

Esta funcionalidad requiere migrar el esquema y retirar workers antiguos antes
de considerarla efectiva. Consulte [guía operativa de backend](../backend/AUTH_TOKEN_REVOCATION.md).
La persistencia local/cookie y la defensa contra XSS mantienen los límites
anteriores; tener revocación de servidor no los sustituye.


En el cierre de revisión de la entrega 48, el productor dashboard incorpora la
misma fecha recorded_at que el canal rider; la fusión puede así aceptar movimiento
real sin permitir que un evento sin fecha reemplace un snapshot fechado. El mapa
omite ticks automáticos si una consulta del mismo ámbito sigue pendiente; no
invalida indefinidamente respuestas que tardan más de diez segundos. El refresh
manual conserva prioridad y un finally antiguo no libera el slot de una petición
nueva. Un cambio de ámbito/conexión retira el slot anterior.

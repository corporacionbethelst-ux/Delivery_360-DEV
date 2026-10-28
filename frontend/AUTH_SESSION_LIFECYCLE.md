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

No se añade revocación de JWT en el servidor, una sesión persistida en BD,
cookies HttpOnly, protección contra XSS ni coordinación atómica entre pestañas.
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

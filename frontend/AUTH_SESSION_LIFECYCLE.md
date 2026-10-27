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
no heredan estos interceptores y mantienen sus controles propios. Tampoco se
resuelven con este lote las actualizaciones tardías de todos los stores de
negocio fuera del cliente HTTP.

El helper heredado authApi.registerRider continúa sin consumidores y conserva
su ruta histórica `/auth/register`; no se declara funcional contra el backend
actual. El registro activo usa authService.register y `/auth/register-rider` con
validación documental. La cobertura de compatibilidad comprueba que el helper
no borra una sesión por una respuesta sin tokens ni persiste una respuesta
obsoleta; alinear o retirar esa interfaz antigua queda como limpieza posterior.

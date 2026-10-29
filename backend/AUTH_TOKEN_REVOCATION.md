# Revocación de credenciales JWT por cuenta

Entrega ampliada 48. Los endpoints activos verifican una versión de credenciales
persistida. No es un inventario de sesiones por dispositivo.

## Contrato y diccionario

| Elemento | Tipo / valor | Función |
|---|---|---|
| users.token_version | BIGINT NOT NULL, default servidor/Python 0 | Versión vigente de todas las credenciales de la cuenta |
| ck_users_token_version_nonnegative | CHECK token_version >= 0 | Impide versiones negativas en SQL |
| JWT ver | Entero JSON entre 0 y 9223372036854775807 | Versión capturada al emitir access o refresh |
| JWT sin ver | Compatibilidad exclusiva con versión 0 | Un token histórico deja de servir tras la primera revocación |
| POST /api/v1/auth/logout | Bearer access válido y no expirado | Incrementa condicionalmente su versión y confirma scope=all_sessions |

No se guardan JWT, refresh tokens, hashes de JWT ni identificadores de sesión en
esta columna. No se expone la versión en los perfiles públicos. `jti` continúa
siendo aleatorio y distinto por token; tener un jti no implementa protección de
reutilización por sí solo.

`create_access_token` y `create_refresh_token` reciben `token_version` como
argumento keyword opcional para conservar sus llamadas existentes. Los productores
de login/refresh activos pasan expresamente el valor leído del usuario. Un helper
invocado sin versión produce tokens de versión cero y no puede autenticar una
cuenta ya revocada. No se debe usar ese default para nuevos productores de login.

Los emisores y decoder rechazan ver negativo, booleano, float, string, null,
colecciones o superior a BIGINT. Se valida firma, tipo y expiración según el
contrato anterior, más la versión. La ausencia histórica de ver no equivale a
aceptar null. La comparación no confía en que el navegador interprete los claims.

## Flujos cubiertos

1. Login valida contraseña y política vigente de la cuenta/repartidor. Emite ambos
   JWT con la versión de las credenciales verificadas. Un login que coincide con
   una revocación puede devolver tokens que el servidor ya no acepta; no se eleva
   su versión después de haber verificado una contraseña anterior.
2. Ambas dependencias activas de autenticación, la del router auth y la de
   core/security, contrastan ver con SQL. Sus SELECT actualizan los atributos de
   un User ya presente en el identity map de SQLAlchemy. No se acepta una versión
   antigua solo porque otro worker la haya cargado antes.
3. Refresh exige type=refresh y versión coincidente, además de cuenta/política
   vigentes. Emite jti nuevos conservando la versión de la cuenta. No incrementa
   la versión por cada renovación, para no invalidar todas las pestañas en cada
   refresh. La prevención de reutilización de cada refresh individual sigue
   pendiente de un ledger de sesiones.
4. Logout ejecuta UPDATE users SET token_version = token_version + 1 con WHERE
   id y versión presentada. Solo confirma éxito después de commit. No pide rol
   operativo ni estado habilitado: una cuenta deshabilitada puede retirar sus
   propias credenciales sin obtener acceso a operaciones. Un refresh token,
   token expirado, subject inválido, usuario inexistente o versión antigua recibe
   401. No es un endpoint anónimo de confirmación.
5. Dos logouts de la misma versión no incrementan dos veces. El ganador confirma
   y los demás reciben 401. Un logout capturado antes no incrementa una versión
   nueva ya emitida tras la revocación previa. Un login emitido antes del commit
   de logout pertenece a la versión que se está retirando y queda invalidado,
   aunque se haya iniciado después de pulsar el botón en otra pestaña.
6. El consumo válido de recuperación de contraseña incrementa la versión en el
   mismo UPDATE condicional que cambia el hash y consume el enlace. Un replay o
   consumo rechazado no incrementa. Un fallo de commit revierte contraseña,
   consumo y versión juntos. No se retiene un lock mientras se calcula bcrypt.
7. El cambio de contraseña desde administración y CRUDUser.update_password
   retiran también los enlaces de recuperación pendientes y revocan credenciales
   dentro de su transacción. Si no se puede incrementar, la operación falla; no
   confirma una contraseña nueva dejando JWT anteriores vigentes.
8. La administración de usuarios revoca cuando cambia realmente rol o is_active,
   incluida la reactivación, y en su soft delete. Una edición de nombre/teléfono
   o una asignación del mismo rol/estado no revoca. No cambia la revisión pública
   de metadatos solo por un incremento interno de credenciales.

El incremento común es una expresión SQL sobre el valor vigente, no un += sobre
una copia antigua del objeto. No pierde incrementos entre workers. RETURNING devuelve solo la versión explícita;
no se sincroniza la copia ORM del usuario. Los callers no deben tratar esa copia
como prueba de vigencia: la autenticación vuelve a cargar los atributos de SQL. El servicio
`revoke_user_tokens` no confirma ni revierte por su cuenta: el caller controla la
transacción. Se protege el límite máximo para no desbordar o volver a cero; se
requiere intervención operativa si se alcanza ese límite, sin degradar seguridad.

## API, sockets y experiencia del navegador

Las rutas de tracking y notificaciones usan las dependencias anteriores al
aceptar y al autorizar actividad/entregas. Un token revocado se rechaza al abrir
el socket; uno ya abierto se cierra con 1008 al detectar la revocación en una
comprobación posterior de entrada o envío. No se añade un broadcast de desconexión
instantánea a todos los workers. Un socket completamente inactivo puede quedar
abierto hasta la siguiente actividad; los pings existentes ayudan a detectarlo.

La interfaz muestra **Cerrar todas las sesiones** para expresar el alcance real.
El navegador mantiene su limpieza local inmediata y envía la petición con el
bearer capturado, sin refresh/reintento que pueda atribuirla a otra cuenta. El
transporte sigue siendo best effort y tiene 1500 ms de plazo; no se promete que
el servidor haya confirmado si se cierra la página, falla la red, expira el token
o se cancela esa espera. El servidor puede completar un commit aunque el cliente
haya dejado de esperar. Las otras pestañas retiran el contenido al observar el
rechazo; no reciben una limpieza local instantánea desde esta implementación.

La revocación no deshace operaciones ya aceptadas ni garantiza bloquear una
petición/frame que pasó su comprobación justo antes del commit. Tampoco retira
por sí misma tokens FCM/dispositivos ni mensajes que un proveedor ya aceptó.

## Migración y puesta en servicio

La revisión `20261028_auth_version` continúa desde `20260930_fase10`. Añade columna,
default y constraint. Para esta entrega se prueban sus operaciones sobre un
esquema PostgreSQL temporal con filas existentes; no se ejecuta contra producción
ni se certifica de nuevo toda la cadena histórica de Alembic desde una BD vacía.

Antes de desplegar:

1. Verificar en una copia/restauración de staging el estado real de Alembic y los
   prerrequisitos históricos. Respaldar y probar restauración según la operación
   del entorno. No hacer stamp de una base incompatible para saltar revisiones.
2. Aplicar la revisión de esquema antes de levantar el código que selecciona
   users.token_version. Comprobar columna/default/constraint y valor inicial 0.
   La aplicación no crea ni migra ese campo automáticamente.
3. Retirar todos los workers de código antiguo antes de considerar efectiva la
   revocación: un worker anterior ignora la versión. La ventana mixta no garantiza
   revocación uniforme. Verificar API y WebSockets contra los workers nuevos.
4. Comprobar login, refresh, logout confirmado, rechazo de ambos JWT antiguos y
   nuevo login. Probar además recuperación y cambio administrativo de contraseña.

El downgrade bloquea la tabla antes de comprobar versiones para no competir
con una revocación concurrente. Permite retirar la columna solo si todas las
versiones siguen en cero. Si detecta alguna revocación, falla antes de borrar el historial, evitando
que un upgrade posterior vuelva a aceptar JWT antiguos como versión cero. Un
rollback de código a una versión que ignora este campo también debilita la
revocación, aunque la columna siga presente. Cualquier rollback de seguridad
requiere un plan explícito de invalidación de credenciales/rotación de claves;
no se automatiza ni se ejecuta en esta entrega.

No se deben poner versiones a cero, copiar un valor antiguo sobre una cuenta
revocada ni eliminar esta columna para resolver un incidente de acceso.
Restaurar una copia anterior de la BD también puede restaurar credenciales
revocadas; contemplarlo en el procedimiento de recuperación del entorno.

## Evidencia y límites

Las pruebas nuevas cubren contratos HTTP montados, JWT firmados de prueba,
compatibilidad histórica, administración, recuperación, integridad SQL,
transacciones fallidas, cuatro workers concurrentes, identity maps precargados,
refresh en vuelo, operaciones de migración y sockets activos. PostgreSQL y Redis
son desechables y solo se usan bases test_* / esquemas privados. No se envían
mensajes externos ni se opera sobre usuarios reales.

Siguen pendientes sesiones por dispositivo, refresh de un solo uso y detección
completa de replay, coordinación global de pestañas, cookies HttpOnly, broadcast
inmediato de desconexión, y auditoría especializada de sesiones. Los helpers
históricos AuthService/UserService, sin consumidores de login activos y con
referencias incompatibles como is_deleted, no se activan ni se certifican con
esta entrega. Cambios de estado de repartidor conservan su política existente;
esta entrega no añade incrementos de versión en todas las transiciones de Rider.

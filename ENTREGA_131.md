# Delivery360 — entrega 131

## Preferencias personales verificables

La página `/notifications/preferences` usa el perfil verificado de la sesión y
el cliente API canónico. El control de acceso permite esta ruta exacta a los seis
roles conocidos, sin abrir otras rutas de notificaciones. El perfil antiguo de
localStorage no decide qué canales son editables.

Repartidor puede editar PUSH; cliente, EMAIL; los otros cuatro roles, EMAIL/SMS/PUSH.
Los canales ajenos al rol conservan su valor consultado y quedan deshabilitados.
Los comprobantes internos no se suprimen con estas preferencias; no se presenta
un interruptor IN_APP que prometa desactivarlos, ni se reescriben sus filas antiguas.
Permitir un canal no configura proveedores ni garantiza envío o recepción.

El catálogo y las preferencias se consultan juntos y se validan estrictamente.
No hay catálogo de reemplazo cuando falla una consulta. Se preservan códigos
históricos, valores falsos explícitos y eventos sin plantilla consultada. Se
proyectan únicamente campos públicos necesarios; no se renderiza cuerpo de
plantillas ni respuestas internas de error. Los códigos Unicode respetan el
límite de 50 puntos de código del backend.

## Escrituras y recuperación

Guardar envía únicamente celdas externas modificadas, con sus tres campos
necesarios. Cambiar una opción y devolverla a su valor elimina ese cambio.
La vista bloquea operaciones duplicadas y valida el acuse `status=ok` con el
número exacto de cambios. Después consulta de nuevo antes de anunciar éxito.

Si el acuse se pierde, queda un resultado incierto: la recuperación explícita
solo hace GET y no repite PUT. Si el acuse fue confirmado pero falla la lectura,
se conserva esa distinción también tras nuevos fallos. Cuando los valores actuales
difieren de los solicitados, se muestran para revisión y se conservan solo las
diferencias pendientes; adoptar los actuales no escribe. Una consulta manual con
borrador requiere una decisión central. Un fallo de esa consulta conserva el
borrador bloqueado hasta recuperar datos válidos.

Las actualizaciones parciales conservan celdas ajenas. El endpoint no ofrece CAS
ni revisión: dos escrituras concurrentes sobre la misma celda siguen la semántica
actual del backend. La lectura posterior detecta diferencias visibles en ese
momento, sin prometer exclusión mutua ni un snapshot atómico.

El desmontaje y las respuestas tardías están protegidos por usuario, rol, revisión
y generación de credenciales. Antes de GET/PUT se comprueba la generación de
montaje, incluso si cambió el almacenamiento antes de que React lo observe.
No se persisten preferencias ni borradores privados en almacenamiento del navegador.

## Interfaz y verificación

Encabezado violeta/índigo/celeste, tarjetas por evento, distintivos de plantillas
pausadas o no consultadas y barra de acciones adaptable. Decisiones y errores
usan modal central; confirmaciones, notificación informativa inferior derecha.

Pruebas unitarias cubren roles, DTOs, cambios parciales, doble clic, errores,
recuperación, respuestas contradictorias, concurrencia y cambio de credenciales.
Chromium valida el flujo con API sintética, controles sin obstrucciones a 320/390px
y recuperación sin repetir escrituras. CI añade el ensayo con API real en el
laboratorio marcado: una única preferencia propia de prueba, respuesta perdida,
lectura de recuperación y comparación de preferencias ajenas e historial original.
Las filas de prueba se retiran y se comparan las tablas protegidas antes/después.

No cambia backend, migraciones, dependencias, importes, pagos o credenciales.
Continúan pendientes homologación externa, aceptación de otros recorridos/roles,
carga representativa e infraestructura y recuperación productivas.

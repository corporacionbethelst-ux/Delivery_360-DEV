# Delivery360 — entrega 130

## Bandeja personal con sesión y recuperación verificables

La página `/notifications` cargaba y eliminaba avisos mediante un fetch separado,
con token leído directamente de localStorage. Una consulta fallida podía parecer
una bandeja vacía; marcar leído mediante el hook no actualizaba sus filas locales.
Las respuestas tardías de la página no tenían la misma protección de sesión que
los paneles administrativos ya existentes.

La bandeja ahora usa el cliente canónico, valida el DTO público y queda ligada a
credenciales, revisión de sesión, usuario y rol. Al cambiar identidad se desmontan
sus filas, filtros, modales y acciones pendientes; las respuestas tardías no
repueblan otra sesión ni publican confirmaciones. No guarda contenido de avisos
en almacenamiento persistente. Retira el transporte WebSocket adicional de la
página; la campana conserva su transporte y reconciliación existentes.

## Acciones y recuperación

Marcar leído espera `status=ok` y el UUID solicitado; eliminar exige confirmación
central y espera `status=deleted`. No hay cambios optimistas antes del acuse ni
fechas de lectura inventadas. Se bloquean clics duplicados y operaciones mientras
se consulta o hace falta recuperar el estado. Los siete eventos externos
gestionados conservan su historial y sus paneles de revisión.

Si la respuesta de una escritura se pierde o es contradictoria, su resultado se
presenta como incierto. La recuperación solo hace GET. Si la acción fue confirmada
y falla la lectura posterior, se conserva esa distinción, incluso cuando fallan
más consultas. No hay reenvío automático de PATCH/DELETE. La campana recibe una
señal local sin contenido ni credenciales y reconsulta únicamente en su generación
de sesión. La consulta manual y la recuperación correcta también reconcilian la
campana.

Las páginas se confirman solo tras una consulta válida. Si se elimina la última
fila, una corrección GET busca la última página vigente. Si vuelve a reducirse el
catálogo durante esa corrección, se conserva la consulta anterior y se pide
recuperación, sin bucles ni una página imposible. Los totales son los de la última
consulta; no se inventa un snapshot atómico que el endpoint actual no garantiza.

## Presentación y pruebas

Encabezado indigo/celeste, tarjetas de resumen, filtros con su alcance de página,
avisos legibles y acciones adaptables. El contador no leído identifica expresamente
su alcance IN_APP. Fechas en Caracas, errores/confirmaciones en modal central y
éxitos en el aviso inferior derecho. Un fallo inicial se distingue de una bandeja
realmente vacía y un fallo de actualización conserva la última consulta.

Jest comprueba formato, acuses, privacidad, sesiones, bloqueos, recuperación sin
repeticiones y paginación concurrente. Chromium sobre la compilación de producción comprueba diseño
en 320/390px, puntos reales de impacto, menús asentados, modal y toast, y una
eliminación simulada aplicada cuya respuesta se pierde. El ensayo real del
laboratorio crea dos avisos sintéticos: uno propio y otro ajeno; verifica lectura
y eliminación por UI, exclusión del otro usuario y conservación de su fila.
Limpia exclusivamente esas filas y compara después todas las tablas protegidas
y todo el historial original de notification_logs. CI conserva las evidencias.

No cambia backend, API, esquema, reglas financieras, proveedores o despliegue.
Continúan homologación externa, aceptación general, carga representativa e
infraestructura/recuperación productiva. Esta entrega cierra el bloque descrito
de bandeja personal; no acredita la aceptación completa del sistema.

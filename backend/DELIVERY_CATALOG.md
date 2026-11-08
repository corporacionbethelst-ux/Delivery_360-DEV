# Catálogo de entregas registradas

Entrega 74, 8 de noviembre de 2026, America/Caracas.

`GET /api/v1/deliveries/page` permite a GERENTE y SUPERADMIN consultar filas
reales de `Delivery`. Usa los roles actuales de la base, no claims de permisos
almacenados en el navegador. Sin autenticación devuelve 401; otros roles, 403.
No crea órdenes, entregas, notificaciones, asientos ni pagos.

| Parámetro | Contrato |
| --- | --- |
| `limit` | Entero 1–200, predeterminado 20 |
| `offset` | Entero >=0, predeterminado 0 |
| `status` | Opcional: PENDIENTE, INICIADA, EN_PICKUP, EN_ROUTE, EN_DESTINO, COMPLETADA, FALLIDA o CANCELADA |
| `rider_id` | UUID opcional, coincidencia exacta |
| `unassigned` | Booleano opcional; true exige rider_id NULL, false exige no NULL |

`unassigned=true` junto con `rider_id` devuelve 400. Tipos y estados inválidos
devuelven 422. Los filtros se combinan y afectan tanto al conteo como a las filas.
La respuesta contiene `items`, `total`, `limit` y `offset`; `total` cuenta todas
las entregas de la consulta, no solo la página.

Se reutiliza la serialización existente, incluyendo IDs reales, referencia
externa, cliente, repartidor, estado, fechas, minutos y SLA. Los joins son por
claves únicas y el orden es `created_at DESC, id DESC`, incluyendo desempate
determinista. El conteo y la lectura son dos sentencias con los mismos filtros;
no constituyen una instantánea transaccional inmutable entre solicitudes.

El modelo actual exige `Delivery.rider_id NOT NULL`. Por ello, Sin asignar devuelve
cero filas mientras se mantenga esa restricción. Las órdenes asignadas que todavía
no tienen entrega pertenecen a la consulta de órdenes. No se amplían las páginas
con representaciones artificiales de esas órdenes ni se altera el esquema.

La ruta histórica `/api/v1/deliveries` mantiene su comportamiento. La nueva ruta
se registra antes de `/{delivery_id}`. El inventario nuevo tiene 204 operaciones;
al retirar únicamente el nuevo GET, su enum OpenAPI y las dependencias que solo
usa este GET se recupera exactamente el inventario anterior de 203 operaciones,
incluidos orden, permisos y hash completo del esquema. Se conservan los fixtures
históricos y sus comparaciones.

El catálogo del gerente solicita 20, 50 o 100 filas, confirma consulta y datos
juntos, y distingue filtros en edición de filtros aplicados. Buscar actúa solo
sobre la página confirmada. Un error conserva los datos y permite repetir la
consulta fallida exacta. Cambiar de credenciales/cuenta desmonta el estado privado;
las respuestas retiradas no pueden repoblar la pantalla. La detección de IDs
repetidos entre páginas adyacentes pide reintentar sin aceptar la página ambigua;
no detecta todas las omisiones posibles de una paginación por desplazamiento
con escrituras concurrentes.

Referencia, cliente, estado, duración o SLA ausentes se indican como desconocidos.
Cero minutos y SLA false se conservan. Las fechas sin zona del backend se
interpretan como UTC y solo se estima duración para estados activos; un estado
terminal sin hora final no se convierte en una entrega todavía en curso.

Evidencia: 25 casos PostgreSQL/PostGIS con dos repartidores reales de prueba,
desempates, filtros, límites, permisos, ausencia de órdenes artificiales y libro
financiero sin cambios; contrato de compatibilidad de API; pruebas frontend de
normalización, sesión, carreras y reintentos; Chromium sobre el build de
producción con lecturas sintéticas interceptadas. Estas últimas no certifican
integraciones productivas ni rendimiento sobre un volumen real.

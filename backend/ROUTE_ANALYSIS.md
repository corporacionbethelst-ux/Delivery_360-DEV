# Rutas persistidas, desvíos y ETA — entrega 51

Fecha: 29 de octubre de 2026 (America/Caracas).

Esta entrega conecta el endpoint GPS heredado con las tablas que existen en el
proyecto. Añade planificación manual, historial, métricas y revisión de desvíos.
No añade navegación vial, predicción de tráfico ni una integración de Directions.

## Fallos corregidos

- La ruta pública estaba montada como /api/v1/routes/routes/{rider_id}/track.
  Consultaba Route.rider_id/end_time/start_time, columnas inexistentes, y trataba
  la relación Route.points como una lista JSON de diccionarios.
- El CRUD creaba rutas y desvíos con nombres de campos inexistentes. El servicio
  usaba el estado no válido active, bearing en lugar de heading y omitía el
  timestamp obligatorio del punto. Resolver un desvío asignaba un atributo Python
  is_resolved sin persistir el estado real.
- El análisis trataba un recorrido como un polígono y medía solo sus vértices.
  El worker comparaba metros con 0,5 y después multiplicaba otra vez por 1000.
- Las supuestas paradas dependían exclusivamente del tiempo transcurrido.
  Las métricas para cero o un punto omitían points_count.
- El worker importaba una fábrica de sesiones inexistente, mezclaba SQL síncrono
  con sesiones asíncronas y podía intentar cerrar una variable no inicializada.
- El ETA sustituía destinos con latitud o longitud cero por la posición actual
  del repartidor, e incluso usaba esa posición como destino cuando faltaban datos.
  El SDK opcional de Google bloqueaba el bucle asíncrono y registraba excepciones
  que podían contener detalles del transporte.

## API y autorización

Todas las rutas siguientes se montan bajo /api/v1/routes. Se mantiene un solo
router, también exportado por routers_combined para conservar compatibilidad.

| Método/ruta | Función | Acceso |
| --- | --- | --- |
| GET / | Lista paginada, sin cargar relaciones GPS completas | Personal operativo, auditor; rider solo sus rutas |
| POST / | Crea el plan de una entrega no terminal | SUPERADMIN, GERENTE, OPERADOR |
| GET /{route_id} | Plan y estado persistidos | Igual que la lista, con pertenencia |
| POST /{rider_id}/track | Guarda un punto y la última posición del rider | Personal operativo o rider propietario; auditor/cliente denegados |
| POST /routes/{rider_id}/track | Alias de la URL anterior, misma autorización y persistencia | Igual que track |
| GET /{route_id}/points | Historial ordenado, fechas y paginación | Lectura autorizada de esa ruta |
| GET /{route_id}/metrics | Distancia, velocidades, duración y paradas | Lectura autorizada de esa ruta |
| GET /{route_id}/deviations | Eventos y datos de resolución | Lectura autorizada de esa ruta |
| POST /{route_id}/analyze | Analiza los puntos guardados con umbral de 500 m | Personal operativo |
| POST /{route_id}/deviations/{deviation_id}/resolve | Cierra un evento y registra actor/fecha/notas | Personal operativo; ambos IDs deben pertenecer al mismo recurso |

El rol desconocido/NULL y CLIENTE no heredan acceso por estar autenticados.
El control de pertenencia usa Delivery.rider_id y Rider.user_id; nunca compara
el ID de usuario con el ID del perfil de rider. Las lecturas no permiten que un
repartidor consulte el historial, las métricas o los desvíos de otro.

Ejemplo de creación:

```json
{
  "delivery_id": "00000000-0000-0000-0000-000000000001",
  "planned_route": [
    {"latitude": 4.60, "longitude": -74.08},
    {"latitude": 4.61, "longitude": -74.07}
  ],
  "distance_km": 2.4,
  "duration_minutes": 12
}
```

Se aceptan entre 2 y 2000 puntos finitos, con latitud [-90,90] y longitud
[-180,180]. El formato se valida explícitamente; no se interpreta GeoJSON,
polylines codificadas ni JSON heredado desconocido. Los extremos antipodales se
rechazan porque no definen un arco menor único. Distancia y duración planificadas
son estimaciones suministradas por el solicitante, no resultados verificados de
un proveedor vial; su valor predeterminado cero no acredita una ruta sin coste.

Ejemplo de punto:

```json
{"lat": 4.605, "lng": -74.075, "delivery_id": "00000000-0000-0000-0000-000000000001", "speed_kmh": 18, "heading": 90}
```

Solo se acepta una entrega activa del rider (INICIADA, EN_PICKUP, EN_ROUTE o
EN_DESTINO), con ruta previamente planificada y no terminada/cancelada. Si hay
varias entregas activas, delivery_id es obligatorio para desambiguar; no se elige
la primera ni se inventa una ruta. Una entrega ajena o inactiva no resulta válida.

La ingesta conserva el mismo control de cuenta y documentos de la ubicación en
vivo: ACTIVO/OCUPADO, documentos requeridos aprobados y archivos disponibles. Se
ejecuta antes de escribir GPS. El timestamp es UTC del servidor; el cliente no
puede imponerlo. Velocidad opcional: 0–300 km/h; heading: 0–360°. Se rechazan
booleanos, cadenas numéricas, NaN, infinito y campos adicionales.

El punto, la transición PLANIFICADA→EN_PROGRESO y la última posición del rider se
confirman juntos. Un error revierte esos cambios. Se conserva started_at existente
y no se fuerza is_online=true ni se rehabilita una cuenta. Si los documentos no
permiten conectarse, la restricción de seguridad puede persistirse antes del 403,
como ya hace el canal de tracking; esa transacción no incluye el punto rechazado.

## Métricas y geometría

La geometría calcula metros sobre una esfera de radio 6 371 000 m. Para un desvío
se toma la mínima distancia al arco menor de cada segmento de la ruta planificada,
limitada por sus extremos. Maneja el cruce del antimeridiano y evita dominios
inválidos por redondeo en Haversine. No confunde el interior de un polígono con
estar sobre un recorrido, ni una recta infinita con el segmento de la ruta.

Las métricas devuelven siempre seis campos:

| Campo | Definición |
| --- | --- |
| total_distance_km | Suma geodésica entre observaciones consecutivas, redondeada a 0,001 km |
| avg_speed_kmh | Distancia / tiempo total transcurrido, incluyendo paradas; cero si no hay intervalo positivo |
| max_speed_kmh | Máxima velocidad válida reportada por el dispositivo; cero si falta, no una velocidad inferida |
| total_time_minutes | Diferencia entre último y primer timestamp |
| points_count | Número de observaciones, también para 0 o 1 punto |
| stops_count | Grupos estacionarios según la regla de evidencia descrita abajo |

Una parada exige posiciones dentro de 30 m del punto inicial del grupo durante al
menos cinco minutos, sin huecos entre muestras superiores a 120 segundos. Un grupo
se cuenta una sola vez. Movimiento fuera del radio o pérdida de continuidad inicia
otro grupo; esperar entre dos reportes no prueba una parada. Son heurísticas, no
evidencia de una entrega o de una infracción del rider.

Las métricas y el análisis se limitan a 10 000 observaciones. Se consulta una fila
extra para detectar exceso y se devuelve error; no se devuelve un resultado parcial
con apariencia de total. El historial se pagina hasta 1000 puntos por petición y
la lista hasta 200 rutas. La geometría intensiva se ejecuta fuera del bucle
asíncrono; los hilos no consultan la sesión durante el análisis de desvíos.

No se filtran automáticamente saltos por mala precisión GPS. Distancia en línea
geodésica, velocidad reportada y huecos de muestras tienen límites de calidad; no
deben usarse para sanciones, facturación, SLA o liquidación automática.

## Persistencia y diccionario de campos utilizados

Se tipan 74 columnas existentes (57 de rutas y 17 de tracking). Los contratos
versionados verifican DDL PostgreSQL, defaults, índices, enums y claves foráneas.
No hay migración nueva en este bloque ni cambios de nulabilidad, nombres o tipos
SQL. Las relaciones points/deviations usan back_populates en ambas direcciones.

| Tabla | Campos y significado usados en esta entrega |
| --- | --- |
| routes | id UUID PK; delivery_id UUID FK UNIQUE a deliveries; status enum PLANIFICADA/EN_PROGRESO/COMPLETADA/CANCELADA; planned_route JSON canónico; planned_distance_km FLOAT y planned_duration_minutes INTEGER estimados; coordenadas inicial/final; started_at/completed_at UTC; has_deviation y deviation_distance_km como evidencia histórica de desvío |
| route_points | id UUID PK; route_id UUID FK; latitude/longitude FLOAT NOT NULL; timestamp TIMESTAMP NOT NULL; speed FLOAT (km/h en los nuevos escritores); heading FLOAT grados; resto de campos de dispositivo conservados |
| route_deviations | id UUID PK; route_id UUID FK; deviation_type, severity; latitude/longitude observadas; detected_at NOT NULL; distance_from_route_km FLOAT; expected_location/actual_location JSON; status abierto/resuelto; resolved_at, resolved_by FK users, resolution_notes; campos de alertas conservados sin afirmar envío |
| rider_live_locations | Posiciones del canal /tracking, tipos escalares UUID/float/datetime; conserva sus índices y política de retención previa |
| delivery_route_snapshots | Resultados del optimizador VRP existente; tipos escalares UUID/float/str/datetime, sin cambiar algoritmo o TTL |

distance_from_route_km se guarda en kilómetros; los argumentos de distancia del
CRUD y los umbrales se expresan en metros. deviation_distance_km de routes es el
máximo registrado por estos escritores, no una suma del recorrido fuera de ruta.
Resolver un evento persiste status=resuelto y su actor/fecha/notas; repetir la
resolución conserva la primera. Un estado heredado desconocido exige revisión.
No se borra el histórico ni se reinician automáticamente has_deviation o tiempos.

## Worker y concurrencia

analyze_route_deviations recibe un UUID de entrega en texto. Crea un engine
asíncrono por invocación con NullPool, abre/cierra su sesión y dispone el engine
incluso ante error. Se registra en include de Celery; no se añade periodicidad ni
encolado automático desde la ingesta GPS o el cierre de una entrega.

Un lock FOR UPDATE sobre routes serializa a estos analizadores en PostgreSQL. Cada
evento automático guarda actual_location.route_point_id; repetir o ejecutar a la
vez el análisis del mismo punto conserva el evento. La creación de la ruta bloquea
la entrega antes de revisar la restricción UNIQUE; dos solicitudes cooperantes no
crean dos rutas. El evento, el indicador de ruta y su distancia se confirman en la
misma transacción. Una resolución emplea lock sobre su evento.

La deduplicación no es una restricción única SQL ni una garantía general de entrega
exactamente una vez. No cubre escritores antiguos/no cooperantes, borrado externo de
eventos o replanificación directa de la base. Un reintento HTTP de GPS puede crear
otro punto con un ID distinto: aún no hay clave de idempotencia para esa ingesta.
El lock se mantiene durante el análisis; la paginación de trabajos grandes y la
reclamación durable de tareas siguen pendientes. SQLite no demuestra exclusión.

El worker no reintenta errores de entrada/plan/demasiados puntos; devuelve una
causa genérica de revisión. Los fallos de infraestructura reintentan hasta tres
veces con error genérico. No se guardan coordenadas ni excepciones crudas en el
resultado de error. Se comprueban recursos y concurrencia con PostgreSQL temporal,
pero no se certifica el arranque del conjunto de workers Celery: otros módulos
heredados conservan importaciones de get_db_session inexistentes y requieren su
propio bloque de corrección antes de habilitar ese conjunto en producción.

## ETA y canal en vivo

El ETA local requiere un destino válido del pedido, conserva coordenadas cero y
valida la velocidad configurada (0,1–300 km/h). No convierte la posición actual
del rider en destino. Usa distancia geodésica/velocidad como aproximación y un
mínimo de un minuto; no es predicción vial ni de tráfico.

Google Distance Matrix es opcional: su SDK síncrono se ejecuta en un hilo con
timeout de petición 5 s, retry_timeout 5 s y sin retry_over_query_limit. No se
afirma un deadline global exacto: los tiempos dependen de la biblioteca de
transporte. Respuestas sin duración numérica finita positiva o sin status OK no
reemplazan el ETA local. Un error conserva el cálculo local y no registra su texto
crudo. Los tests sustituyen el SDK; no se usan claves ni se hacen consultas reales.

En el fallback REST, una posición inválida se declara no disponible; un destino
incompleto/inválido deja distancia y destino desconocidos. No se serializan NaN
como coordenadas de destino. Se conservan las comprobaciones de rol y pertenencia
de tracking; simplificar la lectura del enum no amplía permisos.

La nueva ingesta de route_points no inserta rider_live_locations ni publica un
evento WebSocket/Redis. Son historiales distintos; el canal /tracking existente
mantiene esas funciones. No hay interfaz frontend nueva en este bloque.

## Verificación y operación pendiente

Los tests cubren geometría física, antimeridiano, formatos inválidos, metros/km,
paradas/lagunas GPS, destino cero/ausente, SDK fuera del event loop, esquema sin
cambios, permisos, persistencia nativa, rollback, concurrencia y replay de worker.
Los resultados completos se registran en Implementacion_de_mejoras_V1.md.

Antes de desplegar, validar planes y estados existentes en staging y actualizar
todos los escritores cooperantes. Este bloque no actualiza históricos ni aplica
migraciones. Sustituye la URL antes rota por la canónica y conserva su alias.

Siguen pendientes idempotencia de ingesta, unificación de trazas, captura automática
de puntos en el flujo de la app, UI de planificación/revisión, ciclo completo de
replanificación/finalización, cartografía vial, calidad/retención de GPS y auditoría
integral, outbox de alertas, rate limiting distribuido, salud del conjunto Celery,
Mypy global y cobertura frontend. La emisión fiscal real continúa bloqueada por
la entrega 50 hasta disponer de transporte y homologación verificables.

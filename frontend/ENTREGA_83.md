# Entrega 83 — Auditoría del sistema

Fecha de registro: **10 de noviembre de 2026, UTC**.
Rama: `feat/system-audit-reliability-v1`.
Base main: `c416c8248c3a8dace2f86b3ca5f2d0be7884d944`, árbol
`88bb402b35a577e0b25eb758e71c2aa531c6c967`. El propietario integró la entrega
82 mediante PR #324; su CI completo terminó aprobado.

## Consulta y presentación

La auditoría administrativa adopta encabezado violeta/azul, indicadores de alcance,
filtros en tarjeta y resultados con etiqueta y color. Conserva la estructura de
consulta de eventos y utiliza los endpoints existentes. La tabla se desplaza con
teclado en móvil; los detalles y las confirmaciones tienen altura limitada.

- Los filtros se editan como borrador y se aplican de forma explícita. No se
  consulta por cada tecla. Cambiar búsqueda, acción, resultado, recurso, ID de
  recurso, ID de usuario o fechas reinicia la paginación al aplicar.
- La tabla identifica la consulta confirmada, su total real, página y fecha de
  lectura. Datos, filtros y hora anteriores se conservan ante fallos. Una nueva
  consulta pendiente se distingue de los datos conservados. El reintento usa los
  filtros y offset solicitados; un fallo inicial no presenta una lista vacía.
- Las fechas de calendario abarcan días completos de **America/Caracas** y se
  convierten a instantes UTC antes de enviarse. Se respeta también el desplazamiento
  histórico de la zona. Los eventos se muestran con fecha absoluta y zona clara:
  prioridad para occurred_at_utc válido y respaldo en created_at UTC heredado.
- El resumen de siete días es global e independiente de los filtros. Su lectura,
  error y reintento son independientes de la tabla. Un error conserva el resumen
  previo con su hora. Cero se conserva; el contador de éxito informado no se
  confunde con la clasificación SUCCESS y puede incluir advertencias.
- Acciones y estados desconocidos se muestran como texto neutro, incluso nombres
  que coincidan con propiedades del prototipo. No se convierten en Correcto.
  Se mantiene la distinción entre actor identificado sin email y evento SYSTEM.

## Detalle y exportación

Ver detalle consulta el registro original por ID: actor, recurso, origen,
solicitud, código HTTP, descripción, resumen de cambios, error y valores
anteriores/nuevos. No se sustituye un detalle fallido por datos parciales de la
fila. Hay reintento por identidad y retiro de respuestas al cerrar o cambiar de
cuenta. El contenido se representa como texto; un valor con HTML no se ejecuta.

CSV requiere confirmación del alcance capturado: filtros confirmados, desde el
primer resultado, incluyendo otras páginas, y hasta **5000 eventos**. Un borrador
sin aplicar bloquea la exportación para evitar ambigüedad. Si el total confirmado
supera el límite se sugiere acotar filtros. El archivo puede reflejar cambios
posteriores a la tabla; no se afirma un número descargado que la API no informa.

La exportación pendiente bloquea duplicados, cambios de consulta, recargas y
cierre del diálogo. Un error conserva los filtros para reintentar. Se rechazan
HTML, JSON u otros cuerpos que no tengan la cabecera CSV esperada. El navegador
descarga el CSV del servidor y retira enlaces y Blob URLs después de usarlos o
al abandonar la página. Un resultado de una sesión retirada no descarga archivos.

## Contrato y API

El servicio valida límites, offset entero, filtros, UUID de usuario, rango de
fechas y períodos de resumen. Deja de recortar paginación silenciosamente en
100000. Las respuestas comprueban metadatos, campos, identidades únicas, resultado
y acción solicitados, y totales del resumen. La identidad completa se codifica en
el detalle y su acuse debe coincidir. Todas las respuestas quedan ligadas a su
generación de credenciales. Gerencia y superadministración mantienen el acceso;
los demás roles, incluido Auditor, siguen sin permiso según la API existente.

En backend, SUCCESS y WARNING ahora usan el mismo criterio que la serialización:
un ACCESS_DENIED o un HTTP 4xx no entra en SUCCESS; success=false o HTTP 5xx
pertenecen a FAILURE y se excluyen de WARNING. Los valores NULL heredados se
clasifican de manera coherente. El arreglo se aplica a lista y exportación.

El exportador CSV convierte texto que comienza con un prefijo de fórmula en una
celda literal, incluyendo prefijos con espacios, tabulaciones, controles o BOM.
Se mantienen comas, comillas, Unicode, saltos de línea y números. Los eventos
persistidos y la respuesta de detalle conservan los valores originales.

## Validación

| Control | Evidencia |
| --- | --- |
| Casos frontend nuevos | **93 aprobados** |
| Regresión focalizada frontend | **95 pruebas / 3 suites aprobadas**, incluidos los dos casos anteriores de auditoría de flota |
| Suite frontend completa | **2623 pruebas / 120 suites aprobadas**, 52,927 s |
| Cobertura global frontend | **63,15 % sentencias; 59,36 % ramas; 59,76 % funciones; 62,61 % líneas** |
| Mínimos y selección | Sin cambios; pasan los cuatro mínimos de 50 % |
| TypeScript y build con lint | Aprobados; **48 páginas**, 16 advertencias existentes |
| API nueva | **29 pruebas aprobadas**: partición de resultados sobre 42 combinaciones persistidas, CSV y acceso |
| Montaje PostgreSQL/PostGIS | **16 pruebas existentes de transacciones aprobadas** antes de la corrida completa |
| Backend estático | Black y flake8 crítico aprobados; mypy sin errores en **195 archivos** |
| Chromium | **121 comprobaciones**: auditoría del sistema 15 y los diez smokes anteriores 106 |
| Navegador | Datos y CSV sintéticos; **cero escrituras de negocio y cero excepciones JavaScript** |
| Formato y workflow | Prettier, Black y actionlint aprobados |

Jest simula HTTP y servicios para comprobar payloads, errores, retiros de sesión,
descargas y respuestas tardías. Pytest usa base aislada para las pruebas nuevas;
la suite completa local se ejecuta además con PostgreSQL/PostGIS y Redis
exclusivos de esta entrega. Su resultado final, y el del CI remoto requerido,
se registran por SHA en el PR y `/workspace/work/entrega83/verification.json` y
`ci-observation.json`; los casos focalizados no se presentan como una corrida
completa. Las corridas de montaje interrumpidas no cuentan como aprobadas.

Chromium comprueba el build standalone real y descarga un CSV sintético por el
endpoint interceptado. Se suma el nuevo smoke al frontend-container requerido,
conservando los diez anteriores. No se certifican operaciones integrales contra
staging ni accesibilidad integral. Evidencia y capturas en `/workspace/work/entrega83`.

Sin dependencias, rutas públicas, esquema de base de datos, migraciones o formulario
original de orden nuevos. No se modifican los componentes antiguos de auditoría
que no consume esta página. Publicación por ramas y PRs previamente autorizada;
sin merge, deploy ni operaciones productivas del agente. Se conservan ZIP sin
archivos de entorno, bundle incremental, patch y hashes. Continúan pendientes
staging, infraestructura, carga, restauración, proveedores y protección de main.

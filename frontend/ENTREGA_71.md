# Entrega 71 — Catálogo de auditoría, filtros y CSV de página

Fecha: 7 de noviembre de 2026, America/Caracas.
Base: `9383271c75ecf9fa0859a4245c7f9ff6eaeb0612` (PR #311 fusionado).
Rama: `fix/rider-audit-catalog-filters-and-csv-v1`.

Checkout limpio al iniciar, sin AGENTS.md aplicable. Se conserva el historial.
El CI final de la entrega 70 aprobó backend y seguridad; frontend aprobó 1600
pruebas y tipos/lint/build, con fallo solo del gate global del 50 %. Es evidencia
remota de la base, no validación nueva de esta implementación.

## Problemas confirmados y cambios

El catálogo leía un único lote de hasta 250 filas sin navegación, sumaba importes
sin moneda e identificaba CSV solo por nombre/email, omitiendo IDs. Un error borraba
las tarjetas. No había retiro de lecturas por cuenta/consulta ni frontera propia
de acceso. Los filtros visibles podían diferir de los datos durante una carrera.

- Servicio específico con contrato real de `/riders/audit/summary`, filtros
  status_filter/is_online validados y conservados, y envelope acotado comprobado.
  total del endpoint es cantidad de filas de página, no un total global.
- Páginas de 50 con una fila extra como señal; búsqueda local identificada, incluso
  por ID, placa o nombre sin acentos. Se distinguen métricas de coincidencias y
  agregados por rider. No se suman importes de monedas desconocidas.
- Consulta confirmada junto con filas. Error conserva la página y sus etiquetas;
  reintento fiel, refresh del offset confirmado y reinicio explícito recuperable.
  Se comprueban duplicados/solapes de rider y usuario y respuestas fuera de filtro.
- Servicio/controlador/frontera retiran respuestas de otra cuenta/rol o lectura
  anterior; se conserva el refresh de la misma cuenta. Cambio de cuenta limpia
  búsqueda y datos antes de recibir la respuesta nueva. Solo GERENTE/SUPERADMIN.
- CSV exclusivamente de coincidencias de la página, con 33 columnas, IDs reales,
  contexto, alcance parcial, ceros, desconocidos, signo y UTC. No exporta lookahead
  ni ejecuta otra lectura. Se bloquea durante lectura/error y se recupera de fallos
  de descarga. Se reutiliza el helper seguro sin cambiarlo.
- Se amplía el normalizador compartido con metadatos y límite configurable; el
  detalle mantiene su límite por defecto de 100. Se adapta su script de navegador
  al nuevo enlace real por ID y se ejecuta como regresión, además del script nuevo.

Contrato y ejecución: [RIDER_AUDIT_CATALOG.md](RIDER_AUDIT_CATALOG.md).

## Validación nueva

**100 pruebas netas nuevas**, en cinco suites de contrato, servicio, controlador,
UI y Axios/API real con adaptador en memoria. Las 125 pruebas de detalle anteriores
se ejecutaron inicialmente y permanecen en la suite completa.

| Control | Resultado local de esta entrega |
| --- | --- |
| Frontend completo con cobertura | **1700 aprobadas / 92 suites**, 42,434 s |
| Statements / ramas / funciones / líneas | 43,56 % / 41,68 % / 40,06 % / **41,77 %** |
| Gate global del 50 % | Sigue fallando en cuatro métricas; umbrales/exclusiones intactos |
| Contrato, servicio y controlador nuevos | 100 % de líneas |
| TypeScript y lint | Aprobados; 22 advertencias existentes fuera del bloque |
| Build con Inter real | Aprobado, 48 páginas; tipos/lint activos |
| Chromium catálogo | **7 comprobaciones**, 14 lecturas, un CSV real de 1 fila/33 columnas descargado y verificado |
| Chromium regresión del detalle | **7 comprobaciones**, 54 lecturas |
| Escrituras HTTP / excepciones pageerror | **0 / 0** en ambos scripts |
| git diff --check / Black de ambos scripts | Aprobados |
| Backend | Sin cambios; no se atribuye una corrida backend local nueva |

Chromium verifica paginación, fila extra oculta, disponibilidad desconocida,
métricas acotadas, búsqueda/CSV sin otro GET, contenido real del archivo (IDs,
cero, Offline, moneda vacía, UTC, fórmula neutralizada, comillas y salto de línea),
filtro fallido/reintento, cambios rápidos fuera de orden, escritorio/móvil,
enlace al detalle y logout con lectura pendiente. La regresión del detalle
comprueba su conjunto confirmado, entregas de apoyo y retiro por ruta/sesión.
Se revisan capturas de escritorio y móvil. HTTP/WebSocket son interceptados con
datos sintéticos; no sustituyen E2E con backend o proveedores reales.

## Límites y siguiente prioridad

Sin snapshot ni desempate estable en el backend, cambios de nombre/disponibilidad
pueden mover filas entre páginas; rechazar solapes observables no detecta todas las
omisiones. Búsqueda y CSV son expresamente parciales. Algunos NULL llegan ya
sustituidos por cero/false/texto desde los serializers; no se reconstruyen ausencias.
Los agregados y sus criterios legacy no certifican transferencias ni saldo disponible.
Backend, dependencias, workflows, umbrales y autorización del servidor no cambian.

La siguiente prioridad concreta es el listado de entregas de gerencia: contrato de
páginas y órdenes de apoyo, filtros confirmados —incluido Sin asignar—, sesión y
fidelidad de duración/estados. En ese código persisten la referencia inventada,
estado PENDIENTE por defecto, borrado de datos ante fallo y filtro Sin asignar que
no se aplica con búsqueda vacía. También quedan pendientes cursor/orden estable,
cobertura global del 50 %, E2E real y homologación sandbox de fase 7. No se envían
pagos, mensajes o facturas reales, ni migraciones productivas, merge o deploy.
Publicación y CI observado se registran por separado.

## Publicación verificada

- PR sin borrador: https://github.com/corporacionbethelst-ux/Delivery_360-DEV/pull/312
- Implementación: `c56fb8673e4f6543d0df4f6758a8e02e34450f77`.
- Árbol de implementación cotejado local/GitHub: `a77869569a55922a7098aad438582c43826c59e2`.
- Se publican 18 archivos de implementación/pruebas/documentación. Un segundo
  commit exclusivamente documental registra estos identificadores.
- El PR informa el CI observado del head final por separado de los resultados
  locales. La publicación no fusiona ni despliega la rama.

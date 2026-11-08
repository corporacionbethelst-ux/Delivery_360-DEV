# Entrega 74 — Catálogo real y cobertura global frontend aprobada

Fecha: 8 de noviembre de 2026, America/Caracas.
Base limpia: `6fbb69d9055c8d43b044d719985166f44f805e2b`, árbol
`2d3228d9db1044373b35c47de00d601ab3a9c00b` (PR #315 fusionado por el propietario).
Rama: `fix/delivery-catalog-and-frontend-reliability-v1`, revisión contra main.

## Resultado

Se reemplaza la pantalla de entregas del gerente, que mezclaba consultas amplias y
supuestos locales, por un catálogo paginado de entregas registradas. La nueva API
de lectura tiene conteo filtrado y orden estable; conserva intacta la API anterior.
La pantalla confirma filtros y filas juntos, permite búsqueda local y reintento
exacto, preserva datos ante fallos y retira respuestas al cambiar de sesión.
No inventa referencias, entregas, duración o cumplimiento de SLA.

Los cuatro umbrales globales frontend del 50 % pasan con el conjunto completo.
No se reducen umbrales, no se cambia `collectCoverageFrom` y no se excluyen fuentes.
Jest ignora los módulos generados de `.next` para evitar colisiones al coexistir
con el build standalone; esa carpeta ya estaba fuera de los tests y de `src`.

Contrato: [catálogo de entregas](../backend/DELIVERY_CATALOG.md).

## Mejoras adicionales verificadas

- Autenticación: storage y payload malformados, expiración exacta y no finita,
  claims canónicos, roles desconocidos y generación criptográfica sin fallback
  predecible. Los helpers cliente no verifican firmas ni sustituyen al servidor.
  Errores de servicios dejan de imprimir cuerpos, credenciales o datos de registro.
- Servicios: IDs codificados en rutas y consultas, errores de API consistentes,
  coordenadas válidas incluyendo cero, tarifas y años finitos/acotados. Una caída
  al consultar entrega por orden o alertas pendientes ya no se presenta como una
  ausencia confirmada. El contador histórico de alertas sigue acotado a su página,
  no se declara un total global nuevo.
- Tiempo: tokens repetidos, duraciones ISO estrictas y fracciones, fechas inválidas,
  instantes UTC/local sin desplazar dos veces y segundos relativos pasados.
- Geolocalización: retiro de callbacks tardíos, timers y watch ID cero; rangos,
  opciones y valores desconocidos; excepciones de consumidores contenidas.
- Estado de roles y navegación: flags retirados sin autenticación, comodines
  consistentes, toggles rápidos y navegación sin storage disponible.
- Tiempo real: estados terminales canónicos/legacy salen del mapa activo. El SDK
  WebSocket genérico controla promesa de conexión, cola, parada y callbacks viejos.
  Sus pruebas usan un contrato simulado: no se presenta como un nuevo transporte
  de tracking conectado al servidor.
- El feed local legacy deja de generar órdenes aleatorias y de mostrar una conexión
  remota ficticia. Su contexto comparte el estado y los contadores, se acota y se
  limpia al cambiar credenciales. El transporte canónico de notificaciones sigue
  separado; no se conectó un servicio remoto nuevo.
- Helpers financieros locales corrigen IDs y rechazan importes no finitos. Sus
  cálculos siguen siendo estimaciones y sus transacciones siguen PENDIENTE; no
  sustituyen al libro contable ni prueban liquidación bancaria.

## Evidencia local nueva

| Control | Resultado |
| --- | --- |
| Frontend completo | **2208 pruebas, 109 suites aprobadas**, 31,18 s |
| Cobertura sentencias | **54,78 %** |
| Cobertura ramas | **50,64 %** |
| Cobertura funciones | **50,23 %** |
| Cobertura líneas | **53,39 %** |
| Delta frontend | **508 pruebas adicionales**, frente a 1700/92 suites |
| Backend completo PostgreSQL/PostGIS y Redis | **2566 aprobadas, 2 omitidas**, 714,63 s, cobertura 72 % |
| Delta backend | **26 casos adicionales**: 25 del catálogo y 1 de compatibilidad |
| API | **204 operaciones**; las 203 anteriores y sus esquemas se recuperan exactamente |
| TypeScript y ESLint | Aprobados; permanecen 21 advertencias existentes, sin desactivar reglas |
| Build de producción | **48 páginas**, Next 15.5.29 standalone, fuente Inter real, API `/api/v1`, comprobaciones activas |
| Backend estático | Black, flake8 crítico y mypy aprobados, 195 archivos de aplicación |
| Release y workflows | **8 unittest** y actionlint 1.7.7 aprobados |
| Chromium, catálogo nuevo | 7 comprobaciones, escritorio/móvil, filtros, búsqueda, páginas, fallo/reintento y cero escrituras |
| Chromium, auditoría previa | 7 comprobaciones, CSV real de datos sintéticos, filtros, carreras y retiro por logout |

Las pruebas PostgreSQL usan esquemas aislados y servicios locales exclusivos de
prueba. Una interrupción del entorno cortó una corrida anterior; el resultado de
2566 corresponde a una ejecución completa posterior. Se retiraron contenedores
y volúmenes de prueba al terminar. El navegador usa el build de producción local
con tráfico de negocio interceptado y datos sintéticos; no es E2E de staging.

Los números de cobertura corresponden a las fuentes finales formateadas. No se
atribuyen resultados de una versión anterior. No cambian dependencias ni lockfiles
en esta entrega y no se declara un build Docker local: las imágenes y sus smokes
se validan en los jobs remotos. La prueba Chromium del catálogo nuevo se añade
al job existente `frontend-container` y conserva los controles anteriores.

## Qué falta para producción

La cobertura frontend deja de ser el bloqueo observado en las entregas anteriores.
Su margen en ramas y funciones todavía es estrecho y conviene ampliarlo con
pruebas de nuevos cambios. Esto no certifica por sí solo aptitud para producción.

Quedan activación administrativa de protecciones de main/environments, auditoría
de las imágenes finales y del sistema operativo, infraestructura y secretos reales,
E2E de staging entre servicios, carga y restauración verificadas, y homologación
de proveedores bancarios/fiscales/mensajería. La consulta remota de main durante
el cierre todavía devuelve `protected=false`. Los avisos npm dev y pytest dev
documentados en la entrega 73 no se reauditan ni se dan por resueltos en este delta.

El modelo exige repartidor para una entrega: Sin asignar devuelve cero; las órdenes
sin entrega se consultan en órdenes. El filtro de repartidor acepta su UUID real.
El orden estable no convierte páginas concurrentes en una instantánea inmutable.

La revisión se publica sin draft y su CI se observa por SHA en el PR y en el
manifest del workspace. No se hereda éxito global de otros commits. No se ejecutan
merge, deploy, migraciones productivas, pagos, mensajes ni facturas reales.
Bundle incremental, patch, ZIP de fuentes sin archivos `.env*`, hashes y registros
de validación se conservan en `/workspace/work/entrega74`.

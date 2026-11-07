# Entrega 69 — Historial y detalle de transacciones fieles

Fecha: 7 de noviembre de 2026, America/Caracas.
Base: `aae16c02b6b734882dec5f408863e7b13aaccbf0` (PR #309 fusionado).
Rama: `fix/transaction-history-and-detail-contract-v1`.

Checkout limpio al iniciar, sin AGENTS.md aplicable. Se conserva el historial.
El CI final de la entrega 68 aprobó backend y seguridad; frontend tuvo 1351
pruebas aprobadas, build aprobado y fallo solo del gate global del 50 %. Son
resultados remotos de la base, no validaciones nuevas de esta entrega.

## Problemas y cambios

El historial filtraba localmente el primer lote, presentaba retiros positivos
como ingresos y exportaba ese lote con alcance ambiguo. El servicio admitía solo
10 de los 18 tipos reales, inventaba COP, copiaba rider_id a user_id y aceptaba
aliases/identidades contradictorios. Faltaban límites estrictos, validación de
filtros, retiro de continuaciones de sesión y recuperación del detalle.

- Contrato explícito con los 18 tipos y estados reales, identidad exacta del
  detalle/UUID equivalente, aliases compatibles, dinero/fechas y páginas válidas.
  Se rechazan filtros inválidos y filas duplicadas o ajenas a la consulta.
- Navegación de 50 filas con una adicional como señal de siguiente página,
  filtros de tipo/estado en servidor y búsqueda local etiquetada. No se inventa
  total global. Error conserva página y consulta confirmadas; reintento fiel.
- CSV solo de coincidencias de la página, con filtro/offset/alcance explícitos,
  ceros, ausencias y signos originales. Bloqueado durante lectura/fallo pendiente.
  Se reutiliza el helper CSV seguro de la entrega 68, sin cambiarlo.
- Servicio/controladores y fronteras de acceso retiran respuestas de otra cuenta,
  ruta o lectura anterior. El detalle valida identidad y conserva el último
  registro ante un refresh fallido; reintentar es solo lectura. Impresión sujeta
  a identidad/sesión/lectura confirmadas, sin comunicar pago bancario.
- La moneda y fechas/saldos ausentes quedan desconocidos. Se muestra trazabilidad
  real. En auditoría de rider se adaptan esas filas y se reemplaza la suma de
  importes heterogéneos por cantidad de transacciones cargadas.

Contrato, límites y ejecución: [FINANCIAL_TRANSACTIONS.md](FINANCIAL_TRANSACTIONS.md).

## Validación nueva

**124 pruebas netas nuevas** frente a las 1351 de la base, en cinco suites nuevas
más la adaptación de la suite existente. Se cubren contrato, controlador, UI y
Axios/API real con adaptador en memoria; no se relajan pruebas de sesión.

| Control | Resultado local de esta entrega |
| --- | --- |
| Frontend completo con cobertura | **1475 aprobadas / 82 suites**, 28,094 s |
| Statements / ramas / funciones / líneas | 41,20 % / 39,00 % / 37,16 % / **40,03 %** |
| Gate global 50 % | Sigue fallando en las cuatro métricas; umbrales/exclusiones intactos |
| Normalizador y ambos controladores | 100 % de líneas |
| TypeScript y lint | Aprobados; advertencias existentes fuera de este bloque |
| Build con Inter real | Aprobado, 48 páginas; tipos/lint activos |
| Chromium sobre build local | **7 comprobaciones**, 12 lecturas, un CSV descargado/verificado; cero escrituras o excepciones pageerror |
| git diff --check | Aprobado |
| Backend | Sin cambios; no se atribuye una corrida backend local nueva |

Chromium comprueba las 50 filas y el lookahead oculto, página siguiente/offset,
búsqueda local sin otra lectura, contenido real del CSV parcial (cero, moneda y
saldo ausentes, fórmula neutralizada, UTC y contexto), filtros reales, error y
reintento, móvil, identidad errónea del detalle, impresión y respuestas tardías
tras cambiar de ruta o cerrar sesión. Se revisan capturas de escritorio y móvil.
HTTP/WebSocket de negocio se interceptan con datos sintéticos: esta evidencia no
sustituye E2E con backend/proveedores reales.

## Límites y siguiente prioridad

El orden por created_at y offset del backend no ofrece un snapshot ni desempate.
Se rechazan solapes adyacentes observables, sin prometer detectar todas las
omisiones. El CSV es expresamente parcial. El serializer no informa moneda ni
fecha de proceso y sustituye algunos NULL por cero antes del HTTP; el cliente no
puede recuperar esa información perdida. Los estados contables no certifican
transferencias. Dependencias, workflows, autorización backend y migraciones no
cambian.

La siguiente prioridad concreta es revisar las lecturas combinadas de auditoría
de rider: retiro por sesión/ruta, contratos y alcance de sus métricas/catálogos.
También quedan pendientes cursor estable/snapshot del ledger, gate global del
50 %, E2E con backend real y homologación sandbox de fase 7. No se envían pagos,
mensajes o facturas reales ni se ejecutan migraciones productivas, merge o deploy.
La publicación y el CI observado se registran por separado; no se declara el
sistema al 100 % de producción.

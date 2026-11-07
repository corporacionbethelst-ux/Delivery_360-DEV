# Entrega 68 — Reportes y CSV con filtros confirmados

Fecha: 7 de noviembre de 2026, America/Caracas.
Base: `759b7958aa44df56b2ffb043e36c9afdebe4f293` (PR #308 fusionado).
Rama: `fix/financial-report-snapshots-and-csv-v1`.

Checkout limpio al iniciar, sin AGENTS.md aplicable. Se conservan las ramas y el
historial anterior. El CI final de la entrega 67 aprobó backend y seguridad: las
1226 pruebas frontend y su build también aprobaron, con fallo solo del gate del
50 %. Esas comprobaciones remotas de la base no se atribuyen a esta entrega.

## Problemas confirmados y solución

El formulario de Reportes usaba directamente las fechas en edición para exportar,
sin asegurar que coincidieran con los datos visibles. Un export reemplazaba solo
órdenes, dejando la conciliación anterior. Los errores borraban el par, los campos
ausentes se convertían en ceros/USD, faltaban retiros de continuaciones de sesión
y los límites 1000/5000 podían aparentar un archivo completo. El helper CSV no
neutralizaba fórmulas de celdas de texto ni revocaba sus object URLs.

- Se valida el contrato real de ambos endpoints, manteniendo sus criterios de
  agregación distintos. Dinero/conteos, rangos/fechas base, estados, identidades y
  agregados contradictorios producen error. Los datos desconocidos no se inventan.
- El estado confirmado incluye rango, órdenes y conciliación como un único par.
  Un fallo conserva el par anterior. Editar fechas crea un borrador, sin cambiar
  cifras; se exige aplicarlo antes de exportar. Reintentar conserva el intento.
- La exportación vuelve a leer el rango confirmado con tope 5000 y comprueba que
  están todas sus filas. Un rango mayor o que crece entre lecturas no produce un
  CSV truncado. Los totales del rango y el tamaño de vista previa se distinguen.
- Lecturas anteriores y exportaciones retiradas no publican datos ni archivos.
  Cambiar fechas durante preparación, cuenta, rol, credenciales o desmontar retira
  esa continuación. Hay un guard síncrono contra doble export y se admite refresh
  verificado de la misma cuenta. Cada endpoint mantiene autorización en servidor.
- La UI diferencia órdenes en todos los estados de conciliación de entregas
  cobradas/ledger y retiros. No supone moneda para órdenes ni certifica pagos
  bancarios a partir de estados internos. Se muestran referencia e ID real.
- El CSV conserva importes cero, opcionales vacíos y fechas UTC. Escribe BOM UTF-8,
  CRLF y comillas/saltos de línea escapados; los textos potencialmente interpretables
  como fórmulas llevan apóstrofo. Los números negativos tipados se conservan. Se
  retiran enlaces y revocan URLs aun cuando falle la descarga.

Contrato y ejecución: [FINANCIAL_REPORTS.md](FINANCIAL_REPORTS.md).

## Validación nueva

Se añaden **125 pruebas frontend netas** sobre las 1226 de la base, en cinco suites
de contrato, CSV, controlador, UI e integración con Axios/API real y adaptador en
memoria. Se adapta la prueba de servicio anterior a los envelopes reales; no se
relajan validadores o pruebas de sesión.

| Control | Resultado local de esta entrega |
| --- | --- |
| Frontend completo con cobertura | **1351 aprobados / 77 suites**, 26,715 s |
| Statements / ramas / funciones / líneas | 39,75 % / 37,45 % / 35,61 % / **38,98 %** |
| Gate global 50 % | Sigue fallando en las cuatro métricas; sin cambiar umbrales/exclusiones |
| Página / controlador / normalizador / CSV | 100 % de líneas en las cuatro fuentes |
| TypeScript y lint | Aprobados; advertencias existentes fuera de Reportes |
| Build con Inter real | Aprobado, **48 páginas**, tipos/lint activos |
| Chromium sobre build local | **7 comprobaciones**, 14 lecturas de reportes, un CSV descargado y verificado; cero escrituras o excepciones pageerror |
| git diff --check | Aprobado |
| Backend | Sin cambios; no se atribuye una corrida backend local nueva |

Chromium comprueba fechas en borrador/aplicadas, fallo de conciliación durante
export, reintento, contenido CSV real, cancelación al editar, móvil y logout con
export pendiente. Se verifica un archivo de dos órdenes y 22 columnas, incluidos
cero, opcionales vacíos, IDs y rango, acentos/comillas/salto de línea y texto de
fórmula neutralizado. HTTP/WebSocket se interceptan con datos sintéticos; no se
conecta a una API de negocio. Se revisan capturas de escritorio y móvil.

El build conserva las verificaciones normales y la fuente Inter real, con workers
limitados por CIRCLE_NODE_TOTAL=3. Dependencias, workflows, umbrales, API/backend y
migraciones no cambian. El archivo y las capturas de navegador son evidencia local,
no prueba de integración contra datos o proveedores reales.

## Límites y siguiente prioridad

El par es atómico en la UI, sin prometer una transacción snapshot entre endpoints
o entre consultas internas del servidor. Se rechazan contradicciones observables;
la validación cliente no audita el ledger histórico. Los criterios temporales y
contables diferentes del backend se conservan y documentan. Algunos serializers
legacy todavía sustituyen NULL por cero antes de enviar HTTP.

La exportación completa admite hasta 5000 órdenes; se requiere acotar fechas para
rangos mayores. No se introduce paginación de exportación por offset sin garantías
de consistencia. El mensaje de descarga generada no confirma escritura en disco.
La hoja de cálculo puede aplicar conversiones de tipos al abrir un CSV.

La próxima prioridad concreta es aplicar contratos/confirmaciones equivalentes al
historial y detalle de transacciones financieras, que conservan adaptación parcial
y exportación de un lote. Siguen pendientes el gate del 50 %, E2E con backend real
y homologación sandbox de fase 7. No se envían pagos, mensajes o facturas reales,
no se ejecutan migraciones productivas ni se fusiona o despliega.

La publicación coteja commit/árbol y registra el PR y el CI observado por separado;
no se declara todo aprobado ni el sistema al 100 % para producción.

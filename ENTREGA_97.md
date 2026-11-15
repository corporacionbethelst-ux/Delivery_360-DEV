# Entrega 97 — reportes financieros exactos

Resumen y Reportes de gerencia consultan un nuevo snapshot decimal de precios,
movimientos contables y solicitudes de retiro, con cada fuente separada. El
frontend deja de calcular estas vistas con Float y no combina devengos/retiros
para inventar un margen. El precio de una orden no acredita cobro; la aprobación
de un retiro no acredita una transferencia bancaria.

## Continuidad

La entrega 96 fue fusionada por el propietario mediante PR338 en main,
`f5d8953dc1435020fa47982d8da7b5f2efeb2b7e`. La rama de la entrega 97 parte exactamente
de ese commit. Se preservan ramas, ZIP, bundle, parche, datos, documentos y
respaldos anteriores. No se fusiona el nuevo PR ni se despliega producción.

## Comportamiento

- GERENTE y SUPERADMIN leen `/api/v1/financial/reports/exact`. Se conservan los
  permisos previos de estas pantallas. AUDITOR mantiene su libro de clientes.
- Ventana de hasta 31 días del calendario Caracas; por defecto últimos 7 días.
  Fechas repetidas, desconocidas o inválidas se rechazan. Una sola sentencia
  PostgreSQL determina filas, reloj y visibilidad de las tres fuentes.
- Solo paquetes exactos de órdenes USD versión 1 aportan valor de órdenes.
  Float histórico, moneda no verificada y registros sin fecha quedan excluidos
  e identificados, sin reetiquetarlos ni rellenar importes ficticios.
- El libro `financials` usa sus direcciones canónicas, estados procesados y
  ajuste con signo. No se mezcla con el libro de wallets en centavos, los cobros
  de clientes ni las solicitudes de retiro. Un retiro registrado como débito no
  vuelve a restarse. El neto del período puede ser negativo.
- Las solicitudes se agrupan por fecha de creación y estado actual. Los precios
  y estados se observan al consultar; no reconstruyen un cierre histórico.
- Hasta 5.000 registros completos entre las tres fuentes. Un rango mayor devuelve
  409. CSV incluye todas las filas y exclusiones, corte, conteos y huella del
  contenido del snapshot cargado, sin una segunda lectura ni truncamiento.
- La tabla pagina a 50 filas. Su selector de fuente no limita el CSV. Cambiar
  fechas o sesión invalida resultados anteriores. Los errores no se presentan
  como cifras cero. Ambas pantallas usan un diseño colorido y adaptable.

No se requiere migración de base. La consulta no modifica saldos, órdenes,
retiros ni historia. Las rutas numéricas anteriores continúan por compatibilidad
con consumidores previos; estas pantallas ya no las usan.

## Comprobación

Pruebas PostgreSQL: precios exactos, signos canónicos, exclusión de datos sin
unidad, solicitudes separadas, cero real, fuentes incoherentes, límite completo,
permisos y escritura concurrente sin mezclar snapshots. Se ajustó el fixture de
la entrega 96: su ventana congelada al 14 de noviembre perdía registros creados
por otro fixture con el día real. Ahora ambos siguen el calendario real.

Pruebas frontend: contrato contra fixture sintético de la API real, agregados
recalculados desde todas las filas con BigInt, fechas, CSV, errores, cambio de
cuenta/rol, refresh de la misma cuenta y respuestas fuera de orden. Las pruebas
anteriores de las pantallas se adaptan al nuevo contrato; los clientes legacy
conservan sus propias pruebas de compatibilidad.

El recorrido de Chromium valida ambas pantallas y CSV reales, móvil, errores y
permisos. El laboratorio conserva un respaldo previo, hashes de 14 tablas y
hashes de todos los documentos. Los resultados finales y CI del commit se
registran en los artefactos de entrega.

## Pendientes

Conciliación automática con Banco de Venezuela, Banesco, Provincial, Mercantil
y BOD: requiere canales oficiales, acceso y homologación; se verificará la
entidad operativa actual de BOD. Continúan la revisión explícita de monedas
históricas, migración de consumidores de reportes numéricos legacy, liquidación
VES de riders con BCV conservado y los demás puntos de PRODUCCION_PENDIENTES.md.

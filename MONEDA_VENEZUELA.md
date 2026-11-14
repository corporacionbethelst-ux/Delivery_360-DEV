# Moneda en Venezuela — referencias BCV y operaciones USD

Decisión de negocio: Venezuela, base USD y equivalente en bolívares con BCV.
La entrega 90 cubre referencias y cotizaciones independientes. La entrega 91
identifica nuevas operaciones USD y separa el historial sin moneda; no convierte
importes anteriores ni confirma transferencias.

## Operaciones USD de la entrega 91

Las nuevas órdenes, ganancias del libro `financials`, solicitudes de retiro y
sus nuevos eventos declaran USD. Los saldos y reservas USD consultan únicamente
filas con esa denominación. Una cadena USD comienza en cero; no incorpora el
saldo de una cadena anterior cuya moneda no pueda verificarse. El otro libro de
wallets en centavos conserva sus registros y no se suma al saldo de `financials`.

La migración `20261114_explicit_usd` añade columnas de moneda **nullable y sin
DEFAULT de base de datos** en órdenes, movimientos, retiros, historial de retiros
y caché de repartidor. No ejecuta UPDATE sobre las filas anteriores: quedan con
moneda null. Las escrituras nuevas de la aplicación declaran USD. Escritores
antiguos que omitan la columna dejan filas sin verificar; no se importan al saldo
USD. Las restricciones aceptan USD o null y los triggers impiden reetiquetar una
fila confirmada, incluso de null a USD. La revisión histórica requiere un proceso
explícito futuro; no se resuelve cambiando etiquetas o usando la tasa actual.

`GET /api/v1/payouts/balance` declara USD y añade los conteos
`unverified_financial_count` y `unverified_payout_count`. Los retiros, sus eventos,
las transacciones y las órdenes devuelven su moneda o null. Los reportes de USD
excluyen filas sin denominación; el historial sigue consultable en Transacciones
y Pagos. Las métricas monetarias de la página de pagos suman solo retiros USD.

Una solicitud de retiro acepta `currency: "USD"` (valor por defecto del contrato)
y rechaza COP/VES u otras unidades. Una reserva histórica sin moneda no consume
el saldo USD ni puede aprobarse debitándolo. Se puede rechazar conservando sus
snapshots originales; el nuevo evento histórico no inventa un saldo USD. Las
conciliaciones no sobrescriben cachés cuya moneda carezca de verificación.

La pantalla de ganancias requiere saldo y totales USD confirmados por el servidor:
no reconstruye disponibilidad desde un resumen ni transforma un fallo de consulta
en saldo cero. Los movimientos sin moneda se muestran como tales. Una aprobación
EN_PROCESO es un registro contable, sin confirmación bancaria. El resumen cuenta
solo ganancias registradas: una orden entregada sin asiento no es evidencia de bono.

El formulario de orden mantiene su estructura y colores; sus precios nuevos se
identifican en USD. El historial muestra la moneda recibida, sin asumir dólares.
Se bloquea la edición de importes de una orden sin unidad verificable. El detalle
del operador muestra subtotal y envío registrados, sin inventar una distribución
85/15 ni impuestos. El almacenamiento Float de importes de órdenes sigue pendiente
de una migración decimal revisada; los asientos y retiros usan Numeric con centavos.

La tasa BCV se conserva en los comprobantes de cotización del bloque siguiente.
Este incremento no liquida un retiro en VES ni enlaza un comprobante a un pago
bancario. Sigue pendiente elegir el proveedor, conservar el cambio realmente
aplicado en el pago y conciliar su confirmación externa. La emisión fiscal existente
para Colombia/México no homologa Venezuela ni demuestra conversión válida de USD;
no está habilitada en el laboratorio de esta operación.

## Precios exactos de órdenes — entrega 92

Las órdenes nuevas guardan un paquete de precio versión 1: `subtotal_exact`,
`delivery_fee_exact` y `total_exact` son `NUMERIC(10,2)`; `items_exact` conserva
cantidades y precios como cadenas decimales. La respuesta añade `pricing` con
`version`, `currency: USD`, `revision`, `items`, `subtotal`, `delivery_fee` y
`total`. Los importes son cadenas con dos decimales. Las cantidades positivas
admiten hasta tres decimales; cada línea usa HALF_UP a centavos, luego se suman
las líneas y el envío. Por ejemplo, 3 × 0,10 + 0,20 = 0,50 USD. Cero es un valor
explícito válido, no una señal para buscar un importe alternativo.

Se admiten hasta 200 líneas e importes de hasta 99.999.999,99 USD por orden.
Se rechazan exponentes, booleanos, valores negativos/no finitos, exceso de
precisión y totales que no coincidan. Una línea de cargo puede declarar solo su
subtotal; la API también permite una base y envío explícitos sin productos.
El formulario exige productos completos y usa centavos enteros para calcular;
conserva el texto del usuario y muestra «Por confirmar» si el precio es inválido.
Los campos numéricos anteriores son espejos de compatibilidad para lectores
existentes y no son la fuente para calcular precios nuevos.

Una modificación monetaria de un paquete exacto exige
`expected_pricing_revision`. Un precio diferente aumenta la revisión; repetir
el mismo paquete conserva su revisión. Una edición con revisión obsoleta o
faltante devuelve 412 sin cambios parciales. El formulario conserva su borrador
y explica que debe revisarse la versión actual. La actualización bloquea la
orden en PostgreSQL y vuelve a comprobar la sesión y el rol después de esperar.
Cambiar direcciones o referencias sin tocar precios conserva el paquete.

La migración `20261114_order_exact_prices` añade seis columnas nullable sin
DEFAULT ni UPDATE del historial. Los importes Float anteriores no se convierten
ni redondean durante la migración. Una orden USD histórica solo obtiene un
paquete exacto mediante revisión explícita del precio completo (productos o
base, más envío); una orden sin moneda sigue bloqueada para cambios monetarios.
En la edición de un precio histórico el envío se deja sin confirmar para exigir
esa revisión. Los triggers comprueban paquete, aritmética, espejos y revisiones,
e impiden eliminar la versión exacta de una orden ya confirmada.

Resumen, reporte de órdenes y conciliación añaden `exact_order_pricing`: suma
SQL decimal del subconjunto exacto USD y conteo separado de órdenes USD antiguas.
La UI presenta ese subconjunto en una tarjeta propia. Los indicadores generales
y CSV anteriores mantienen su contrato numérico y criterio contable; todavía
no representan una migración completa de todos los reportes a decimales.
Facturación y reparto interno usan los importes exactos cuando existen. Esta
entrega no habilita liquidación VES, facturación fiscal venezolana ni un banco.

Para desplegar hay que respaldar, aplicar la migración y coordinar el reemplazo
de todos los escritores monetarios. Un proceso antiguo que intente cambiar los
espejos Float de una orden exacta será rechazado por PostgreSQL. La reversión de
la migración se niega cuando ya hay paquetes exactos; no elimina precios para
forzar un downgrade. La entrega solo aplica la migración al laboratorio marcado.

`tests/test_order_pricing_exact.py` verifica cálculo y PostgreSQL real, incluyendo
concurrencia y revocación durante una espera de bloqueo. El runner
`frontend/e2e/local-order-pricing.browser.py` comprueba creación, recarga, revisión,
conflicto 412, borrador, rechazo de total alterado y diseño móvil contra API real.
Exige el marcador del laboratorio antes de escribir y usa cuentas sintéticas.

## Cotización ligada a la orden — entrega 93

El detalle de una orden incorpora una tarjeta USD/Bolívares con revisión previa,
importe exacto y referencia BCV del día de Caracas. El operador no escribe otro
importe: el servidor obtiene el total del paquete exacto de la orden y conserva
su revisión, artículos, subtotales y referencia externa junto con la tasa aplicada.
El equivalente VES se calcula con Decimal/HALF_UP en el servidor y centavos enteros
en el navegador. Cero conserva su significado. La tarjeta mantiene los colores y
la estructura del detalle; las acciones de asignación conservan su posición.

Nuevos endpoints (los de cotización independiente permanecen iguales):

- `GET /api/v1/currency/orders/{order_id}/quotes`: precio actual, referencia
  actual y últimos diez comprobantes visibles, con `has_more`.
- `POST /api/v1/currency/orders/{order_id}/quotes`: acepta exclusivamente
  `request_key` UUID, `rate_id` UUID y `expected_pricing_revision` entero positivo.
  No admite un importe, moneda ni snapshot proporcionados por el cliente.
- `GET /api/v1/currency/order-quotes/{quote_id}`: recupera un comprobante
  conservado. El enlace del detalle usa `?bcv_quote=UUID` y permite recargarlo
  incluso cuando ya no está entre los diez documentos recientes.

La respuesta declara `scope: order_quotation_only`, `quotation_only: true` y
`payment_confirmed: false`. Guardar una cotización no registra un cobro, reserva,
retiro, factura o transferencia. El precio de la orden sigue en USD. La nueva
tabla `order_currency_quotes` guarda el precio completo como cadenas, importes
NUMERIC, tasa enlazada, cuenta responsable, fecha UTC y clave de solicitud.

Solo se crea un comprobante con un precio exacto USD y una orden cuyo estado
no sea cancelado o fallido. Los precios históricos sin paquete exacto o moneda
verificada requieren revisión previa; no se convierten en esta operación.
Un precio o referencia desactualizados causan 412; falta de tasa actual, cambio
de día o una orden no apta causan 409. Orden, usuario y referencia del día se
coordinan mediante bloqueos. Se vuelven a comprobar sesión y rol después de
esperar por la orden. El comprobante y su auditoría se confirman juntos.

Repetir la misma clave, cuenta, orden, tasa y revisión recupera el mismo documento,
incluso después de cambios de precio, tasa, estado o día. Reutilizarla con otro
contenido o cuenta da 409. El navegador conserva la solicitud tras un resultado
ambiguo y permite reintentar o cerrar la revisión sin descartar esa recuperación.
Un rechazo definitivo exige volver a revisar los valores actuales.

La consulta muestra el precio actual separado del documento histórico y avisa
cuando sus revisiones difieren. La corrección de la tasa o del precio no recalcula
los comprobantes anteriores. Superadministrador, gerente y operador pueden crear;
auditor solo consulta. Cada operador consulta únicamente sus propios comprobantes;
gerente, superadministrador y auditor pueden consultarlos para su función.

La migración `20261114_order_bcv_quotes` crea una tabla nueva sin UPDATE del
historial. Sus triggers verifican el snapshot contra el precio bloqueado, tasa
vigente, día y conversión, y rechazan UPDATE, DELETE y TRUNCATE. Las claves
foráneas conservan orden, referencia y responsable. El downgrade se niega si ya
existen comprobantes. La migración se prueba y aplica únicamente al laboratorio.

Continúan pendientes el registro de cobros efectivamente verificados, abonos
parciales/devoluciones y conciliación con el proveedor/banco seleccionado. No se
habilita una liquidación VES ni fiscalidad venezolana por guardar este documento.

## Uso

En el menú **USD / Bolívares**, gerencia y superadministración registran una
referencia después de consultar BCV. Deben indicar bolívares por dólar, fecha de
la publicación, nota y confirmación explícita. El diálogo permite revisar y
cancelar antes de escribir. Operadores pueden cotizar; no registrar tasas.

El día de uso procede del servidor en `America/Caracas`. Solo se crean nuevas
cotizaciones con una referencia registrada para ese día. En días sin publicación,
una persona autorizada debe comprobar la vigencia de la referencia anterior y
justificarla con una nota de al menos diez caracteres. No hay arrastre automático.

La pantalla admite coma o punto decimal, sin separadores de miles. Al guardar
una cotización, su enlace `?quote=<UUID>` permite recuperar el mismo comprobante
con autenticación. El operador solo recupera los que creó; gerencia,
superadministración y auditoría pueden consultar comprobantes por API. Esta
entrega no añade un portal de auditoría nuevo.

**El origen es manual (`MANUAL_BCV`, `automatically_verified: false`).** No se
presenta como una consulta oficial automática. El acceso HTTPS público al BCV
respondió 503 durante el desarrollo; no se desactivó TLS. El operador debe
consultar y validar la publicación oficial por un medio disponible. El sistema
no puede comprobar por sí mismo que el valor escrito coincide con ella.

## Contrato de API

Todas las rutas requieren sesión vigente y rol autorizado.

| Ruta | Función | Roles |
| --- | --- | --- |
| `GET /api/v1/currency/context` | Día, referencia actual e historial de 20 registros | SUPERADMIN, GERENTE, OPERADOR, AUDITOR |
| `POST /api/v1/currency/rates` | Añadir referencia o corrección | SUPERADMIN, GERENTE |
| `POST /api/v1/currency/quotes` | Conservar cotización | SUPERADMIN, GERENTE, OPERADOR |
| `GET /api/v1/currency/quotes/{id}` | Recuperar comprobante | Consulta; OPERADOR solo propio |

Para registrar una referencia se envían `request_key` UUID, `previous_rate_id`
(UUID de la referencia actual del día, o null), `valid_on`, `reference_date`,
`ves_per_usd` como cadena decimal positiva, `note` y `confirmed_bcv: true`.
Se admiten hasta ocho decimales y nueve cifras enteras en la tasa.

Para cotizar se envían `request_key`, `rate_id`, `amount_usd` como cadena decimal
no negativa de hasta doce cifras enteras y dos decimales, y `reference` de hasta
120 caracteres. Los importes y tasas de respuesta también son cadenas; no se
deben convertir a coma flotante para calcular. El equivalente VES usa HALF_UP a
dos decimales. Por ejemplo, 0,01 USD a una tasa **sintética** 1,5 produce 0,02 VES.

Una revisión anterior causa 412; la UI conserva el borrador y pide actualizar.
Sin referencia del día o ante cambio de fecha durante una escritura se devuelve
409. Repetir la misma clave, cuenta y contenido recupera el mismo registro,
incluso si su día ya terminó. Reutilizar la clave con contenido o cuenta distintos
devuelve 409. El navegador conserva la clave mientras reintenta una operación
sin respuesta concluyente. La concurrencia usa bloqueos transaccionales en
PostgreSQL; el registro y su auditoría se confirman juntos.

Los comprobantes indican `quotation_only: true` y `payment_confirmed: false`.
El contexto indica `scope: "quotation_only"`. Ninguno reserva fondos, modifica
saldos ni acredita transferencias. La conversión genérica heredada rechaza VES
y monedas desconocidas: no puede fabricar una equivalencia 1:1 para estos casos.

## Persistencia y migración

Alembic `20261114_bcv_currency`, después de `20261113_runtime_schema`, crea
`bcv_rates` y `usd_ves_quotes`, sus restricciones y protecciones de historial.
No modifica los importes de tablas anteriores. Las revisiones enlazan la
referencia anterior y los comprobantes conservan la referencia aplicada.
No se edita o borra un registro confirmado. La reversión de esta migración se
niega si las tablas contienen datos; no elimina historia para forzar un downgrade.

La migración se comprueba en bases de prueba independientes y en el laboratorio
marcado. Aplicarla a producción requiere el proceso de despliegue autorizado,
respaldo y validación de compatibilidad. Esta entrega no la ejecuta allí.

## Prueba real de laboratorio

Tras `python scripts/local_test.py up`, instala Playwright y usa Chromium local:

```bash
python frontend/e2e/local-currency.browser.py --artifacts-dir browser-real/currency
```

El ejecutor exige el marcador de la base dedicada y que la identidad HTTP coincida
con ella antes de escribir. Usa tasas etiquetadas como **datos sintéticos**, sin
consultar bancos o enviar mensajes. Comprueba cancelación, precisión, revisiones,
recuperación al recargar, reintentos, conflictos, permisos y vista móvil. Compara
conteos y hashes de órdenes, contabilidad, retiros y configuración antes y después.
Conserva referencias y comprobantes de prueba; no los borra para simular limpieza.

En CI se ejecuta después de los recorridos funcionales anteriores, respetando la
ventana real de cinco logins por minuto mediante `--wait-auth-window`. Los casos
PostgreSQL automatizados utilizan una base `test_*` explícita y esquemas propios.

Siguen pendientes la revisión de moneda histórica, la migración decimal de órdenes,
la aplicación de BCV a liquidaciones VES reales, automatizar BCV con disponibilidad
y trazabilidad verificables y elegir/homologar pagos y facturación venezolana.

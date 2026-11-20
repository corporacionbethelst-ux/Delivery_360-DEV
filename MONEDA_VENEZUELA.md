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

El bloque de cobros de la entrega 94 utiliza estas cotizaciones para conservar
el cambio acordado. Las cotizaciones siguen sin confirmar pagos por sí solas.

## Cobros de clientes y revisión independiente — entrega 94

Medios confirmados: **efectivo USD/VES, transferencia USD/VES y pago móvil VES**.
El detalle de la orden permite declarar un abono USD y el importe realmente
recibido. Se revisan los importes antes de guardar y se confirma explícitamente
la recepción. El registro nace PENDIENTE: reserva capacidad, pero no suma al
importe verificado. Un gerente o superadministrador distinto del declarante
comprueba el efectivo o ingreso en cuenta y verifica o rechaza con una nota.
La decisión es final y conserva la declaración; corregir un rechazo requiere
una declaración nueva. No hay consulta o confirmación automática de un banco.

El importe recibido USD debe coincidir con el abono USD. Un cobro VES exige una
cotización de la misma orden, revisión de precio y día de Caracas; el importe
recibido debe ser exactamente el abono USD × la tasa conservada, con HALF_UP a
centavos. Una corrección posterior de BCV no revaloriza el pago acordado. En este
primer bloque se declaran recepciones del día; no se inventan tasas para pagos
anteriores ni se deducen dólares dividiendo bolívares redondeados.

Se indica un alias interno de caja/cuenta y la referencia completa del recibo o
transferencia. La combinación es única entre todos los cobros pendientes o
verificados, incluso de distintas órdenes, fechas o medios. No se deben introducir
números de cuenta ni datos personales bancarios. Un rechazo libera capacidad y
permite corregir la referencia con otra declaración, preservando la anterior.

El resumen muestra USD pendientes, verificados y por cobrar. La capacidad de
nuevos abonos resta también los pendientes, para evitar reservas duplicadas.
El precio exacto se congela mientras exista un pendiente o verificado: se pueden
actualizar direcciones y prioridad según el estado operativo. La protección
existe en la API y PostgreSQL. No se actualiza el `payment_status` heredado ni los
libros de bonos, wallets y retiros del repartidor; el resumen de este panel es
la fuente de este nuevo libro de cobros de clientes.

Una orden cancelada o fallida no admite declaraciones nuevas. Si ya hay un
importe verificado, se expone como devolución pendiente, sin ejecutar una salida
de dinero. Verificar un pendiente de esa orden exige reconocer esa obligación.
La entrega 95 añade autorización, declaración y conciliación manual de
devoluciones. La conciliación bancaria automática y la liquidación VES de
repartidores siguen pendientes.

| Ruta | Función | Roles |
| --- | --- | --- |
| `GET /api/v1/customer-collections/orders/{order_id}` | Resumen global, últimos 20 registros visibles y cotizaciones VES elegibles | SUPERADMIN, GERENTE, OPERADOR, AUDITOR |
| `POST /api/v1/customer-collections/orders/{order_id}` | Declarar abono recibido | SUPERADMIN, GERENTE, OPERADOR |
| `POST /api/v1/customer-collections/{collection_id}/review` | Verificar o rechazar con evidencia y nota | SUPERADMIN, GERENTE; distinto del declarante |
| `GET /api/v1/customer-collections/{collection_id}` | Recuperar declaración y decisión conservadas | Consulta; OPERADOR solo propio |

El contexto agrega todos los abonos de la orden; un operador solo ve sus propias
declaraciones y cotizaciones. Gerencia y auditoría consultan el conjunto. El enlace
`?customer_collection=UUID` recupera un registro aunque haya salido de la lista
reciente. Cada nueva declaración exige revisiones esperadas de precio y cobros;
la revisión exige la revisión de cobros. Un cambio concurrente devuelve 412.
Repetir la misma clave y contenido recupera el registro ya confirmado, incluso
si cambió el día o la orden se canceló; otro contenido con esa clave causa 409.
El navegador conserva la solicitud ante una respuesta ambigua para reintentar.

La migración `20261114_customer_collections`, después de las cotizaciones de
orden, añade dos tablas inmutables y dos columnas nullable sin DEFAULT a órdenes:
`collection_revision` y `collection_locked`. No reescribe filas anteriores.
Triggers verifican snapshot, conversión, referencia, capacidad e independencia;
calculan el estado de cobros y bloquean su falsificación y los cambios de precio.
Declaración/decisión, contadores y auditoría se confirman en la misma transacción.
UPDATE, DELETE y TRUNCATE se rechazan; el downgrade se niega si existe historial.
La migración solo se aplica al laboratorio marcado durante esta entrega.

Las pruebas `test_customer_collections_postgresql.py` y
`frontend/e2e/local-customer-collections.browser.py` cubren el libro real y la UI
con dos cuentas independientes. No se envía dinero, mensajes ni datos a bancos.

## Devoluciones y conciliación manual — entrega 95

Regla confirmada por el usuario: **devolver en la misma moneda y con la tasa BCV
conservada del cobro original**. No se usa la referencia del día de devolución
ni una corrección posterior para revalorizar lo recibido. Se admiten devoluciones
parciales o totales de un cobro ya verificado, cuando la orden esté cancelada o
fallida. Las solicitudes conservan el cobro original, motivo, solicitante,
importe USD, moneda de salida y prefijo de devoluciones ya verificadas.

El flujo diferencia estados que no deben confundirse:

1. SOLICITADA: reserva el importe; no registra una salida.
2. APROBADA: otro gerente o superadministrador autoriza; el dinero sigue pendiente.
3. EJECUCION_DECLARADA: un responsable registra una salida ya realizada fuera
   del sistema, con importe exacto aprobado, medio, fecha de Caracas, alias de
   caja/cuenta y referencia única. Requiere confirmación explícita.
4. DEVUELTA: otro responsable distinto del ejecutor comprueba la evidencia.
   Solo este evento reduce el saldo pendiente de devolución.

Una OBSERVADA conserva la reserva y bloquea otro intento. Otro responsable puede
verificar la salida tras aclararla o confirmar con evidencia que no hubo salida;
esta última decisión retorna a APROBADA y permite declarar otro intento con una
referencia nueva. Nunca se reutiliza la referencia de un intento anterior. Se
puede rechazar una solicitud antes de aprobarla, o anular una aprobación con
comprobación expresa de que no hubo ejecución; ambas decisiones liberan la
reserva. Solicitar y revisar la propia autorización está prohibido. Un ejecutor
no puede verificar, observar ni confirmar la no ejecución de su propia salida.

Hay una sola solicitud sin resolver por cobro. Esto evita pagos simultáneos y
permite conservar un prefijo exacto de importes ya devueltos. Cada parcial en
VES se calcula como la diferencia entre convertir el acumulado nuevo y los VES
previamente verificados. Ejemplo sintético: un cobro de 0,50 USD a 1,5 conserva
0,75 VES. Parciales de 0,01 + 0,01 + 0,48 USD devuelven 0,02 + 0,01 + 0,72 VES.
Se conservan exactamente los 0,75 VES originales; no se redondea cada parcial de
forma independiente. Se rechaza un parcial que no alcance un centavo de salida.

El panel de devoluciones aparece en el detalle de órdenes canceladas o fallidas,
a ancho completo y adaptable a móvil. Muestra saldo pendiente, importe en trámite
y total devuelto verificado. Cada acción exige revisar el importe y motivo antes
de guardar. Los reintentos conservan la misma solicitud tras respuestas ambiguas;
`?refund=UUID` recupera el historial aunque salga de las veinte solicitudes recientes.
Los eventos anteriores se consultan por páginas de cincuenta, sin perder historia.

El resumen anterior de cobros conserva sus importes **brutos**. Su clave heredada
`refund_due_usd` se identifica con `refund_due_scope: gross_verified_collections`;
no representa el saldo neto después de devoluciones. La UI actual lo explica y
remite a Devoluciones de clientes. El neto procede exclusivamente de
`GET /api/v1/customer-refunds/orders/{order_id}` y su `summary.remaining_usd`.
Se deben actualizar API y frontend de forma coordinada; clientes anteriores no
conocen este nuevo libro. Los bonos, wallets, retiros y payment_status heredado
conservan sus contratos y registros.

| Ruta | Función | Roles |
| --- | --- | --- |
| `GET /api/v1/customer-refunds/orders/{order_id}` | Resumen neto, cobros y últimas 20 solicitudes visibles | SUPERADMIN, GERENTE, OPERADOR, AUDITOR |
| `POST /api/v1/customer-refunds/orders/{order_id}` | Solicitar devolución con revisión esperada del libro | SUPERADMIN, GERENTE, OPERADOR |
| `GET /api/v1/customer-refunds/{refund_id}` | Recuperar solicitud e historial reciente | Consulta; OPERADOR solo sus cobros/solicitudes |
| `GET /api/v1/customer-refunds/{refund_id}/events?before_revision=N` | Recuperar eventos anteriores | Mismos permisos de consulta |
| `POST /api/v1/customer-refunds/{refund_id}/events` | Autorizar, declarar o conciliar manualmente | SUPERADMIN, GERENTE, con independencia por acción |

Las escrituras tienen claves UUID idempotentes y revisiones esperadas. Una
solicitud compara la revisión global del libro de la orden; las acciones comparan
la revisión del historial de esa devolución. El importe real declarado debe
coincidir con la moneda y los centavos aprobados. Solo se declaran salidas del
día actual de Caracas; la revisión puede ocurrir después. Los operadores ven
los cobros que declararon y sus devoluciones; el resumen agrega toda la orden.
Auditoría es de solo lectura. Las respuestas indican `bank_verified: false` y
el contexto `bank_integration_available: false`.

La migración `20261114_customer_refunds` crea dos tablas, sin columnas nuevas en
los libros anteriores ni UPDATE de historia. Los triggers comprueban importe,
prefijo acumulado, moneda y BCV originales, estado, revisión, roles activos e
independencia. También impiden reabrir una orden con devoluciones en curso o ya
verificadas. Las referencias de ejecución son únicas, incluso en intentos luego
observados. Solicitud/evento y auditoría se confirman en la misma transacción.
UPDATE, DELETE y TRUNCATE se rechazan; el downgrade poblado se niega.

Las comprobaciones SQL están en `tests/test_customer_refunds_postgresql.py`.
El runner `frontend/e2e/local-customer-refunds.browser.py` usa dos cuentas reales,
datos sintéticos y el marcador del laboratorio. Conserva cobros, eventos y datos
anteriores, sin llamadas a bancos, transferencias reales ni mensajes. Sigue
pendiente elegir el proveedor/banco y conciliar automáticamente su confirmación.

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

Siguen pendientes la revisión de moneda histórica, el cierre decimal de reportes,
la aplicación de BCV a liquidaciones VES reales, automatizar BCV con disponibilidad
y trazabilidad verificables y elegir/homologar pagos y facturación venezolana.


## Libro exacto de cobros y devoluciones — entrega 96

`GET /api/v1/customer-cashbook/report` y la pantalla
`/manager/financial/customer-cashbook` admiten SUPERADMIN, GERENTE y AUDITOR.
Solo leen cobros con revisión VERIFICADO y eventos VERIFICAR_DEVOLUCION;
solicitudes, aprobaciones y ejecuciones todavía no verificadas quedan fuera.
El reconocimiento corresponde a la fecha de verificación manual, no a la fecha
de la orden o la solicitud. Los documentos originales conservan sus fechas.

Filtros opcionales: `date_from`, `date_to` (YYYY-MM-DD, calendario Caracas),
`method` (EFECTIVO/TRANSFERENCIA/PAGO_MOVIL), `currency` (USD/VES) y `source_key`
(alias exacto normalizado). Sin fechas se consultan los últimos siete días.
El máximo es 31 días, con final no posterior a hoy en Caracas. Los límites UTC
son medianoche local inclusiva y medianoche siguiente exclusiva. Se rechazan
filtros desconocidos o repetidos. La operación es exclusivamente GET.

Una sola sentencia PostgreSQL determina filas y momento de lectura. Totales,
desglose diario, monedas, medios y CSV proceden de esas mismas filas. La prueba
de concurrencia verifica que una devolución confirmada durante la lectura no
mezcla filas anteriores con totales posteriores. Los importes viajan como
cadenas decimales; servidor Decimal y navegador BigInt conservan centavos.
El neto de un período puede ser negativo por devoluciones de cobros anteriores.
Los originales USD y VES nunca se suman como una misma unidad.

Cada devolución conserva la tasa del cobro original y la asignación acumulada
de centavos. El detalle incluye IDs del cobro, devolución, orden y verificación,
responsables distintos, fechas, alias/referencia y BCV original. Se valida la
ejecución vinculada a la última declaración anterior a la verificación, también
cuando hubo observación y reintento. Un origen incoherente produce 409.

Hasta 5.000 movimientos se reciben completos y se paginan visualmente a 50.
Si el rango supera el límite, la API responde 409 y pide acotarlo: no entrega
CSV parcial. Editar filtros descarta las cifras anteriores e impide exportarlas
hasta aplicar la nueva consulta. El CSV incluye todas las filas, rango, hora,
conteo y huella SHA256 del snapshot; esta huella identifica contenido y no es
una firma bancaria. También permite exportar un período confirmado vacío con
sus metadatos. El cambio de sesión invalida solicitudes privadas en curso.

La migración `20261115_cashbook_indexes`, sucesora de devoluciones, crea dos
índices parciales por fecha de verificación; no transforma filas ni importa
saldos. Su downgrade solo elimina esos índices, incluso con datos presentes.
El libro de clientes es independiente de ganancias/retiros de riders y de los
indicadores Float heredados. Este bloque no cierra todos los reportes antiguos.

Bancos confirmados por el usuario: Banco de Venezuela, Banesco, Provincial,
Mercantil y BOD. La conciliación automática sigue pendiente de canales
oficiales, credenciales y homologación. Se verificará la entidad operativa
actual de BOD antes de diseñar un adaptador. Ningún alias histórico se interpreta
como banco ni una verificación manual se presenta como confirmación externa.

## Reportes gerenciales exactos — entrega 97

Las pantallas **Finanzas → Resumen** y **Finanzas → Reportes** utilizan
`GET /api/v1/financial/reports/exact`, con acceso de GERENTE y SUPERADMIN.
La consulta devuelve un único snapshot de tres fuentes separadas:

- **Órdenes:** paquetes de precio versión 1 en USD, con subtotal, envío y total
  NUMERIC. Las órdenes con precio Float anterior quedan identificadas como
  excluidas; no se convierten ni copian importes aproximados. Su valor no
  acredita un cobro. Incluye todos los estados, con desglose explícito.
- **Movimientos:** `financials` en USD con estado PROCESADO/PAGADO y tipos del
  libro canónico. Los créditos usan magnitud positiva, los débitos negativa y
  AJUSTE conserva signo. AJUSTE_MANUAL sigue siendo débito, según el servicio
  existente. El cambio del período no es un saldo disponible ni un costo global.
- **Retiros:** solicitudes USD creadas en el rango, agrupadas por su estado al
  consultar. Pendientes, aprobadas, en proceso, completadas, rechazadas y fallidas
  se presentan por separado. No se restan otra vez de los movimientos ni se
  interpretan como transferencias bancarias confirmadas.

El rango usa la fecha de creación de cada fuente; en órdenes, `ordered_at` es
el respaldo si falta `created_at`. Los precios y estados son los observados al
consultar. No reconstruye un cierre histórico, una utilidad o un estado bancario.
Los cobros y devoluciones verificados conservan su libro independiente de la
entrega 96, enlazado desde ambas pantallas. El libro de wallets en centavos no
se incorpora al de `financials`.

Los filtros `date_from` y `date_to` admiten fechas YYYY-MM-DD de Caracas, hasta
hoy y con máximo 31 días. Sin filtros se usan los últimos siete días. Una sola
sentencia PostgreSQL reúne filas, reloj y visibilidad de las tres fuentes.
Los importes viajan como cadenas; servidor Decimal y navegador BigInt validan
centavos, direcciones y totales. Un origen monetario incoherente produce 409.

Los registros sin fecha aparecen como excluidos en cualquier rango, sin
asignarles un día ficticio. La moneda no verificada, los precios anteriores,
los movimientos no procesados y los tipos/estados no admitidos también se
identifican, con conteos y detalle. Cada fila tiene una sola razón principal de
exclusión; sus importes no se suman ni se muestran como USD.

Hasta 5.000 registros entre las tres fuentes se reciben completos. Superar el
límite responde 409 y no permite descargar un CSV parcial. La tabla pagina a
50 filas; elegir una fuente solo cambia la vista. El CSV conserva todas las
fuentes y exclusiones del snapshot cargado, sin una segunda consulta, junto a
rango, corte, conteos y huella SHA256. Un rango confirmado vacío puede exportar
metadatos. Cambiar fechas o sesión invalida lecturas anteriores.

La entrega es de solo lectura y no necesita migración de tablas ni reescribe
historial. Las rutas numéricas anteriores de resumen/reporte/conciliación se
conservan para compatibilidad con clientes previos; estas dos pantallas ya no
las consultan. Su retirada exige migrar a esos consumidores. Tampoco se completa
la revisión de moneda histórica ni la conciliación bancaria automática.

## Ganancias exactas del repartidor — entrega 98

Inicio, Productividad y Mis Ganancias del repartidor consultan ahora
`GET /api/v1/financial/riders/me/report`. El servidor toma la identidad de la
sesión; no acepta seleccionar `rider_id` o `user_id`. Devuelve un snapshot
completo de sus movimientos, totales históricos, créditos de hoy y de los últimos
siete días en Caracas, más exclusiones y detalle exportable. Una sola sentencia
PostgreSQL proporciona filas, propietario y corte. Hasta 10.000 movimientos;
superar el límite produce 409, sin cifras ni CSV parciales.

Solo Financial en USD y PROCESADO/PAGADO aporta cifras, con las direcciones
canónicas de créditos, débitos y ajuste con signo. Una orden ENTREGADA sin asiento
no acredita ganancias; tampoco se usa su precio o valor a cobrar como bono. Se
retira ese cálculo del inicio, incluyendo el fallback que mostraba el total
histórico cuando una semana valía cero. Las fechas inválidas, futuras, monedas
sin verificar y tipos no admitidos quedan identificados sin aportar importes.
Los registros del libro de wallets en centavos permanecen separados.

`GET /api/v1/payouts/balance/exact` publica el saldo disponible como cadenas
decimales. Comparte el cálculo canónico de reservas con los endpoints anteriores:
los retiros ya asentados no se descuentan otra vez y los completados históricos
sin débito conciliado mantienen su reserva. La extracción de valores Decimal
conserva la conversión numérica en el adaptador de compatibilidad. No modifica
las solicitudes ni efectúa transferencias.

La lectura exacta del saldo bloquea brevemente la fila del rider, igual que los
escritores canónicos, y revisa la continuidad del libro USD. Un historial
incoherente o que exceda el límite devuelve 409; no publica un cero ficticio. Un
libro vacío puede demostrar cero con `ledger_integrity: no_evidence`. Los
registros sin moneda no se reetiquetan ni financian USD.

Historial y saldo son lecturas con sus propios cortes, indicados en la pantalla.
No se combinan para inventar otra disponibilidad. El formulario de retiro sigue
revalidando el saldo al guardar y conserva su protocolo de idempotencia; su
contrato numérico de compatibilidad y otros clientes aún quedan por migrar.
Las decisiones de moneda USD/VES y devolución a tasa original no se alteran.

Las pantallas conservan el diseño colorido y adaptable. Las consultas privadas
se invalidan por cambio de cuenta/rol y las cargas se vinculan al ID de sesión,
sin reconsultar por cada objeto de usuario recreado. Un fallo financiero deja
las cifras por confirmar; no rellena ingresos con órdenes ni monedas de prueba.
La exportación incluye todas las filas y exclusiones del historial cargado,
propietario, corte y huella SHA256, sin una segunda consulta.

## Entrega 99: formulario de retiro exacto

La solicitud usa el saldo exacto del propietario y compara centavos con BigInt.
El usuario puede escribir punto o coma decimal; el POST existente recibe el monto
USD como texto decimal canónico, sin redondeo en el formulario. Se mantienen las
intenciones v1 y la misma clave al recuperar o reintentar una solicitud incierta.
Una confirmación recuperada indica USD aun cuando falle la lectura del saldo.

El formulario no solicita fondos nuevos con saldo desconocido. Sí permite
confirmar o reintentar una intención existente con la misma identidad, para que
una reserva ya creada no obligue a generar otra solicitud. El servidor decide
sobre fondos, concurrencia e idempotencia. No se amplían métodos, no se introduce
conversión VES ni se confirma una transferencia bancaria. Las respuestas
numéricas de compatibilidad del servidor se conservan; su migración y los demás
consumidores activos siguen en el registro de producción.


## Entrega 101: resumen exacto de auditoría de repartidores

El listado y resumen del detalle consultan `/riders/audit/summary/exact`, para
SUPERADMIN/GERENTE. La página conserva créditos, débitos, ajustes firmados y
solicitudes pendientes como cadenas USD, con un mismo corte PostgreSQL y
exclusiones por moneda/fecha/estado/tipo. No se infiere saldo disponible ni se
convierte VES o moneda desconocida a USD. El detalle obtiene el perfil por ID
sin escanear un catálogo limitado a 500 perfiles.

Los importes se validan en centavos con BigInt y se exportan como texto decimal,
con el corte, huella y filtros confirmados. Los agregados operativos y contables
no multiplican filas al combinar órdenes, entregas y movimientos. Un importe
elegible inválido bloquea el resumen, con posibilidad de reintentar y conservar
el conjunto anterior. La ruta y consumidores numéricos anteriores siguen como
compatibilidad; las tablas internas del detalle y demás vistas pendientes se
registran en PRODUCCION_PENDIENTES.md. No hay migración ni cambio de datos previos.


## Entrega 102: registros de transacciones exactos

El gerente consulta páginas y detalles decimales en `/financial/transactions/exact`.
Las cadenas preservan el signo del movimiento y su moneda guardada; VES y moneda
no informada no se convierten en USD. Los códigos monetarios inválidos y los
importes no finitos se marcan para revisión sin perder la fila ni inventar ceros.
Los saldos ausentes permanecen desconocidos y los saldos registrados no se
presentan como disponibilidad actual. No se agrega el libro de wallets en centavos
ni el de cobros y devoluciones de clientes.

La lectura conserva corte, actor y filtros; el CSV usa cadenas decimales y señala
las revisiones. La impresión sigue siendo un registro contable, no un comprobante
de transferencia. Los contratos numéricos anteriores y sus consumidores no
migrados permanecen intactos. No hay migración, reetiquetado de moneda histórica
ni integración bancaria nueva. La política USD/BCV y las devoluciones a la tasa
original siguen vigentes.


## Entrega 103: historial exacto de retiros

Las lecturas de retiros conservan cadenas decimales, moneda original y saldos
ausentes. La página mantiene cursores firmados y el detalle consulta solicitud
e historial completo en una sola sentencia. Los registros con importe, moneda
o destino por revisar permanecen visibles, con decisiones bloqueadas cuando
sus datos no permiten confirmarlas. El subtotal USD utiliza BigInt y explicita
exclusiones; el CSV corresponde solo a la página y su corte confirmado.

La aprobación/rechazo mantiene el contrato anterior y se comprueba contra los
centavos del registro exacto. No se reemplaza la lectura con una confirmación
numérica ni se reintenta una decisión automáticamente. Los saldos históricos
no representan disponibilidad ni verificación bancaria. No hay migración ni
reetiquetado de moneda; la política USD/BCV y la tasa original de devoluciones
siguen vigentes.


## Entrega 104: tablas de auditoría exactas

Las tablas de órdenes, entregas y movimientos del detalle de auditoría ya usan
lecturas decimales. El precio versionado de la orden se comprueba contra sus
artículos y revisión; los Float históricos no se convierten ni se presentan como
cero. Los bonos conservados salen de NUMERIC y los movimientos del libro preservan
signo, moneda original y saldos ausentes. Cada tabla identifica su propio corte,
actor y huella; el CSV conserva ese alcance sin sumar fuentes independientes.

La entrega no tiene una moneda registrada propia para el bono. La auditoría
conserva esa ausencia y no adopta la moneda de la orden, un asiento o la configuración
actual. Se registra como pendiente denominar explícitamente nuevos snapshots, sin
reetiquetar los anteriores. No hay migración ni escritura histórica en esta entrega.
USD/BCV y la política de devolución a la tasa original permanecen vigentes.


## Entrega 105: moneda propia e inmutable de los bonos nuevos

Cada cierre bonificable nuevo conserva `locked_bonus_currency = USD` junto con
importe NUMERIC, tipo y fecha. También se conserva la unidad si el bono elegible
es 0.00; no se crea un movimiento financiero de importe cero. Los fallos no
bonificables no inventan importe, tipo, fecha ni moneda de bono. Las cinco rutas
de cierre usan la misma protección contra snapshots o asientos previos ambiguos.

La migración `20261117_bonus_currency` añade una columna nullable sin default ni
backfill. Todos los registros previos conservan NULL, incluidos bonos cero y
cierres históricos sin snapshot. Los triggers PostgreSQL impiden modificar el
snapshot congelado, su orden, repartidor o estado, eliminarlo y truncar historia
congelada. Un snapshot nuevo incompleto o sin USD se rechaza. Si ya se registró
una unidad explícita, el downgrade se niega para evitar perderla.

La lectura `/riders/audit/records/exact/v2` presenta únicamente la unidad guardada
en la entrega; las órdenes de apoyo siguen sin bono ni moneda de bono. La pantalla
y el CSV exactos usan esta versión. La lectura v1 conserva su contrato anterior y
no añade unidades a sus respuestas. No se deduce la moneda histórica desde una
orden, el libro financiero o la configuración. No se recalculan importes previos.

La base USD, la conversión VES con BCV conservado y la devolución en moneda y tasa
originales permanecen vigentes. Este bloque no cambia liquidaciones bancarias ni
convierte saldos históricos. Continúa pendiente la revisión de los demás
consumidores numéricos y la configuración decimal de bonos.


## Entrega 106: parámetros, escenario y componentes de bono exactos

La configuración activa usa `/settings/exact/v2` (GET/PATCH). Los importes llegan
y se guardan como texto decimal de hasta dos decimales; la comisión porcentual
conserva hasta 18 decimales. La lectura interpreta el texto JSON almacenado con
Decimal, sin pasar por Float. Un valor ausente permanece null; uno inválido o con
precisión incompatible se identifica para revisión, sin convertirlo a cero. Las
claves faltantes se inicializan en null, con el comportamiento anterior y sin
montos predeterminados. No se migran valores existentes en bloque.

La revisión s2 incluye el JSON original, fecha y actor: detecta diferencias que
una conversión binaria podría ocultar. If-Match es obligatorio. Los escritores
antiguos y exactos comparten los mismos bloqueos; un cambio concurrente recibe
412 y debe revisarse. La API anterior conserva sus respuestas y revisión s1; la
v2 informa legacy_revision cuando puede calcularse. La auditoría nueva conserva
el JSON anterior y los textos enviados, incluidos valores inválidos reparados.

`/settings/simulate-bonus/exact/v2` compara el bono uniforme propuesto con los
bonos USD conservados de las mismas entregas. Una sentencia PostgreSQL captura
configuración, revisión, reloj y candidatos. Se conservan los intentos fallidos
USD y se reemplaza únicamente el bono de las entregas completadas elegibles.
Moneda desconocida, otra moneda, ausencia de bono, snapshot inválido y cierre sin
fecha se excluyen con conteos explícitos. Los registros sin fecha se informan
como alcance global, sin asignarlos a un día supuesto. Una muestra superior a
10000 se rechaza, sin presentar una lectura truncada como completa. No aplica
zonas/niveles, no predice nuevas entregas ni confirma pago o disponibilidad.

`/deliveries/bonuses/exact` obtiene hasta diez órdenes con sus bonos conservados
en un solo corte SQL. El repartidor solo consulta asignaciones propias; se
comprueban identidad, origen y estado del snapshot. Una orden sin entrega no se
convierte en entrega ni en un bono cero. Productividad y el detalle del repartidor
usan esa lectura para importe, base y factores guardados, sin recalcular un
desglose monetario ni sustituir una unidad desconocida por USD o COP. Un fallo
de lectura mantiene el importe por confirmar y permite reintentar sin repetir
el cierre de la entrega. Los créditos y el saldo siguen procediendo de sus
libros canónicos separados.

El backfill legado migrate_historical_snapshots queda retirado: se detiene antes
de abrir una conexión o mostrar una URL. La moneda USD de nuevos snapshots y los
triggers de la entrega 105 permanecen vigentes. Esta entrega no añade migración,
reescribe snapshots anteriores ni incorpora conciliación bancaria o BCV automático.


## Entrega 107: precios registrados en las vistas operativas

Operador y repartidor consultan `pricing` de la orden: importes y artículos de
texto decimal con revisión. Se mantienen centavos con BigInt y se muestra USD
solo cuando el precio versionado declara esa unidad coherente con la orden.
Un precio inexistente o inválido no se reconstruye desde Float ni se convierte
en cero; la revisión histórica y la información almacenada permanecen intactas.
El detalle de entrega confirma la identidad de la orden y el vínculo inverso
antes de mostrar su precio, con reintento independiente de la lectura operativa.

«Precio de la orden» describe el total de esa revisión, no un saldo a cobrar.
Cobros parciales, devoluciones, créditos del rider y disponibilidad siguen en
sus libros separados. No se deduce deuda ni pago bancario desde el precio.
No hay migración ni cambios de contratos del servidor o de reglas de cobro.

## Entrega 108: saldo canónico en el perfil

El perfil consulta libro USD, reservas y disponible mediante el mismo cálculo
transaccional del propietario. La nueva ruta por repartidor autoriza únicamente
Gerente y Superadmin y vincula actor, propietario y perfil. No usa cachés Float
como evidencia monetaria ni escribe saldos. Monedas no verificadas quedan fuera
y se informa su cantidad. La interfaz distingue cero, error y última lectura
confirmada; retira datos al cambiar identidad o perder autorización. El saldo
contable no acredita una transferencia bancaria. No hay migración.

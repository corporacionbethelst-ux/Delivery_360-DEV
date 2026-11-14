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

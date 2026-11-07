# Historial y detalle de transacciones financieras

## Contrato HTTP comprobado

`GET /financial/transactions` devuelve un array sin total. Acepta `type`, `status`,
`rider_id`, `date_from`, `date_to`, `limit` (1–500, por defecto 100) y `offset`.
`GET /financial/transactions/{id}` devuelve un registro. Ambos endpoints están en
`backend/app/api/v1/financial.py`; los enums están en los modelos del backend.
La autorización del servidor sigue siendo la autoridad final.

El cliente admite los 18 tipos reales de TransactionType. Conserva los cuatro
PaymentStatus canónicos y las respuestas históricas APROBADA/PROCESANDO, que no
se envían como filtros porque el endpoint solo acepta el enum canónico. Rechaza
filtros desconocidos en vez de ampliar la consulta silenciosamente. `page` es una
comodidad local, convertida en offset con el límite efectivo; no se combina con
`offset`. Los límites finitos se truncan/acotan y un límite omitido usa 100.

Las fechas se validan y normalizan a UTC antes de enviarse: el parser legacy del
servidor retira tzinfo. Una fecha sin hora en `date_to` significa medianoche de ese
día en este endpoint; no se transforma en el final del día como en Reportes. La
pantalla no añade un selector de fechas; el servicio conserva ese contrato para
sus consumidores actuales.

## Adaptación y datos desconocidos

`transaction-contract.ts` valida objetos, identidad, aliases type/transaction_type
compatibles, enum, dinero con hasta dos decimales y centavos seguros, fechas y
metadatos opcionales. UUID equivalentes se canonicalizan. El detalle debe devolver
el ID solicitado; una página debe ser un array acotado sin duplicados y cumplir
los filtros capturados. Una respuesta contradictoria produce un fallo visible.

Los ceros se conservan. La moneda, descripción, fechas y snapshots de saldo
omitidos quedan desconocidos. No se deduce user_id desde rider_id, no se inventa
metadata, moneda COP, fecha actual o fecha de procesamiento. El importe mantiene
el signo almacenado: RETIRO positivo no equivale a ingreso. Los estados y las
fechas del registro contable no prueban un pago bancario. Se muestran los campos
reales de origen, referencia, actor e idempotencia cuando el servidor los informa.

El serializer actual no proporciona currency ni processed_at. También sustituye
algunos NULL históricos por cero mediante `_float_money`; el cliente no puede
reconstruir la ausencia que ya se perdió antes del HTTP. No se modifica el backend.

## Páginas, consultas y CSV

El historial pide 51 filas, muestra hasta 50 y usa la extra únicamente para saber
si hay siguiente página. El offset avanza 50. Tipo y estado se aplican en servidor;
la búsqueda de texto solo abarca las filas de la página confirmada. Se distinguen
filas cargadas y coincidencias visibles; ninguna cifra se presenta como total.
La navegación sigue disponible aunque la búsqueda local no tenga coincidencias.

Cada lectura conserva su consulta. Un error inicial no equivale a catálogo vacío;
un fallo posterior conserva la última página y sus etiquetas. Reintentar repite
el intento fallido, actualizar relee el offset confirmado y volver al inicio
reinicia la consulta. Respuestas de lecturas anteriores no sustituyen la actual.

El CSV exporta exclusivamente las coincidencias visibles de esa página, sin otra
lectura. Incluye filtros confirmados, offset, búsqueda y alcance parcial en cada
fila; excluye la fila extra. Se bloquea mientras hay una lectura pendiente o un
error sin resolver. El helper compartido conserva cero/negativos y opcionales
vacíos, neutraliza fórmulas en textos, escribe BOM UTF-8/CRLF y limpia URLs/enlaces.
Un fallo de descarga conserva los datos y permite reintentar. No hay promesa de
exportar todo el historial ni de confirmar escritura física en disco.

El backend ordena solo por created_at descendente, sin cursor ni desempate por ID.
Cambios concurrentes y fechas iguales pueden desplazar filas. Se detecta un solape
observable entre páginas adyacentes y se ofrece reiniciar; esto no detecta todas
las omisiones ni aporta un snapshot. Un CSV de página es una lectura acotada, no
una auditoría completa del ledger. La consistencia global requiere trabajo de
backend con cursor/orden estable o snapshot.

## Sesión, detalle y consumidores

El servicio captura credenciales antes de esperar HTTP y las comprueba después,
incluso en errores, antes de normalizar o entregar datos. Los controladores añaden
retiro por secuencia/desmontaje. La frontera de acceso solo monta las pantallas
para GERENTE/SUPERADMIN autenticados y reinicia el estado al cambiar cuenta, rol,
generación de credenciales o ID de ruta. Se mantiene el refresh verificado de la
misma cuenta del cliente API existente. No se realizan mutaciones financieras.

Un fallo al refrescar detalle conserva el registro confirmado y bloquea imprimir;
un fallo frío ofrece reintentar. Imprimir vuelve a comprobar sesión, identidad y
estado de lectura. Un cambio de ruta retira la respuesta anterior. La impresión
es del registro contable, sin presentar un comprobante bancario.

La auditoría de rider se adapta al modelo nullable para sus filas de transacción:
moneda/fechas fieles y cantidad cargada en lugar de sumar importes heterogéneos.
Sus restantes consultas, acceso, métricas y consistencia conjunta quedan fuera
de este bloque y requieren revisión propia.

## Validación reproducible

```sh
npm test -- --runInBand TransactionHistoryPage TransactionDetailPage transaction-flow transaction-contract transaction.service useTransactionHistory
npm test -- --runInBand --coverage
npm run type-check
npm run lint
CIRCLE_NODE_TOTAL=3 NEXT_PUBLIC_API_URL=https://api-test.delivery360.com npm run build
npm run start -- --hostname 127.0.0.1 --port 3069
python e2e/transactions.browser.py --artifacts-dir /tmp/transactions-browser
```

Los comandos se ejecutan desde frontend; Playwright Python y Chromium deben estar
instalados. El navegador solo admite un preview localhost/127.0.0.1, intercepta
HTTP/WebSocket de negocio y usa datos sintéticos, sin pagos reales. Verifica página
extra/offset, filtros, errores/reintentos, una descarga CSV real y su contenido,
móvil, identidad del detalle, cambios de ruta y logout con lectura pendiente.
Los resultados de la entrega se registran en [ENTREGA_69.md](ENTREGA_69.md).

# Detalle de auditoría de repartidor

## Alcance

Esta entrega modifica exclusivamente `/manager/operations/rider-audit/[id]` y su
nuevo servicio/controlador/contrato. El catálogo `/manager/operations/rider-audit`
y los servicios genéricos de riders, órdenes y entregas conservan su comportamiento
y requieren revisión propia. Los enlaces conducen a sus rutas existentes.

## Contratos reales y consultas acotadas

Se comprobaron `backend/app/api/v1/riders.py`, `orders.py`, `deliveries.py` y
`financial.py`. No se modifica backend, autorización, dependencias ni migraciones.

| Lectura | Contrato y alcance del cliente |
| --- | --- |
| `/riders/audit/summary` | Envelope items/total/limit/offset; **total es len(items)**, sin total global. No admite rider_id. Se buscan hasta cinco páginas de 100, deteniéndose al encontrar el rider o llegar a una página corta. |
| `/orders` | Array filtrado por rider_id. Se piden 51, se muestran 50; offset avanza 50. No se usa getAll de órdenes, que recorre un catálogo completo con otro alcance. |
| `/deliveries` | Envelope con total, limit y offset, filtrado por rider_id. Se piden 51 registros reales y include_total=true. En offset cero el backend puede añadir hasta 50 órdenes de apoyo además del límite. |
| `/financial/transactions` | Array filtrado por rider_id. Se valida con el contrato de transacciones de la entrega 69, 51/50 y offset explícito. |

Cada tabla tiene navegación independiente. La fila extra solo señala una página
siguiente; no se muestra ni se cuenta entre las 50 visibles. No se inventa un total
global. Cada conjunto confirmado requiere entre cuatro y ocho GET: tres tablas y
una a cinco páginas del resumen. No hay escrituras de negocio ni exportación nueva.

La búsqueda del resumen valida las páginas completas y rechaza duplicados de
rider o usuario, incluso entre páginas. No encontrar al rider entre 500 filas es
una búsqueda acotada, no prueba de inexistencia. Una página corta permite terminar
el recorrido observado, sin garantizar un snapshot del catálogo concurrente.

El endpoint de entregas añade objetos `id=order-{order_id}` cuando una orden
asignada no tiene registro en deliveries. Su estado se deriva de la orden. Se
validan y separan en un bloque propio, solo en la primera página; no cuentan como
entregas reales/completadas ni como señal de más páginas. Su límite es 50 y no se
conoce el total global de esas órdenes. Se comprueba el total del envelope con la
cantidad de registros reales y de apoyo; en offsets posteriores el backend informa
solo el total de entregas reales. No se reutiliza ese total como cantidad de órdenes.

## Adaptación fiel

Se valida identidad del rider en cada fila y relaciones/aliases informados,
estados reales, dinero finito con centavos seguros, fechas válidas, metadatos y
envelopes acotados. Dinero/fechas ausentes permanecen desconocidos; cero, Offline
y coordenadas 0,0 se conservan. Los UUID equivalentes se canonicalizan.

El detalle usa order_id, rider_id, updated_at y locked_bonus_amount del HTTP. No
confunde aliases camelCase, no sustituye actualización omitida por creación ni
bono ausente por un pago pendiente. Se muestran IDs completos y enlaces codificados
a la orden o transacción real; una orden de apoyo no recibe enlace de entrega.

El resumen valida conteos, subconjuntos y proporción SLA. Tolera el redondeo de
Python a dos decimales, incluido el empate a par, y el residuo binario del campo
legacy available_to_payout, que resta floats sin redondear. Este último no se
presenta como saldo disponible. El SLA sin entregas informa un denominador vacío.

Se separan agregados del servidor y cantidades de cada página. total_earned suma
CREDIT_TYPES en estado PROCESADO; pending_payouts suma retiros PENDIENTE. No son
el neto del ledger ni certifican dinero transferido. La moneda no viene en esos
serializers y no se deduce COP/USD. Tampoco se suman importes de monedas desconocidas
para producir una métrica cliente. Algunas ausencias ya se convierten en cero,
false o texto de reemplazo en el serializer; el cliente no puede reconstruirlas.
Las fechas sin zona informadas por el backend se interpretan y muestran en UTC.

## Confirmación, errores y sesión

Resumen y tres tablas se publican como un único conjunto tras validación. Si falla
un bloque, no se mezcla con otros nuevos ni se reemplaza por vacío. Un fallo frío
muestra error/reintento sin tablas vacías ficticias. Reintentar repite todos los
offsets del intento fallido; actualizar relee los confirmados; volver al inicio
reinicia las tres tablas y permite recuperarse de un solape de páginas.

Esto es coherencia en la UI, sin una transacción snapshot entre endpoints. El
backend ordena por fechas o disponibilidad/nombres sin desempate estable. Se
rechazan solapes adyacentes observables, pero inserciones, cambios de disponibilidad
y empates pueden causar omisiones no detectables. Hace falta cursor/orden estable
o snapshot del servidor para garantías globales y un filtro exacto de resumen para
evitar recorrer el catálogo.

Cada operación captura la sesión, consulta antes de cada GET y comprueba sesión y
secuencia después de esperar, incluidos errores y el intervalo entre interceptor
Axios y continuación del servicio. Una lectura retirada no continúa el resumen
con otra cuenta o ruta. Lecturas más recientes prevalecen. La frontera de acceso
solo monta el detalle para GERENTE/SUPERADMIN autenticados y reinicia el estado al
cambiar cuenta, rol, generación de credenciales o ruta. Se conserva el refresh
verificado de la misma cuenta. La autorización final sigue estando en servidor.

## Validación reproducible

Desde frontend, con dependencias instaladas:

```sh
npm test -- --runInBand rider-audit-contract rider-audit.service useRiderAudit RiderAuditDetailPage rider-audit.integration
npm test -- --runInBand --coverage
npm run type-check
npm run lint
CIRCLE_NODE_TOTAL=3 NEXT_PUBLIC_API_URL=https://api-test.delivery360.com npm run build
npm run start -- --hostname 127.0.0.1 --port 3070
python e2e/rider-audit.browser.py --artifacts-dir /tmp/rider-audit-browser
```

El navegador requiere Playwright Python y Chromium. Solo admite previews locales;
intercepta HTTP/WebSocket de negocio con datos sintéticos. Comprueba el resumen en
segunda página, las tres tablas, órdenes de apoyo, fallos/reintentos, identidad,
móvil y retiros de consultas por ruta/logout. La navegación por el catálogo usa
sus enlaces existentes; esta prueba no corrige ese catálogo. La evidencia no
sustituye E2E con backend real. Resultados nuevos: [ENTREGA_70.md](ENTREGA_70.md).

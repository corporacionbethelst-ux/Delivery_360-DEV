# Entrega 101 — auditoría operativa con importes USD exactos

La auditoría de repartidores en `/manager/operations/rider-audit` y su detalle
consultan un nuevo resumen decimal. Los créditos registrados, débitos, ajustes
con signo y solicitudes pendientes se mantienen separados. El cambio neto del
libro no representa saldo disponible, utilidad ni pago bancario.

## Contrato y conservación

`GET /api/v1/riders/audit/summary/exact` exige SUPERADMIN o GERENTE. Permite filtrar
estado, disponibilidad —incluido Offline— e ID de repartidor, con páginas de
hasta 200 perfiles. El detalle consulta directamente el ID; no abandona la
búsqueda después de escanear 500 perfiles. El listado muestra 50 filas y utiliza
una fila adicional para la navegación, sin afirmar un total global.

Una sola sentencia PostgreSQL obtiene los propietarios, métricas operativas,
agregados de Financial y solicitudes de retiro, junto con el corte de lectura.
Los agregados independientes evitan multiplicar importes al combinar órdenes,
entregas y movimientos. El orden termina en UUID para resolver nombres iguales.

Solo se agregan movimientos USD fechados hasta el corte, PROCESADO/PAGADO y de
los tipos canónicos. Créditos y débitos usan su dirección contable; AJUSTE
conserva el signo. Las solicitudes USD PENDIENTE se informan aparte: no se
restan para estimar disponibilidad ni se confunden con débitos ya asentados.
Se cuentan por separado las exclusiones por fecha ausente/futura, moneda no
verificada, estado y tipo no admitido, con prioridad determinista. Un importe
USD elegible inválido produce 409 y no publica un cero ficticio.

Los importes viajan como cadenas decimales. El frontend valida centavos con
BigInt, identidades, filtros, límites, exclusiones y la igualdad entre créditos,
débitos, ajustes y cambio neto. El CSV conserva esas cadenas, el corte, la huella
SHA256 del resumen y el alcance de la página/búsqueda confirmada. No vuelve a
consultar para exportar. Un error posterior conserva el conjunto confirmado;
cambiar cuenta o rol retira los datos privados anteriores.

Se mantienen los contratos numéricos anteriores, la lectura estricta de las
operaciones y la corrección de órdenes de la entrega 100. No se reetiquetan ni
reescriben datos históricos, no hay migración nueva ni transferencia bancaria.
Las tarjetas, filtros y tablas conservan el diseño colorido y adaptable.

## Verificación

Las pruebas PostgreSQL cubren decimales, signos, monedas desconocidas/VES,
fechas, estados, solicitudes, importes inválidos, permisos, filtros y orden
estable. Una inserción concurrente demuestra que el resumen inicial no mezcla
los datos del siguiente corte. Las pruebas históricas de bootstrap comprueban
que las rutas y esquemas anteriores permanezcan compatibles.

La suite frontend cubre el contrato exacto, importes superiores al entero seguro,
CSV, privacidad, filtros, paginación, fallos y lectura directa. Chromium comprueba
las pantallas y descargas sintéticas, además de las sesiones reales SUPERADMIN y
GERENTE sobre el laboratorio marcado. La prueba real compara tablas antes y
después y registra escrituras y excepciones JavaScript. Los resultados exactos
y artefactos se conservan junto a la entrega.

## Pendientes

Continúan pendientes los demás consumidores monetarios numéricos: tablas de
movimientos/órdenes/entregas del detalle, historial de retiros, bonos y otras
vistas de compatibilidad. También la revisión explícita de moneda histórica,
liquidaciones VES con BCV conservado, obtención fiable del BCV e integraciones
bancarias oficiales. Esta entrega no declara terminado el paso a producción.

Base: `35fa710a8960ddcd312fc8ea0111f3b41af721c9`, que contiene la entrega 100
fusionada por el propietario. Trabajo en `feat/exact-operational-rider-audit`;
sin fusión a main ni despliegue.

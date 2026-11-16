# Entrega 102 — transacciones registradas con decimales exactos

El listado `/manager/financial/transactions` y su detalle consultan una nueva
lectura decimal. Los importes y saldos guardados viajan como cadenas, sin pasar
por Number o Float. Se conserva el signo del registro, su moneda y la ausencia
de información; no se reinterpretan retiros positivos como ingresos.

## Lectura y conservación

`GET /api/v1/financial/transactions/exact/page` admite filtros por tipo, estado,
repartidor y fechas ISO, con páginas de 1 a 500 filas. El detalle usa
`GET /api/v1/financial/transactions/exact/{transaction_id}`. Ambas rutas exigen
SUPERADMIN o GERENTE, sin ampliar el acceso de otros roles. Las rutas numéricas
anteriores permanecen para compatibilidad, incluidos los consumidores del rider
y las tablas internas de la auditoría operativa.

Una sola sentencia PostgreSQL obtiene la página y su corte de visibilidad. Las
fechas se serializan en UTC; los límites con huso horario se convierten a UTC.
Una fecha final sin hora representa medianoche, igual que el contrato de consulta
existente, y no se amplía a fin del día. El orden usa creación descendente, fechas
ausentes al final y UUID descendente para resolver empates. Cada respuesta indica
los filtros, propietario de la consulta, corte y huella SHA256. El total corresponde
a las filas de esa respuesta, no a todo el historial.

Se conserva `currency_recorded`: USD, VES, otras unidades o null. No se transforma
moneda histórica desconocida en USD ni se aplica una tasa de cambio implícita.
Un código inválido se muestra para revisión, sin utilizarlo como denominación.
Un importe no finito o inválido queda sin cifra y con `money_review`; su fila
continúa visible junto con las correctas. Los saldos ausentes no se sustituyen
por cero. El cero efectivamente guardado permanece como `0.00`. No se reescribe
ningún valor original para presentar el historial.

Los saldos son fotografías del registro; no se valida ni se infiere un saldo
actual a partir de ellos. Se excluyen de este alcance el libro de wallets en
centavos y el libro de cobros/devoluciones de clientes. Un estado contable no
acredita una transferencia bancaria. No hay escrituras, integración bancaria ni
migración nueva.

## Frontend y exportación

Las pantallas conservan sus filtros, enlaces, tabla y controles, con cabeceras
degradadas, tarjetas, estados con color y adaptación móvil del sistema. Los
indicadores cuentan filas visibles y revisiones; no suman monedas distintas.
Se muestran el corte, los importes por revisar y los datos monetarios ausentes.

El contrato valida cadenas decimales, identidades, filtros, revisiones y las
banderas de alcance. Las comparaciones temporales conservan microsegundos. El
CSV usa los datos confirmados de esa página/búsqueda, con importes como texto,
moneda original, revisiones, origen, corte, huella y actor de consulta. La protección
de celdas de texto frente a fórmulas se mantiene. Exportar no vuelve a consultar.

Un fallo conserva la página o registro anterior y bloquea la exportación o la
impresión hasta recuperar una lectura válida. Cambiar cuenta, rol o recurso retira
los datos privados anteriores. Imprimir produce un registro contable identificado,
sin presentarlo como comprobante bancario.

## Verificación

Las pruebas PostgreSQL comprueban signos, monedas, NaN sin pérdida de filas,
valores ausentes y cero, filtros y husos horarios, orden estable, permisos y
compatibilidad numérica. Una escritura concurrente demuestra que los campos del
registro leído pertenecen al mismo corte. Las pruebas históricas de bootstrap
siguen comprobando las rutas y esquemas anteriores.

Las pruebas frontend cubren precisión superior al entero seguro, CSV, revisiones,
privacidad, recuperación, paginación, impresión e identidades contradictorias.
Los recorridos Chromium sintéticos y reales se incluyen en CI; los reales comparan
las tablas antes y después, verifican ambos roles y registran escrituras y errores
JavaScript. Los resultados exactos se conservan con los artefactos de la entrega.

## Continuidad

Base `db0e3f41d1a530539e0b690af6a90efb5b2dd172`, con la entrega 101 fusionada
por el propietario. Rama `feat/exact-financial-transactions`. No se fusiona main,
no se despliega y no se migra producción.

El siguiente bloque es el historial y administración de retiros con importes
exactos, conservando intenciones, reservas, estados y concurrencia. Siguen pendientes
las tablas monetarias internas de auditoría, bonos y precios de las vistas de
órdenes del rider, además de las integraciones y requisitos externos registrados
en PRODUCCION_PENDIENTES.md.

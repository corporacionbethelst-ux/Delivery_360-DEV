# Catálogo de auditoría por repartidor

## Contrato y alcance de la consulta

La pantalla `/manager/operations/rider-audit` usa `readAuditCatalogPage`, con un
GET por consulta a `/riders/audit/summary`. Se comprobó el endpoint real en
`backend/app/api/v1/riders.py`: admite `status_filter`, `is_online`, `limit` de
1 a 500 y `offset`. El envelope informa items/limit/offset y **total=len(items)**;
ese total no describe todo el catálogo. No se añade un filtro de texto al servidor.

La pantalla pide 51 filas, muestra hasta 50 y reserva la extra como señal de
siguiente página. El offset avanza 50. Estado y disponibilidad se filtran en
servidor; se conserva `is_online=false` para Offline. Un filtro desconocido o
un offset inválido no se omite silenciosamente. La respuesta debe cumplir los
filtros capturados, tener límite/offset correctos y ser una página acotada sin
IDs rider/usuario repetidos. No se inventa un total global ni una última página.

La búsqueda de ID rider/usuario, nombre, email, teléfono, placa, zona o estado
solo recorre la página confirmada; ignora mayúsculas/acentos y conserva el texto
original en los datos/CSV. Una búsqueda sin coincidencias permite seguir navegando.
La búsqueda no se amplía automáticamente al resto de páginas.

## Datos y métricas

Se reutiliza el normalizador de la entrega 70 para identidad, estados, conteos,
SLA, dinero, coordenadas y fechas. Se agregan vehículo/placa/zona y sus IDs como
campos opcionales validados. El límite de normalizeSummaryPage es configurable;
su valor por defecto sigue siendo 100 para la búsqueda del detalle. El catálogo
usa 51 explícitamente. Los contratos del detalle siguen comprobándose.

Cero, Offline y coordenadas 0,0 se conservan. Disponibilidad/estado omitidos se
muestran desconocidos, no Offline/PENDIENTE. Moneda/fecha/metadatos ausentes no se
inventan. Las tarjetas muestran los IDs completos reales de rider y usuario y un
enlace codificado al detalle. No se deduce user_id desde rider_id.

Las métricas se limitan a filas cargadas, coincidencias, Online informado con su
cantidad desconocida y órdenes activas de las coincidencias. Una suma de conteos
fuera de enteros seguros informa que no es calculable. Se elimina la suma cliente
de ganancias/retiros en monedas desconocidas. Los importes por rider conservan
su signo y la moneda solo si viene informada; no se presenta un saldo disponible.

Los créditos PROCESADO del resumen agregan CREDIT_TYPES en ese estado, mientras
que los retiros pendientes agregan PayoutStatus.PENDIENTE. El SLA usa todas las
entregas del rider como denominador; cero entregas se indica explícitamente. Se
mantienen los criterios legacy documentados en [RIDER_AUDIT_DETAIL.md](RIDER_AUDIT_DETAIL.md),
incluidos redondeo Python, resta float y ausencias ya sustituidas en el serializer.
Estos agregados contables no prueban una transferencia bancaria.

## Confirmación, errores, sesión y CSV

Cada página conserva su consulta confirmada. Las respuestas anteriores no
sustituyen una consulta nueva. Cambiar filtros reinicia offset y combina cambios
rápidos. Si falla un filtro, se conservan página/etiquetas confirmadas y el intento
para reintentar. Una lectura fría fallida muestra error sin catálogo vacío ficticio.
Actualizar relee el offset confirmado; volver al inicio reinicia explícitamente.
Reintentar conserva también la intención de reinicio si ese intento había fallado.

La frontera de acceso solo monta el catálogo para GERENTE/SUPERADMIN autenticados
y reinicia estado y búsqueda al cambiar cuenta, rol o generación de credenciales.
El servicio comprueba sesión tras HTTP y en errores; el controlador añade secuencia
y desmontaje. Se comprueba el intervalo de continuación del interceptor Axios y
se conserva el refresh verificado de la misma cuenta. La autorización del servidor
sigue siendo la autoridad final. No se realizan mutaciones de negocio.

El CSV es exclusivamente de las coincidencias de la página confirmada, sin otra
lectura y sin fila extra. Incluye 33 columnas con IDs rider/usuario, datos reales,
ceros, ausencias vacías, disponibilidad nullable, moneda, coordenadas, fecha de
ubicación convertida a UTC, conteos, denominador SLA, filtro de estado/online,
offset, búsqueda y alcance parcial. No se añade available_to_payout como saldo.

Se bloquea el archivo durante lectura/error sin resolver o sin coincidencias. Una
falla de descarga conserva datos y permite intentar de nuevo. El helper compartido
protege textos de fórmula, escapa comillas/saltos, escribe BOM UTF-8/CRLF y limpia
URLs/enlaces. Los números negativos tipados conservan su signo. La generación no
prueba escritura en disco y abrir el CSV puede aplicar conversiones de la hoja.

## Límites

El backend ordena por disponibilidad y nombres sin desempate estable ni snapshot.
Cambios concurrentes pueden mover filas. Se rechazan solapes observables de rider
o usuario entre páginas adyacentes de la misma consulta; no se detectan todas las
omisiones. El CSV no es una auditoría completa de todos los repartidores. Cursor,
orden estable y exportación global requieren garantías adicionales de backend.
El helper legacy getAuditSummary de rider.service no se modifica; el catálogo
activo utiliza el nuevo servicio validado.

## Validación reproducible

Desde frontend, con dependencias instaladas:

```sh
npm test -- --runInBand rider-audit-catalog.test rider-audit-catalog.service useRiderAuditCatalog RiderAuditCatalogPage rider-audit-catalog.integration
npm test -- --runInBand --coverage
npm run type-check
npm run lint
CIRCLE_NODE_TOTAL=3 NEXT_PUBLIC_API_URL=https://api-test.delivery360.com npm run build
npm run start -- --hostname 127.0.0.1 --port 3071
python e2e/rider-audit-catalog.browser.py --artifacts-dir /tmp/audit-catalog-browser
python e2e/rider-audit.browser.py --base-url http://127.0.0.1:3071 --artifacts-dir /tmp/audit-detail-regression
```

Playwright Python y Chromium deben estar instalados. Ambos scripts solo admiten
previews locales e interceptan HTTP/WebSocket de negocio con datos sintéticos.
El script del detalle se adapta al enlace accesible real identificado por rider,
sin modificar sus comprobaciones. Se verifican también los bytes del CSV descargado.
Resultados nuevos y pendientes: [ENTREGA_71.md](ENTREGA_71.md).

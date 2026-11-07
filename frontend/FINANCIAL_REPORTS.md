# Reportes financieros y CSV con rango confirmado

La pantalla de Reportes mantiene separados los valores de los inputs y la última
consulta confirmada. Editar fechas no cambia las cifras ni habilita la exportación
de otro rango; Aplicar consulta valida y consulta ese rango. Sin fechas, ambos
extremos están abiertos. Los días se interpretan en UTC e incluyen el día final.

## Contratos del servidor

- GET /financial/reports/orders acepta date_from, date_to, limit hasta 5000 y offset.
  Devuelve filas acotadas y agregados para todo el rango, con todos los estados.
- GET /financial/reconciliation admite solo date_from/date_to. Su criterio incluye
  entregas cobradas, ledger y estados internos de retiros. No es el mismo conjunto
  que todas las órdenes. El cliente no fuerza igualdad entre esos agregados.
- El reporte de órdenes usa delivered_at, después created_at y ordered_at como
  fecha base. La conciliación también considera updated_at y distintas fechas
  para ledger/retiros. Esa diferencia del servidor se conserva y se indica.
- Los servicios copian la consulta y comprueban credenciales después del HTTP,
  incluso ante errores. Rechazan filtros desconocidos y paginación en conciliación
  en lugar de ignorarlos. Los offsets de timestamps se normalizan a UTC antes del
  parser legacy que retira la zona sin convertirla.

Se comprueban rangos explícitos, conteos enteros seguros, importes finitos de hasta
dos decimales, identidades únicas, estados, fecha base de las filas y consistencia
de los agregados. Una respuesta corta, duplicada o contradictoria falla. Cuando
se recibe todo el conjunto, sus importes y estados deben cuadrar con sus agregados.
Un opcional omitido sigue desconocido; un importe principal omitido no se vuelve
cero. La conciliación se valida con sus fórmulas de obligación, costos y margen.

La moneda de órdenes no se infiere de la moneda COP informada por conciliación.
La pantalla conserva ceros medidos y distingue estados internos de retiro de
confirmación bancaria. Los campos opcionales de pago/rider/fecha no se reconstruyen.

## Lectura y exportación

Aplicar consulta lee órdenes (máximo 1000 filas) y conciliación en paralelo y solo
publica el par cuando ambas respuestas son válidas. Los agregados pertenecen al
rango completo; la vista previa muestra hasta 10 filas y declara cuántas recibió.
El ID interno y la referencia externa se muestran separados, como en el CSV.

Exportar CSV lee de nuevo **el rango confirmado**, con máximo 5000 órdenes y su
conciliación. Solo descarga si la respuesta contiene todo el conjunto declarado.
Si el rango ya supera 5000, se pide reducirlo; si crece entre vista previa y
exportación, se rechaza el archivo y se conserva el par anterior. No se descargan
archivos truncados ni se recorren páginas offset para aparentar una foto completa.

Un fallo de lectura conserva el último par y permite un reintento deliberado del
intento fallido. Un fallo al crear la descarga conserva el nuevo par ya validado.
Si las órdenes desaparecen durante la preparación, el par vacío válido se muestra
y no se crea un CSV vacío. El mensaje CSV generado solo confirma que se solicitó
la descarga al navegador, no que el archivo ya esté guardado en el dispositivo.

Las lecturas antiguas no sustituyen nuevas ni detienen su carga. Un guard síncrono
impide dos exportaciones por doble clic. Editar fechas o iniciar otra consulta
retira una exportación pendiente; cambiar cuenta/rol/credenciales o desmontar la
pantalla también impide una descarga tardía. La renovación de token verificada de
la misma cuenta sigue siendo válida. El control de roles cliente no concede acceso:
ambos endpoints mantienen los permisos del servidor.

## Formato del archivo

El archivo incluye ID real, referencia externa, fechas y fecha base en UTC,
datos informados del cliente/direcciones, estados, importes, método de pago,
rider y límites del rango. Los importes cero se conservan y los opcionales ausentes
quedan vacíos. El nombre se construye con el rango confirmado; sin límite se usa
sin_inicio/sin_fin. El sufijo de fecha que añade el helper es la fecha de descarga,
no un límite inventado para la consulta.

El helper compartido escribe BOM UTF-8, CRLF, comillas escapadas y columnas
introducidas por filas posteriores. Un texto que empieza por =, +, -, @ tras
espacios/control lleva un apóstrofo inicial para impedir que se interprete como
fórmula; los números tipados negativos siguen siendo números. Esa transformación
solo afecta al archivo, no a los datos de la aplicación. El importador de hojas
de cálculo puede aplicar sus propias conversiones de tipos.

Los enlaces temporales se retiran y sus object URLs se revocan, también si falla
el clic. Las demás pantallas que usan downloadCSV conservan su llamada existente.

## Límites y comprobación

Dos endpoints y las consultas internas del backend no forman una transacción
snapshot entre lecturas. La validación detecta contradicciones observables, sin
garantizar que el historial no cambie después ni certificar datos del ledger.
El serializer del servidor todavía puede transformar algunos NULL históricos
en cero; el cliente no puede distinguirlos de un cero ya informado por HTTP.

El recorrido reproducible está en e2e/financial-reports.browser.py. Requiere
Playwright Python, Chromium y un build servido localmente; intercepta HTTP y
WebSocket con datos sintéticos. Ejemplo:

```sh
python e2e/financial-reports.browser.py --base-url http://127.0.0.1:3068 --artifacts-dir /tmp/delivery360-reports-browser
```

Comprueba el archivo realmente descargado, fechas, ceros, datos ausentes, textos
con comillas/acentos/saltos de línea, neutralización de fórmulas, cancelación,
logout y vista móvil. Es una prueba de navegador con transporte simulado, no E2E
contra el backend de producción ni homologación bancaria.

# Resumen financiero: contrato y recuperación

El resumen de gerencia consulta GET /financial/summary con period=today/week/month.
El servidor usa calendario UTC (hoy, lunes de la semana y primer día del mes),
no los últimos 7/30 días ni el calendario local del navegador. La pantalla muestra
el rango devuelto y su zona UTC; no inventa fechas cuando faltan.

## Datos admitidos

getSummary captura la sesión y copia/valida la consulta antes del HTTP. El período
de respuesta debe corresponder al solicitado. Para rangos personalizados, el
servidor responde custom y se comprueban sus límites. Las fechas con offset se
normalizan a UTC antes del envío porque el parser legacy del backend elimina el
offset sin convertir la hora. Esto corrige ese comportamiento para este caller;
no cambia el parser del servidor ni garantiza el contrato de otros clientes.

Los importes admiten números o cadenas decimales finitas con hasta dos decimales
y centavos enteros seguros. Se rechazan booleanos, vacíos, NaN/Infinity, fracciones
excesivas y cantidades fuera de precisión. Los conteos requieren enteros seguros
no negativos. Los campos principales son obligatorios: una respuesta parcial no
se convierte en un informe de ceros. Los campos opcionales ausentes quedan null.

Se comprueba margen = ingresos − costos, costo de riders ≤ costo total y el
desglose de otros costos cuando viene informado. Si el servidor entrega las tres
capas, se comprueba su fórmula de costo reconocido de riders: el mayor entre cero,
devengo menos deducciones y retiros EN_PROCESO/COMPLETADO. No se suman dos veces
devengo y retiro. Una respuesta degraded no se interpreta como una medición válida.

Un cero realmente informado permanece cero. El margen puede ser negativo y su
barra conserva un ancho positivo, a la izquierda del eje cero. El resumen no
supone USD/COP: sin currency muestra moneda no informada. El servidor actual no
incluye ese campo en esta respuesta. No se añade conversión de moneda.

La etiqueta Costo reconocido de repartidores evita presentar esa combinación
de devengo/caja como transferencias bancarias pagadas. Los valores opcionales del
desglose no se reconstruyen silenciosamente con restas o Math.max.

## Consultas y sesión

La página mantiene una instantánea local de la última consulta válida con su
período y rango. Un error de otro período conserva esa instantánea y vuelve a
seleccionar su período; Reintentar consulta repite el intento que falló. Actualizar
resumen consulta el período confirmado. Las respuestas/errores antiguos no
sustituyen lecturas nuevas ni detienen su indicador de carga.

Cambiar generación de credenciales, usuario o rol retira el estado privado de la
pantalla antes de una nueva lectura. Se comprueba la sesión después del servicio,
incluido el intervalo posterior al interceptor HTTP. Una renovación verificada
del token de la misma cuenta conserva el período. El servidor sigue autorizando
cada request; el control de roles del navegador no concede permisos.

El store legacy comparte una secuencia para fetchSummary y getDailySummary. Usa
el endpoint real de resumen en lugar de /financial/report. Su adaptación camelCase
mantiene netCommission, pendingPayouts, activeDeliveries y pendingPayments en null:
la respuesta no informa esas métricas. Un fallo conserva el resumen o null inicial.
No se rediseñan aquí los canales legacy de reportes, transacciones o reglas.

## Validación y límites

Las pruebas Jest cubren contrato, store, UI y la cadena Axios/API real con adaptador
en memoria. El recorrido Chromium está en e2e/financial-summary.browser.py y exige
un preview local. Requiere Playwright Python y Chromium; no son dependencias nuevas
de la aplicación. Ejemplo, con el build iniciado en el puerto 3067:

```sh
python e2e/financial-summary.browser.py --base-url http://127.0.0.1:3067 --artifacts-dir /tmp/delivery360-summary-browser
```

El script intercepta HTTP y WebSocket, usa identidades/importes sintéticos y no
conecta a una API de negocio. Comprueba errores/reintento, respuesta tardía,
margen negativo, ausencia de otros costos, vista móvil y logout con consulta en
curso; comprueba que no haya escrituras HTTP ni errores JavaScript. Las capturas
son evidencia del build local con transporte simulado, no E2E con datos reales.

Cada resumen es una lectura puntual de agregados del servidor. No se ofrece
snapshot transaccional entre consultas, homologación bancaria o balance de
producción. La exactitud de los agregados históricos depende del ledger/órdenes
y reglas del servidor; las comprobaciones de forma/consistencia no son auditoría
contable. Los reportes/CSV y el gate global del 50 % siguen pendientes.

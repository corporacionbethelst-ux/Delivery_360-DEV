# Entrega 67 — Resumen financiero verificable y contrato de arranque actualizado

Fecha: 6 de noviembre de 2026, America/Caracas.
Base: `2212aaabb74d76a0452fc1e8f43f4cc685a3b192` (PR #307 fusionado).
Rama: `fix/financial-summary-validation-and-api-surface-v1`.

El checkout inicial estaba limpio y no se encontraron instrucciones AGENTS.md
aplicables. Se conservan las ramas y el historial de entregas anteriores.

## Problemas confirmados

El CI final de la entrega 66 terminó con 2428 pruebas backend aprobadas, dos
omitidas y **cuatro fallos de inventario de API**, además del gate de cobertura
frontend. Esos fallos sí fueron introducidos al añadir /payouts/page sin actualizar
el inventario; se reprodujeron localmente antes de corregirlos. La suite financiera
acotada de la entrega anterior no detectaba ese problema de composición.

El resumen de gerencia no retiraba consultas de períodos/cuentas anteriores ni
separaba el período seleccionado de los datos conservados. Aplicaba `|| 0` y USD
por defecto, reconstruía otros costos y llamaba pagos a un agregado que incluye
devengo/retiros en proceso. El store conservaba otro contrato camelCase distinto
del HTTP, fabricaba un resumen de ceros ante un error y consultaba /financial/report
para adaptar el resumen diario. Ninguna de esas conductas confirma cifras reales.

## Cambios

- Nuevo inventario exacto de **203 rutas** con /payouts/page y sus dependencias.
  Se conservan los dos inventarios históricos. Una prueba adicional elimina solo
  esa adición y exige que todas las rutas, dependencias y OpenAPI previos coincidan
  con la base de conciliación. Se restaura la descripción original del endpoint
  legacy, evitando un cambio incidental de su OpenAPI. No se relajan los permisos
  o pruebas de arranque ni se añade una ruta nueva en esta entrega.
- El servicio valida sesión, copia de consulta, período/rango, dinero en centavos
  seguros, conteos, margen y desgloses coherentes. Campos principales ausentes o
  contradictorios fallan; opcionales ausentes quedan null. Fechas sin zona se
  interpretan UTC y los offsets de consulta se normalizan antes del parser legacy.
- La pantalla conserva la última consulta válida con su período/rango, permite
  reintentar el intento fallido y refrescar el período confirmado. Lecturas/errores
  antiguos no sustituyen una consulta posterior. Cuenta, rol o credenciales nuevos
  retiran datos privados. Una renovación de token de la misma cuenta sigue vigente.
- Se mantienen ceros realmente medidos, margen negativo y moneda desconocida.
  No se supone USD/COP ni se reconstruyen campos opcionales omitidos. Las etiquetas
  distinguen costo reconocido/devengo de confirmación bancaria. El gráfico admite
  valores negativos a la izquierda de cero sin alturas/anchos negativos.
- El store usa /financial/summary en ambas entradas de resumen con una secuencia
  compartida. Un error conserva la instantánea o null inicial. Métricas que el HTTP
  no informa quedan null; margen neto no se presenta como comisión neta.
- Se añade un recorrido Chromium repetible, con HTTP/WebSocket interceptados y
  datos sintéticos. Se revisan capturas de escritorio y móvil; la revisión visual
  detectó y corrigió un texto recortado por el ancho del contenedor móvil.

Contrato/ejecución: [FINANCIAL_SUMMARY.md](FINANCIAL_SUMMARY.md).

## Validación nueva

**93 pruebas frontend netas nuevas** sobre las 1133 de esta base, en cuatro suites:
contrato, store, página y cinco integraciones con Axios/API reales y transporte en
memoria. Se conservan y adaptan los casos anteriores para usar el contrato HTTP real.

| Control | Resultado local |
| --- | --- |
| Frontend completo con cobertura | **1226 aprobados / 72 suites**, 20,168 s |
| Statements / ramas / funciones / líneas | **38,09 % / 35,06 % / 34,09 % / 37,65 %** |
| Gate global 50 % | Sigue fallando en las cuatro métricas; no se cambian umbrales/exclusiones |
| TypeScript y lint | Aprobados; advertencias existentes fuera de la pantalla modificada |
| Build con Inter real | Aprobado, **48 páginas**, tipos/lint activos |
| Chromium sobre build local | **6 comprobaciones**, 8 lecturas de resumen, cero escrituras HTTP o errores JavaScript |
| Página / normalizador del resumen | 100 % de líneas; ramas 96,22 % / 97,45 %, respectivamente |
| Contrato de composición focalizado | 5 aprobados: inventario actual, preservación histórica, dos factories y ausencia de IO al construir |
| Backend completo | **2433 aprobados, 2 omitidos**, 766,88 s, PostGIS 16/3.4 y Redis 7 locales |
| Cobertura backend de esa corrida | **71,56 %** de líneas |
| Flake8 / Black / Mypy | Aprobados; 194 fuentes app sin errores de tipos |
| git diff --check | Aprobado |

Después del ajuste de ancho móvil se repiten UI, TypeScript, build, Chromium y
la suite frontend completa sobre la fuente final.
No se desactiva ninguna verificación del build; CIRCLE_NODE_TOTAL=3 limita workers.

La primera preparación de backend completo usó PostgreSQL sin PostGIS y falló al
crear geometry. Se detuvo esa corrida y se conservó su log como diagnóstico. Se
preparó después el mismo motor PostGIS del CI y se verificaron diez pruebas de
asignación antes de repetir la suite completa. No se atribuyen los errores de ese
entorno inicial a la fuente ni se usan sus resultados parciales como aprobación.
Los datos/esquemas de prueba son locales y privados; no se accede a producción.
La corrida final omite dos pruebas offline de SDK Firebase/Twilio porque esos
paquetes opcionales no están instalados, como en el CI de la base. La advertencia
existente de pytest por asyncio_default_fixture_loop_scope permanece sin cambiar
dependencias. La cobertura backend se registra en el XML de la corrida completa.

Los primeros ensayos del navegador detectaron un doble WebSocket que cerraba y
reconectaba continuamente y un selector ambiguo con el anunciador de rutas de Next.
Se corrigió el arnés para mantener sockets sintéticos locales y seleccionar la
alerta financiera. Los seis controles finales se ejecutan sin esos bloqueos.

## Límites y continuidad

La validación del cliente no audita el ledger histórico ni crea una instantánea
transaccional entre consultas. El resumen del servidor usa calendario UTC y un
agregado de devengo/caja; no se modifica su cálculo ni se certifica pago bancario.
La normalización de offsets se aplica a este servicio, sin corregir el parser de
otros callers. Se conserva desconocida la moneda que esta respuesta no incluye.

Las seis pruebas de navegador usan transporte simulado; no sustituyen E2E de
backend real ni homologación con un proveedor. Los canales legacy de reportes,
transacciones/reglas del store quedan fuera de esta refactorización. La próxima
mejora concreta es extender estos controles a Reportes/CSV, que aún conserva
adaptaciones parciales y filtros de borrador junto a datos de otra lectura.

El gate global del 50 % y la homologación sandbox de fase 7 siguen pendientes.
No se modifican dependencias, workflows, migraciones o umbrales; no se envían pagos,
mensajes o facturas reales ni se fusiona o despliega. El sistema no se declara al
100 % para producción. La publicación y el CI se registran por separado.

# Delivery360 — entrega 104

El detalle de auditoría del repartidor consulta los precios de órdenes y los bonos
conservados en entregas mediante registros decimales, y reutiliza la lectura exacta
de transacciones. Conserva la navegación independiente de cada tabla, sus controles
y el conjunto anterior cuando una lectura falla. Los enlaces mantienen los IDs de
orden y movimiento confirmados, con la presentación adaptable de auditoría.

## Alcance de las lecturas

`/riders/audit/records/exact` requiere el perfil solicitado y el tipo `orders` o
`deliveries`. Solo Gerente y Superadmin pueden consultar. Cada página obtiene su
corte, actor, registros y huella de una sola sentencia SQL, incluso estando vacía.
Se conservan empates por fecha/ID y fechas ausentes. Las páginas usan desplazamientos
sobre registros vivos y una fila de anticipación; no congelan cambios posteriores.
El resumen, órdenes, entregas y transacciones siguen siendo lecturas independientes.
La pantalla exige que sus actores coincidan antes de publicar el conjunto.

Los precios de órdenes proceden únicamente de su registro NUMERIC versionado y
comprobado con la revisión, artículos y cálculo originales. Los precios históricos
Float no se convierten a exactos ni a cero. Un precio incompleto o contradictorio
queda visible para revisión, sin ocultar las otras filas ni modificar su moneda.
El precio de una orden no representa ganancias del repartidor.

Los bonos conservados se leen de NUMERIC sin conversión numérica en el navegador.
Se distingue cero, ausencia e importe inválido. El modelo de entrega no registra
una moneda propia para ese bono: se presenta sin moneda informada y no se deduce
USD desde una orden, un movimiento o la configuración actual. Los movimientos
contables conservan signo, moneda original y saldos ausentes, según la entrega 102.
Ninguna de estas tablas declara disponibilidad actual o verificación bancaria.

Las órdenes sin entrega se mantienen separadas, sin bonos ni cómputo como entregas
reales. El bloque muestra hasta 50 en la primera página y advierte si hay más. Su
consulta comparte la sentencia de las entregas reales para no duplicar una orden
que acaba de obtener su registro de entrega. El estado mostrado es derivado.

El nuevo CSV incluye solo las filas visibles de las páginas confirmadas, su clase
de origen, importes decimales, revisiones, unidades, actor, corte y huella de cada
tabla. No hace consultas adicionales ni suma precios, bonos y saldos. Una carga
pendiente, un error o un cambio de sesión impiden exportar datos no confirmados.

## Compatibilidad y validación

Los endpoints numéricos, los contratos anteriores de auditoría, la creación de
órdenes, los cierres de entregas, el libro de saldos y las mutaciones de retiros
permanecen compatibles. No hay migración ni reescritura de moneda o importes
históricos. Se verifica la conservación del laboratorio y sus documentos.

Se añaden pruebas PostgreSQL para fuentes exactas, precios históricos, importes
inválidos, límites, roles, fechas y concurrencia. Las pruebas frontend cubren
identidad, metadatos, importes, paginación, recuperación, sesión y CSV. Chromium
comprueba la navegación interceptada y el laboratorio real con ambos roles,
exportación, rechazo de respuestas corruptas y presentación móvil. La validación local del código incluye 3360 pruebas frontend en 151 suites,
35 casos nuevos del backend y 96 contratos históricos de bootstrap. TypeScript,
Black, flake8 crítico, mypy de 216 fuentes y build de 50 páginas están aprobados.
Los recorridos principales de Chromium suman 26 comprobaciones: 7 interceptadas
y 19 del laboratorio real, sin escrituras ni errores JavaScript. Los resultados
finales y archivos de recuperación se guardan en `work/entrega104`.

Para probar la rama o el PR conservando los cambios propios:

```sh
docker compose up -d --build --no-deps backend frontend
```

Recargar con Ctrl+F5, entrar como Superadmin o Gerente a
`/manager/operations/rider-audit`, abrir un perfil y probar las tres tablas,
paginación y «Exportar tablas CSV». No hace falta volver a sembrar la base.

Siguen pendientes otros consumidores numéricos y la denominación explícita de los
nuevos snapshots de bono, conservando desconocida la moneda histórica. Los accesos
bancarios, BCV automático fiable, staging y aceptación del usuario siguen en
`PRODUCCION_PENDIENTES.md`.

# Delivery360 — entrega 105

El punto 1 incorpora una unidad USD propia e inmutable en los bonos nuevos de
entregas. Los cinco caminos de cierre guardan importe NUMERIC, moneda, tipo y
fecha en la misma transacción que el movimiento canónico. Los reintentos no
duplican ingresos. Si existe un snapshot o asiento anterior ambiguo, el cierre
requiere revisión y no reetiqueta ni recalcula su historia.

## Datos anteriores y protección

La migración `20261117_bonus_currency`, sucesora de
`20261115_cashbook_indexes`, añade `deliveries.locked_bonus_currency` nullable,
sin default ni UPDATE histórico. Los bonos anteriores, incluidos ceros y
cierres sin snapshot, conservan NULL. Los fallos no bonificables nuevos también
conservan la ausencia de bono; un bono elegible de 0.00 sí guarda USD, sin crear
un crédito cero. Los importes y las reglas actuales de cálculo se conservan.

PostgreSQL rechaza snapshots nuevos incompletos y protege los congelados frente
a cambios de importe, unidad, componentes, identidad, estado, DELETE y TRUNCATE.
Los metadatos operativos ajenos al snapshot siguen actualizables. El downgrade
solo se permite mientras no exista ninguna moneda explícita; después se niega
para preservar esa información. No se debe eliminar esta columna para revertir
un despliegue que ya haya registrado bonos nuevos.

## Auditoría y compatibilidad

La auditoría exacta v2 muestra la moneda guardada, con la presentación adaptable
y colorida existente. El CSV mantiene USD solo donde está registrado. Los bonos
históricos siguen visibles sin moneda informada y las órdenes sin entrega
continúan separadas, sin bono sintético. La lectura exacta v1 y las respuestas
numéricas anteriores conservan su contrato. Se mantienen roles, paginación y
exportación de páginas confirmadas.

## Validación

61 casos nuevos de PostgreSQL cubren las cinco rutas, importes cero, fallos no
bonificables, concurrencia, rollback, recibos previos, historia, triggers y
downgrade. Pasaron además 196 casos existentes de cierres/seguridad y 131 de
bootstrap y auditoría exacta. El frontend aprobó 3361 pruebas en 151 suites;
TypeScript, Black, flake8 crítico y mypy de 216 fuentes están verificados.
El build de 50 páginas y las 162 comprobaciones de los 14 recorridos visuales
interceptados están aprobados. El ciclo real completa 25 comprobaciones,
incluyendo unidad USD, UI/CSV, idempotencia y retiros. Los resultados finales de
Chromium y CI se conservan en `work/entrega105`.

Antes de migrar el laboratorio se respaldó su base. Se verificaron las columnas
originales de las 83 entregas y el resto de tablas con datos, y las huellas de
los 48 documentos anteriores. Las nuevas pruebas funcionales usan datos
sintéticos adicionales y conservan los originales. No se migró producción.

## Prueba del cambio

Usar esta rama o incorporar el PR conservando cambios propios. Respaldar primero
la base local y aplicar la migración con el procedimiento habitual del proyecto:

```sh
docker compose up -d --build --no-deps backend frontend
```

El arranque del backend ejecuta Alembic. No volver a sembrar ni borrar volúmenes.
Como Superadmin o Gerente, abrir `/manager/operations/rider-audit`, elegir un
repartidor y revisar entregas y «Exportar tablas CSV». Los bonos anteriores deben
seguir sin moneda. Completar una entrega nueva: su bono debe mostrar USD en la
auditoría y el CSV. Recargar con Ctrl+F5 después de reconstruir el frontend.

El siguiente pendiente es la revisión de los demás consumidores numéricos y la
configuración decimal de bonos. BCV automático, accesos bancarios, staging y
aceptación del usuario permanecen en `PRODUCCION_PENDIENTES.md`. Este bloque no
fusiona main ni despliega servicios de producción.

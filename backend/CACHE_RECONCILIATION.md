# Conciliación verificable de caché legacy — entrega 56

La API independiente `/api/v1/reconciliation` permite revisar la cadena registrada
en `financials` y, con autorización y evidencia vigente, reconstruir exclusivamente
`riders.wallet_balance`. Antes de esta entrega su módulo se importaba, pero no se
montaba en `main`. El montaje incorpora cinco rutas a la aplicación real.

Esta comprobación verifica aritmética y continuidad de registros existentes.
No verifica liquidación bancaria, identidad de una moneda, recibos de un proveedor,
integridad frente a operaciones nunca registradas ni la contabilidad completa del
negocio. La respuesta declara `external_settlement_verified=false` y moneda `null`.

## Almacenes y alcance

| Almacén | Papel | Efecto de una sincronización explícita |
| --- | --- | --- |
| `financials` | Historial legacy con importe, tipo, estado y snapshots | Solo lectura; no se crean ni editan asientos |
| `riders.wallet_balance` | Caché decimal derivada de ese historial | Único importe que puede actualizarse |
| `riders.version` | Versión entera de concurrencia | Se incrementa una vez al reparar |
| `audit_logs` | Evidencia de la operación administrativa | Un registro `CONFIG_CHANGE`, atómico con la reparación |
| `RiderWallet` / `FinancialTransaction` | Wallet y transacciones del subsistema moderno | No se modifican |

Los dos subsistemas monetarios no se unifican en esta entrega. No se ejecutan
retiros, reservas, pagos, ajustes contables, transferencias o emisiones fiscales.
Tampoco se añaden tablas, columnas, migraciones, dependencias o flags.

`financials` carece de moneda. Los importes individuales se devuelven como strings
decimales de dos posiciones, sin convertirlos a float. No se suman diferencias
entre repartidores: `total_discrepancy_amount=null`. El campo de compatibilidad
`total_adjusted_amount="0.00"` significa que el lote de consulta no ajustó nada.

## Rutas y permisos

| Método y ruta relativa | Permisos | Comportamiento |
| --- | --- | --- |
| `GET /wallet/{rider_id}` | SUPERADMIN, GERENTE | Previsualiza caché y evidencia |
| `POST /wallet/{rider_id}/sync` | SUPERADMIN | Consulta por defecto; aplica solo con `dry_run=false` y cuerpo válido |
| `GET /batch/daily` | SUPERADMIN, GERENTE | Página de previsualizaciones actuales |
| `POST /fix-all-discrepancies` | SUPERADMIN | Página de consulta por defecto; aplicación masiva rechazada con 409 |
| `GET /audit/ledger-integrity` | SUPERADMIN, AUDITOR | Página con integridad del historial, sin los importes de caché |

Todas llevan el prefijo `/api/v1/reconciliation`. Se utiliza la autenticación real
de la aplicación y su comprobación de actividad, rol y versión de token. Antes de
aplicar se vuelven a leer esos valores de la base de datos bajo bloqueo compartido
del usuario; una desactivación, revocación o pérdida de privilegios invalida la
operación aunque la autenticación inicial ya se hubiera completado.

Los endpoints previos `/financial/reconciliation` y `/fiscal/reconciliation` tienen
otros contratos. El helper privado legacy
`FinancialService.reconcile_wallet_with_ledger` conserva su comportamiento por
compatibilidad y no se usa para la nueva sincronización pública. Esa coexistencia
requiere revisión futura de sus consumidores internos.

## Qué significa un historial verificado

El servicio lee la caché y hasta 10.001 filas del historial mediante una sola
sentencia SQL por repartidor. Analiza como máximo 10.000; la fila adicional detecta
truncamiento. El orden es `created_at ASC NULLS FIRST, id`.

- `PROCESADO` y `PAGADO` afectan al saldo analizado.
- `PENDIENTE` y `RECHAZADO` se cuentan como ignorados. Sus importes y snapshots no
  se certifican aritméticamente.
- Un estado desconocido o nulo exige revisión.
- Los tipos legacy de crédito y débito tienen dirección explícita; `AJUSTE`
  conserva el signo. Los tipos modernos sin correspondencia explícita y los tipos
  desconocidos no se interpretan como créditos.
- Cada importe debe ser finito, distinto de cero, de precisión exacta en centavos
  y estar dentro de ±99.999.999,99. Los snapshots deben ser finitos y válidos.
- El primer asiento procesado debe partir de cero. Un saldo de apertura diferente
  requiere revisión; no se inventa ni se certifica una apertura faltante.
- Cada `balance_before` debe igualar el `balance_after` procesado anterior y el
  nuevo saldo debe corresponder al importe y dirección del asiento.
- Las fechas procesadas deben existir, aumentar estrictamente y no exceder el
  reloj UTC de evaluación en más de cinco segundos. Empates requieren revisión.
- Una cadena truncada siempre requiere revisión. El límite incluye filas
  pendientes o rechazadas, aunque no afecten al saldo.

`verified` significa únicamente que estas comprobaciones pasan sobre la cadena
registrada. `requires_review` impide obtener un saldo verificado. `no_evidence`
significa que no hay asientos procesados; **no equivale a saldo cero**. Se devuelve
el número total de incidencias y hasta las primeras 50, con indicador de recorte.
Los detalles no incluyen descripciones libres ni referencias bancarias del ledger.

La caché puede estar `ok`, `within_tolerance`, `discrepancy`, `requires_review` o
`no_ledger_evidence`. Una diferencia de hasta 0,01 conserva la tolerancia legacy y
no causa escritura. Una caché nula puede reconstruirse si el historial está
verificado; una caché no finita o versión inválida exige revisión. La versión
máxima de int32 bloquea reparaciones para evitar desbordamiento.

## Procedimiento de consulta y reparación

1. Consultar `GET /api/v1/reconciliation/wallet/{rider_id}`.
2. Revisar `status`, `can_apply`, los importes y `integrity`. No aplicar si hace
   falta esclarecer historial, moneda o movimientos reales.
3. Enviar como SUPERADMIN el `version` y `fingerprint` de esa misma respuesta,
   con un motivo de entre ocho y 500 caracteres:

```http
POST /api/v1/reconciliation/wallet/{rider_id}/sync?dry_run=false
Content-Type: application/json
Authorization: Bearer <token vigente>

{
  "expected_version": 0,
  "expected_fingerprint": "<copiar los 64 caracteres hexadecimales de fingerprint>",
  "reason": "Revisión del historial y reparación de caché"
}
```

El marcador de huella del ejemplo debe reemplazarse por el valor real; no es una
petición ejecutable tal como está escrita. No se acepta `target_balance` ni campos
adicionales. La versión es un entero estricto, no un booleano o string; el motivo
se recorta y rechaza controles Unicode. El objetivo se calcula en el servidor.

La huella SHA-256 enlaza repartidor, caché, versión, registros y resultado de la
evaluación. Es evidencia de estado para concurrencia optimista; no es una firma,
un recibo de pago ni una credencial. Cambiar registros, caché, versión o evaluación
invalida la previsualización, incluso si el saldo final coincide.

La transacción toma los bloqueos en este orden: usuario compartido, repartidor
`FOR UPDATE`, filas existentes de `financials` `FOR UPDATE`. Después vuelve a leer
y evaluar la evidencia. El bloqueo del padre serializa los escritores canónicos
y las inserciones que cumplen la FK; los bloqueos de filas protegen frente a
actualizaciones y eliminaciones directas de los registros existentes. Se prueba
este comportamiento en PostgreSQL real, incluidas inserciones por FK.

Si la evidencia coincide y hay discrepancia válida, se actualizan la caché y
versión mediante condición de versión y se inserta el audit log en la misma
transacción. Un fallo de flush o commit revierte ambos. La respuesta incluye el
identificador de auditoría y declara `ledger_changed=false` y
`modern_wallet_changed=false`. Un saldo correcto o dentro de tolerancia devuelve
`no_change`, sin incrementar versión ni crear auditoría de reparación.

Una repetición exacta de la operación solo devuelve `already_applied` si coincide
con un audit log exitoso del mismo actor, motivo, huella y versión originales, y
el estado resultante y la evidencia continúan intactos. Devuelve el mismo audit
id. Si cambian el ledger o la caché después, la petición antigua recibe 409.
Este recibo local no sustituye una conciliación bancaria externa.

| Respuesta | Significado operativo |
| --- | --- |
| 200 | Consulta, reparación confirmada, repetición reconocida o ninguna diferencia aplicable |
| 401 / 403 | Credenciales/cuenta inválidas o permisos insuficientes |
| 404 | Repartidor inexistente |
| 409 | Evidencia obsoleta/no verificable o intento de aplicación masiva |
| 422 | Parámetros/cuerpo inválidos o fecha histórica no soportada |
| 428 | Se solicitó aplicar sin cuerpo de revisión |

Ante 409 se debe obtener otra previsualización y revisar el cambio. No se debe
reintentar automáticamente fabricando una nueva prueba para forzar la corrección.

## Páginas y auditoría

`limit` admite de uno a 25 repartidores; `after_id` es un cursor UUID ascendente.
`next_after_id` permite avanzar cuando `has_more=true`. Se incluyen todos los
estados de repartidor por defecto; `rider_status` aplica un filtro explícito.
Los contadores describen solo la página devuelta, no la flota completa.

`batch/daily` consulta el estado actual UTC. `target_date` solo puede ser el día
UTC actual: no hay snapshots históricos de esta caché. Cada repartidor tiene su
propia lectura atómica, pero la página completa no es un snapshot global.
`audit/ledger-integrity` devuelve la evaluación del ledger por repartidor y sus
contadores. `verified_page` no certifica toda la flota o liquidaciones externas.
El endpoint con nombre histórico `fix-all-discrepancies` no hace correcciones
masivas; `dry_run=false` se rechaza y exige revisiones individuales.

## Contratos y validación

La aplicación pasa de 197 a 202 entradas de rutas, con cinco adiciones y 194
definiciones de dependencia. El baseline anterior permanece intacto; la prueba
compara sus rutas y dependencias y reconstruye el hash OpenAPI previo retirando
solamente las cinco rutas y nueve componentes nuevos. Se conserva el contrato
de los endpoints existentes y se evita un segundo montaje del router.

El nuevo inventario vive en
`tests/fixtures/api_surface_after_reconciliation.json`. Los casos de
`tests/test_cache_reconciliation.py` cubren análisis puro, tipos y límites,
permisos HTTP con JWT real, revocación, paginación, lectura sin efectos,
reparación exclusiva de caché, auditoría, rollback e intercalaciones concurrentes
en PostgreSQL. Las pruebas anteriores de conciliación conservan los casos del
helper privado y actualizan el contrato público para la revisión explícita.
Los resultados completos de la entrega se registran en el informe raíz.

## Límites y trabajo posterior

Revisar los datos históricos que resulten bloqueados, la moneda y la procedencia
de saldos antes de cualquier corrección operativa. La continuidad desde cero no
puede detectar una historia fabricada coherente o eventos nunca registrados.
Debe evaluarse la inmutabilidad, exhaustividad y unificación de los dos libros.
La entrega 57 endurece el escritor compartido: rechaza tipos sin dirección,
importes imprecisos e historial no verificable antes de añadir movimientos.
Comparte este mismo análisis; consulte [escritura y límites operativos](LEGACY_LEDGER_WRITES.md).

El límite de filas acota materialización, análisis y tamaño de respuesta; no
garantiza una duración máxima de SQL o espera de bloqueos. Revisar planes,
índices, tiempos, volumen de páginas y concurrencia en staging antes de operación
a escala. No se incorpora UI, ejecución masiva automática, scheduler, job,
migración histórica ni certificación financiera externa. Persisten criterios
globales de tipado, cobertura, carga, observabilidad, outbox, sesiones por
dispositivo, adaptadores y homologación de proveedores/fiscal.

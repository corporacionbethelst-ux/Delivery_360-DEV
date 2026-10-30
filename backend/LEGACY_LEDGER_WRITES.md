# Escritura contable y cierre transaccional de entregas — entrega 57

La escritura de `financials` se concentra en `FinancialService.create_ledger_entry`.
Antes de añadir una operación nueva, valida sus datos y revisa la cadena registrada
bajo bloqueos. Las rutas de órdenes y entregas dejan de construir filas Financial
directamente. Completar o fallar una entrega, actualizar la orden, congelar el bono
y crear su asiento forman una sola unidad de confirmación.

No se añaden tablas, columnas, migraciones, dependencias, rutas o flags. El
inventario de 202 entradas y el hash OpenAPI de la entrega 56 permanecen intactos.
El informe raíz contiene los resultados completos y el estado del CI por separado.

## Un solo criterio sobre la evidencia registrada

`app/services/legacy_ledger.py` contiene las direcciones legacy, precisión, límites,
LedgerEntry y el análisis puro que antes vivía en cache_reconciliation. Los imports
anteriores de los servicios mantienen sus nombres de compatibilidad. La política
`recorded-financials-chain-v1` y el algoritmo de huella no cambian.

El escritor y la [conciliación de caché](CACHE_RECONCILIATION.md) utilizan los mismos
criterios: estados con impacto, importe exacto, apertura desde cero, aritmética,
continuidad, snapshots completos, fechas procesadas inequívocas y tipos admitidos.
Esto verifica solo los registros existentes, no su origen, exhaustividad, moneda
o liquidación bancaria. No constituye una certificación contable externa.

`get_current_balance` conserva su interfaz y fallback histórico para lectores.
**Ya no determina la apertura de nuevas escrituras.** El helper privado de
reconciliación legacy también conserva su interfaz; no sustituye la reparación
administrativa explícita de la entrega 56.

## Tipos y precisión de entrada

| Dirección | Tipos admitidos en financials |
| --- | --- |
| Crédito: valor absoluto positivo | PAGO_ENTREGA, PAGO_INTENTO_FALLIDO, BONO_RENDIMIENTO, INGRESO, BONO |
| Débito: valor absoluto negativo | PENALIZACION, RETIRO, AJUSTE_MANUAL, DESCUENTO |
| Signo explícito | AJUSTE |

Los otros ocho miembros del enum compartido de tipos modernos se rechazan en este
libro, incluso con estado pendiente o rechazado. No se inventa una dirección para
STRIPE_PAYOUT, BANK_TRANSFER o WALLET_ADJUSTMENT. Sus contratos del subsistema
moderno no se modifican. `ledger_delta` tampoco tiene un fallback genérico.

La ingestión monetaria exige importe finito, no cero, dentro de ±99.999.999,99 y
con precisión exacta de centavos. Booleanos, NaN, infinitos y fracciones de centavo
se rechazan antes de hacer IO de base de datos. Por ejemplo, `"10.235"` ya no
se convierte silenciosamente en `10.24`. El snapshot de apertura explícito admite
cero, pero debe ser exacto, finito, estar dentro de rango y coincidir con la prueba.
`commit` debe ser un booleano real; `"false"`, cero y uno no deciden la propiedad
de una transacción.

`money()` conserva su función histórica de redondeo para cálculos explícitos.
La existencia de esa utilidad no convierte una entrada de ledger imprecisa en
válida: los importes recibidos por el escritor se validan sin redondearlos.

| Campo de trazabilidad | Validación previa a SQL |
| --- | --- |
| description | String opcional, máximo 500 caracteres, acorde al DTO existente |
| reference_id | String opcional, máximo 100 |
| source_type / source_id | Strings opcionales, máximos 50 / 100 |
| idempotency_key | String opcional, máximo 100, se recorta y no puede quedar vacío |
| rider_id / created_by_user_id | Identificadores UUID válidos; actor opcional |

Los textos rechazan NUL y strings que no puedan codificarse en UTF-8. Los campos
descriptivos no se recortan ni se reescriben para ocultar colisiones. Los límites
son de aplicación; description sigue siendo Text en la base de datos.

## Escritura y límites operativos

1. Validar identidad, tipos, estado, importe, apertura explícita y metadatos.
2. Abrir savepoint y bloquear el repartidor `FOR UPDATE`.
3. Buscar una operación con la clave global. Si existe, comparar los campos de
   identidad persistidos. Si se presentó apertura explícita, también debe coincidir
   con su snapshot. Un reintento exacto devuelve el mismo registro; no añade otro.
4. Para una operación nueva, leer y bloquear las filas mínimas de financials en
   orden `created_at ASC NULLS FIRST, id` y verificar la cadena registrada.
5. Derivar la apertura verificada, calcular la dirección, verificar el rango de
   cierre y asignar un timestamp que no invierta el orden contable.
6. Insertar, flush y confirmar solo si `commit=True`. Un savepoint protege la
   transacción externa ante una carrera por clave global.

La lectura del escritor materializa como máximo **10.000 registros**. Si ya hay
10.000, bloquea la operación nueva con **409**, antes de producir una cadena que
supere el límite verificable. Una historia corrupta o no verificable también
devuelve 409. Se mantiene el rechazo previo de cronología futura excesiva como
error de validación. No se repara ni borra el historial para permitir la escritura.

Este límite es una barrera conservadora que puede detener nuevas operaciones de
repartidores con mucho historial. **Debe revisarse el volumen real y definirse una
verificación escalable/checkpoints confiables antes de desplegarlo en producción.**
No se presenta como una solución de rendimiento para flotas de cualquier tamaño.
El límite acota memoria/filas; no garantiza tiempo máximo de SQL o espera de locks.

Si no hay movimientos procesados y no hay incidencias, el escritor puede iniciar
un nuevo libro desde cero con la primera operación válida. No usa el valor de la
caché como apertura. Esta regla de creación no autoriza a poner una caché existente
a cero: la conciliación de caché vacía continúa respondiendo `no_evidence`.
PENDIENTE y RECHAZADO no afectan al saldo analizado; estados desconocidos bloquean.

El reintento de una operación ya registrada devuelve su recibo de identidad aun
si después se dañó otra parte del historial. No significa que la cadena actual
esté verificada. Cualquier movimiento nuevo sí exige una prueba vigente.

`commit=False` deja la propiedad de la unidad en el caller: una falla del ledger
revierte su savepoint y no confirma cambios ajenos. El caller debe revertir la
unidad completa si no puede finalizar su operación. `commit=True` conserva el
rollback del servicio frente a errores, cancelaciones y fallo de confirmación.

## Entrega, orden y bono como unidad

| Entrada | Cambios coordinados |
| --- | --- |
| PATCH /api/v1/orders/{id}/status → ENTREGADO | Orden, creación/actualización de entrega y bono |
| PATCH /api/v1/deliveries/{id}/status → COMPLETADA | Orden, entrega, desglose/snapshot y bono |
| PATCH /api/v1/deliveries/{id}/status → FALLIDA | Orden, entrega, causa y bono compensable si corresponde |
| POST /api/v1/deliveries/{id}/complete | Mismos componentes, a través de DeliveryService |
| POST /api/v1/deliveries/{id}/fail | Mismos componentes, a través de DeliveryService |

Las transiciones financieras usan orden de locks **Order → Delivery → Rider →
Financial**. El servicio vuelve a leer Delivery con populate_existing después de
adquirir los locks y comprueba otra vez su estado y OTP. Se vuelve a consultar
actividad/rol del actor y propiedad del recurso después de esperar esos locks.
Una lectura autorizada anterior no basta si la entrega cambió de repartidor.
El guard JWT global conserva la validación de versión de token por petición;
no se introduce un nuevo protocolo de sesiones o una garantía de permisos
irrevocables durante toda la transacción.

CRUDDelivery.update y CRUDOrder.update aceptan `commit=False` como opción keyword:
flush sin confirmación interna. Su valor predeterminado sigue siendo True para
preservar el resto de consumidores. Los cierres del servicio usan False, al igual
que el escritor contable. El servicio hace el commit final y rollback conjunto
ante un error; ya no captura una falla contable para continuar declarando éxito.
Las rutas directas mantienen su confirmación final y la dependencia get_db revierte
las excepciones de la petición.

Las claves por orden siguen siendo `pago_entrega_{order_id}` y
`pago_fallido_{order_id}`. El servicio también las utiliza. Las rutas que encuentran
un bono congelado previo comprueban rider, referencia de orden, tipo, estado
procesado/pagado e importe positivo válido antes de aceptarlo; no vuelven a
calcularlo con la configuración actual. El escritor común mantiene su identidad
exacta de todos los campos cuando recibe un reintento de inserción.

Todos los caminos financieros comprueban que no exista la clave del resultado
contrario para la misma orden, incluso si su registro sigue pendiente. Si existe,
devuelven 409 y exigen revisión; no pagan éxito y fallo por una orden con estados
históricos incoherentes. El endpoint de órdenes también rechaza completar una
orden en curso si su entrega ya figura terminada. Estas barreras usan las claves
conocidas y no identifican automáticamente todos los asientos históricos sin clave.

Completar y fallar simultáneamente no genera ambos bonos: el segundo intento ve
el estado terminal actualizado y se rechaza. El bloqueo de la orden serializa
también el cruce entre su endpoint legacy y los endpoints de entrega. Esto no
reconstruye ni elimina duplicados históricos ya existentes.

## Cálculo del bono y cero explícito

Los componentes de base, zona y nivel se validan como decimales antes de multiplicar.
El resultado se redondea una vez con ROUND_HALF_UP al congelar el importe. El mismo
valor de centavos se entrega al ledger. Por ejemplo, `5.50 × 1.15 = 6.325` produce
**6.33** tanto en DeliveryService como en la ruta unificada; el float anterior
podía producir `6.324999999999999` y terminar en 6.32.

Una recompensa calculada de cero no crea un asiento de importe cero ni inventa
un movimiento. La entrega puede cerrarse y conserva el snapshot correspondiente.
En un fallo de pago cero, bonus_applied=false. La ruta unificada registra también
el snapshot del bono fallido y la advertencia si falta su configuración.

Se conservan diferencias de política previas entre entradas: el helper de órdenes
usa fallback 2.50 cuando falta rider_delivery_bonus; la ruta unificada usa cero
con advertencia; DeliveryService devuelve cero con advertencia ante configuración
ausente o inválida. La configuración inválida de las rutas directas se rechaza
como error de dominio. Homogeneizar esas decisiones de negocio requiere una
política explícita; no se disfraza su coexistencia como paridad completa.

## Pruebas y próximos pasos

Las pruebas nuevas cubren ingestión sin IO ante entradas inválidas, direcciones,
historia corrupta, límites, reintentos, propiedad transaccional y bloqueos reales.
La prueba de arquitectura detecta constructores directos de Financial fuera del
servicio canónico. La suite HTTP usa JWT real, modelos físicos con sus columnas
y tipos reales, y un esquema PostgreSQL privado. Incluye las cinco entradas,
rollback por flush/commit, carreras cruzadas, cuentas desactivadas, cambios de rol
y reasignaciones después de la lectura inicial. Los proveedores post-commit se
sustituyen en pruebas; no hay pagos, mensajes o facturas externos reales.

El montaje de tablas en PostgreSQL usa una copia de MetaData: la creación de FKs
circulares no puede alterar las reglas DDL del metadata ORM productivo en memoria.
Una prueba compara después el contrato SQL completo existente, sin regenerarlo.

La regresión completa se divide por archivos en tres grupos exhaustivos y
disjuntos, cada uno con PostgreSQL/PostGIS y Redis propios. Se comprueba el total
colectado y los hashes del código antes y después; no se excluyen pruebas. Los dos
SDK opcionales se prueban aparte con transporte HTTP sustituido.

Antes de producción siguen pendientes saneamiento de historiales bloqueados,
volumen/índices/esperas, checkpoints confiables e inmutabilidad efectiva,
unificación de libros/moneda y recibos externos. Los jobs y hooks post-commit
necesitan outbox/reintentos durables; esta entrega no garantiza entrega externa
exactamente una vez. Persisten la deuda global de tipado/cobertura y los demás
criterios del roadmap. No se fusiona ni despliega automáticamente esta entrega.

La entrega 58 aborda la cancelación de la orden padre y el cierre coherente de
entrega/ruta. Consulte [cancelación coordinada](ORDER_CANCELLATION.md): requiere
una migración de enum, limita cancelación a gerencia/superadministración y rechaza
evidencia económica previa; no implementa compensaciones ni reembolsos.

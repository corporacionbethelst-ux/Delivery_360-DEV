# Integridad fiscal y previsualización explícita

Entrega 50. El motor genera representaciones locales de prueba y registra su
evidencia. Los adaptadores DIAN/SAT predeterminados **no tienen transporte real
homologado**. Configurar claves o certificados no convierte esos adaptadores en
una integración operativa. No se envían documentos ni se simulan aceptaciones.

## Cambio de comportamiento

Antes, una factura sin credenciales podía guardarse como ACEPTADA con CUFE/UUID
ficticio, PDF stub y enlace de verificación aparente. Una firma fallida podía
sustituirse por un hash simulado. Colombia tenía además un TypeError en el
helper XML al pasar schemeID. Una cancelación cambiaba el estado local sin
confirmación de autoridad y un país sin adaptador usaba silenciosamente Colombia.

Ahora la emisión está deshabilitada por defecto. La previsualización requiere
opt-in, entorno permitido, petición explícita y una resolución marcada sandbox.
Conserva PENDIENTE, no recibe CUFE/UUID ni PDF/QR oficial y lleva evidencia de
simulación. La emisión real se rechaza antes de reservar folio si el adaptador
no declara capacidad real; ninguno de los predeterminados la declara.

La firma RSA configurada falla de forma cerrada: no hay sustitución simulada.
El verificador exige ACK explícito y un identificador no ficticio antes de
registrar aceptación en el flujo preparado para un adaptador real. Las pruebas
que ejercitan esa rama inyectan un adaptador offline; no acreditan integración
con DIAN, SAT o PAC. Esa integración continúa pendiente.

## Configuración y permisos

| Opción / requisito | Default / efecto |
|---|---|
| ENABLE_ELECTRONIC_INVOICING | false; bloquea emisión/previews y el hook automático no emite |
| FISCAL_SANDBOX_ENABLED | false; permiso adicional para preview |
| APP_ENV y ENVIRONMENT | Ambos deben ser development/dev/test/testing/local/sandbox/staging/stage |
| preview en POST /api/v1/fiscal/invoices | false por defecto; se debe enviar true para preview |
| InvoiceResolution.is_sandbox | false por defecto; preview solo selecciona true, flujo real solo false |
| Rol | GERENTE o SUPERADMIN para crear; auditor/operador conservan lectura |

Un único entorno production/prod, vacío o desconocido bloquea el sandbox aunque
el flag esté activo. Activar sandbox no modifica el hook automático para crear
simulaciones: este no pasa preview=true. No se generan previews sin una acción
explícita. Los parámetros de claves/certificados existentes se conservan para
compatibilidad de configuración, pero no habilitan envíos por sí solos.

Las resoluciones de prueba deben prepararse en una base de desarrollo/staging,
con rangos separados y is_sandbox=true. Esta entrega no crea rangos automáticamente
ni añade una pantalla o endpoint de alta de resoluciones. No marque un rango
oficial como sandbox para probar el sistema. El contador inicial recomendado es
start_range - 1; un contador histórico cero se lleva al inicio real del rango.

Petición de ejemplo, con un UUID de pedido existente y un bearer de administración:

```json
{
  "order_id": "<UUID de pedido existente>",
  "customer_name": "Cliente de prueba",
  "customer_tax_id": "NN",
  "country": "MX",
  "preview": true,
  "items": [
    {"name": "Servicio de entrega", "unit_price_cents": 116001, "quantity": 1}
  ]
}
```

Se espera PENDIENTE, execution_mode=sandbox, is_simulation=true,
is_officially_accepted=false y unique_identifier/pdf_url/qr_code_url nulos.
El status endpoint devuelve status_source=local_snapshot; no consulta autoridad.

## Diccionario de la migración

Revisión `20261029_fiscal_integrity`, padre `20261028_auth_version`.

| Campo / índice | Definición | Finalidad |
|---|---|---|
| electronic_invoices.resolution_id | UUID nullable, FK RESTRICT a invoice_resolutions.id | Vínculo exacto para reservas nuevas; históricos sin asociación verificable quedan null |
| electronic_invoices.execution_mode | VARCHAR(20) NOT NULL; default SQL/Python legacy_unverified | Distingue sandbox, real y legacy_unverified |
| ck_invoice_execution_mode | CHECK de esos tres valores | Impide estados de ejecución arbitrarios |
| invoice_resolutions.is_sandbox | BOOLEAN NOT NULL; default SQL/Python false | Separa rangos de prueba de los de emisión |
| idx_invoice_resolution_date | (resolution_id, issue_date) | Apoya el conteo de reservas del día por resolución |

Los 75 campos fiscales anteriores pasan a Mapped con tipos escalares, Decimal,
UUID, enum y nulabilidad real. Se conserva el contrato original de esas columnas,
defaults, enums e índices previos. Las tres tablas sin nuevos campos conservan
su DDL completo. No se cambia el significado de los enums de estado.

La migración clasifica como sandbox solo los registros cuyo pdf_url comienza
por stub://. No cambia su status histórico, importes, identificadores ni fechas.
El resto queda legacy_unverified; no se infiere aceptación a partir de un enlace
HTTPS ni se adivina una resolución. La API conserva esos estados históricos y
expone por separado que no acreditan aceptación oficial. No hay saneamiento
financiero masivo ni reasociación automática de documentos anteriores.

## Numeración, cuota y transacciones

El contador se asigna con UPDATE condicional y RETURNING sobre la fila actual.
El primer valor es start_range y se incrementa una sola vez. Se revalidan estado,
fechas y límite del rango en SQL. Los objetos precargados o de otro worker no
pueden reservar con un contador antiguo. Se consulta también el máximo de los
folios ya registrados, para no reutilizar el valor que el bug histórico había
guardado una unidad por encima del contador.

El flujo completo bloquea la resolución al comprobar la cuota y mantiene ese
lock hasta confirmar contador y fila PENDIENTE. El siguiente worker ve la reserva
confirmada y no puede exceder el límite por una carrera. Se cuentan intentos de
todos los estados: un proveedor fallido no permite eludir el cupo ni reutilizar
folio. Los registros históricos sin FK cuentan conservadoramente contra los
rangos del mismo país e inicio que pudieran corresponderles.

Después del commit de la reserva se libera el lock antes de generar/firmar/enviar.
Un fallo de commit inicial revierte contador y fila juntos. Un fallo posterior
conserva evidencia y termina localmente en RECHAZADA, con mensaje genérico. Una
caída del proceso después de reservar puede dejar PENDIENTE: requiere conciliación,
no borrar/reutilizar el folio. Esto no implementa un worker outbox, un endpoint
idempotente ni exactamente una emisión por pedido; repetir una petición explícita
puede crear otra reserva. No se promete numeración sin huecos.

Se conserva la restricción única legacy país + inicio de rango + secuencia y
las FK anteriores. Esa restricción puede limitar rangos con igual inicio y
prefijos distintos; la política de prefijos/rangos e historial fiscal requiere
otra evolución de esquema. También se conserva la FK legacy del pedido con
ON DELETE CASCADE: la política global de retención de pedidos/facturas continúa
pendiente de revisión; la aplicación no hace borrados de pedidos en esta entrega.

## Importes y documentos

Los inputs monetarios son enteros estrictos en centavos, dentro de BIGINT;
booleanos, floats, negativos o cantidades no enteras se rechazan. Se limitan
cantidad a 1..1000 y detalle a 1..100 líneas. El total agregado se valida antes
de reservar. El pedido inexistente produce 404 sin consumir folio.

El cálculo usa Decimal y ROUND_HALF_UP a centavo entero. El IVA incluido de MX
no se resta del total pagado: base + impuesto incluido coincide exactamente con
el bruto. Varios impuestos incluidos se reparten conservando el residual y sin
importes negativos. Los impuestos externos se suman y las retenciones se restan.
El desglose conserva total_tax_cents para impuestos externos y añade
included_tax_cents; la factura suma ambos para su total de impuestos.

CO usa COP y MX usa MXN. Los inputs ya están denominados en esa moneda y se guarda
exchange_rate=1.0000: no se consulta ni finge una conversión USD/COP. Convertir
entre monedas sigue siendo otro flujo. Las lecturas del pedido usan Decimal,
sin pasar sus importes por float o round bancario. No se recupera precisión que
un llamador ya hubiera perdido antes de entregar un float.

La vista mexicana serializa los importes como strings decimales exactos; su
valor unitario contempla cantidad y seis decimales. El XML colombiano escapa
contenido y admite schemeID sin TypeError. Son representaciones de preview:
no son una implementación certificada de UBL/CFDI, XMLDSig/XAdES, CSD/timbrado o
las reglas fiscales vigentes de cada autoridad. Los defaults tributarios no se
presentan como validación normativa actual.

## Firma, errores y aceptación

sign_document exige clave RSA PEM de al menos 2048 bits y cryptography disponible.
Firma los bytes UTF-8 con RSA PKCS1v15/SHA256. Clave ausente, corrupta, cifrada sin
soporte, débil, EC u otro tipo falla sin hash sustituto. Su uso en el orquestador
va fuera del event loop mediante threadpool. La firma de bytes no equivale por
sí sola a una firma fiscal homologada o a validar el certificado del contribuyente.

Un adaptador futuro debe declarar capacidad real y devolver accepted=true,
identificador no vacío, imprimible y sin prefijos stub/sandbox, y enlaces
opcionales HTTPS válidos. Estas validaciones son estructurales: no prueban por
sí solas autenticidad ante la autoridad. is_officially_accepted refleja el ACK
registrado localmente para modo real; status_source continúa siendo local_snapshot. Respuestas
ambiguas o inválidas quedan sin aceptación; una excepción no filtra rutas de
clave, material privado ni detalle del proveedor en API, fila o logs. Ninguna
clave/certificado se envía con los adaptadores predeterminados: sus métodos de
submit rechazan siempre y se eliminan los endpoints supuestos anteriormente.

RECHAZADA en este flujo es un estado local de fallo sin aceptación verificable;
no acredita que la autoridad haya rechazado el documento. El estado público
siempre indica fuente local. Las notas crédito exigen evidencia de aceptación
real; una aceptación legacy o sandbox no basta. La cancelación externa no está
homologada y no cambia a CANCELADA solo porque se solicite en el sistema.

## Puesta en servicio y pruebas

Definir explícitamente ENABLE_ELECTRONIC_INVOICING=false en todos los workers,
incluidos los antiguos, antes del cambio. Retirar los workers anteriores antes
de considerar efectivos los controles; una ventana mixta conserva rutas viejas
que podían simular aceptación. Aplicar la nueva revisión antes del código que
selecciona sus columnas. Probar en
una copia de staging la cadena histórica y los datos antes de desplegar; esta
entrega verifica las operaciones aisladas de upgrade/downgrade con PostgreSQL y
filas antiguas, no certifica toda la cadena desde cero. No se aplica en producción.

El downgrade bloquea ambas tablas y rechaza eliminar datos de ejecución si ya
hay asociaciones, clasificaciones nuevas o resoluciones sandbox. Volver al código
que simulaba aceptaciones también pierde las protecciones aunque las columnas
sigan presentes; requiere un rollback auditado. No se automatiza limpieza de
históricos para permitirlo ni se reinician contadores.

Las pruebas generan claves de prueba en directorios temporales y sustituyen el
proveedor para comprobar la rama de ACK. Verifican RSA criptográficamente,
conservación de centavos, XML/JSON, rangos, concurrencia y cuota, rollback,
permisos, migración y snapshots. No se conectan a DIAN, SAT/PAC ni se envían
facturas, pagos, correos, SMS o PUSH reales.

Pendientes: transporte/homologación DIAN o PAC/SAT con contrato y credenciales
válidos, certificados/firmas fiscales, consulta/cancelación externa verificable,
reglas normativas actualizadas, outbox/conciliación, idempotencia de emisión,
retención/auditoría integral, alta/revisión de resoluciones en UI y revisión de
restricciones legacy de prefijos y moneda. Esta entrega corrige integridad y
transparencia del flujo; no declara facturación productiva al 100 %.

# Registro de integraciones y diagnóstico local — entrega 54

## Finalidad

La API registra integraciones, consulta metadatos, permite cambios administrativos
y pausa su programación registrada. Conserva el historial y genera auditoría
transaccional. Una fila ACTIVE, una URL configurada o una fecha de sincronización
no constituyen prueba de una conexión externa válida.

Esta entrega no activa proveedores, verifica credenciales, ejecuta sincronizaciones
ni envía webhooks. Los adaptadores homologados, configuración segura, transporte
con restricciones de destino, recibos verificables y procesamiento durable siguen
pendientes. El diagnóstico informa explícitamente `performed=false`.

## Problemas corregidos

- El montaje anterior repetía `/integrations` y leía `type`/`is_active`, atributos
  inexistentes del modelo. Se usan `integration_type` y `status` reales.
- Los identificadores de servicio eran enteros a pesar de las PK/FK UUID.
- Crear una integración pasaba un diccionario a TEXT y un argumento `last_sync`
  inexistente. Se elimina ese argumento y se serializa JSON interno de forma acotada.
- `test_connection` anunciaba éxito para tipos sin implementación. Ya no produce
  éxitos por defecto ni filtra excepciones del proveedor.
- El servicio de sincronización construía conectores con dominios de ejemplo y
  no elegía la configuración del registro. Esas delegaciones se rechazan hasta
  contar con un adaptador verificado.
- La API pública selecciona campos explícitos e indicadores de presencia en SQL,
  sin cargar entidades ORM con secretos para construir la respuesta.

## Contratos HTTP y permisos

Todas las rutas de la tabla incluyen `/api/v1/integrations` como prefijo.

| Método y sufijo | Acceso | Efecto |
| --- | --- | --- |
| `GET ""` | SUPERADMIN, GERENTE | Lista de metadatos |
| `GET /{integration_id}` | SUPERADMIN, GERENTE | Detalle por UUID |
| `GET /{integration_id}/diagnostics` | SUPERADMIN, GERENTE | Diagnóstico local, sin contacto externo |
| `POST ""` | SUPERADMIN | Crea un registro INACTIVE, con sync deshabilitado |
| `PATCH /{integration_id}` | SUPERADMIN | Modifica nombre, proveedor o frecuencia registrada |
| `POST /{integration_id}/pause` | SUPERADMIN | INACTIVE, sync deshabilitado y siguiente ejecución retirada |

`GET /api/v1/integrations/` y el alias histórico
`GET /api/v1/integrations/integrations` comparten el handler de listado y sus
permisos, y se omiten en OpenAPI. No se mantienen los CRUD de demostración del
módulo antes no montado. No hay endpoints para activar, borrar, enviar, guardar
secretos o consultar payloads/headers de webhook.

Se comprueban JWT, versión de credenciales, rol y cuenta vigentes en base de datos.
OPERADOR, AUDITOR, CLIENTE y REPARTIDOR no pueden consultar este registro. GERENTE
puede consultar, pero no modificar. No basta un rol antiguo en un token.

Listado: `integration_type` y `status` son enums; `limit` es 1–100, por defecto 50;
`skip` es 0–10000, por defecto cero. Devuelve un array, ordenado por nombre e ID
para desempates estables. La paginación no ofrece un total global ni una fotografía
estable frente a inserciones concurrentes.

## Entradas administrativas

Crear admite `name`, `integration_type`, `provider` opcional y
`sync_frequency_minutes` opcional, por defecto sesenta. Nombre y proveedor se
recortan; el nombre debe tener entre uno y cien caracteres visibles, el proveedor
hasta cincuenta. Se rechazan controles/caracteres de formato incrustados. Un
proveedor vacío se convierte en null. La frecuencia exige un entero estricto
entre uno y 1440; bool no se acepta como entero.

La creación siempre queda INACTIVE, `sync_enabled=false`, sin configuración de
conexión ni secretos recibidos por HTTP. `created_by` es el usuario autenticado.
Una fila creada no representa una cuenta habilitada en un proveedor.

PATCH admite solo nombre, proveedor y frecuencia. Exige al menos un campo;
omitir proveedor lo conserva y enviarlo null lo limpia. Nombre/frecuencia null
se rechazan. Tipo, estado, flags de sync, URLs, credenciales, config y secretos no
son campos editables. Propiedades desconocidas se rechazan con 422.

Cambiar frecuencia exige INACTIVE y `sync_enabled=false`; en otro caso devuelve
409 y exige pausar primero. Nombre/proveedor son etiquetas y pueden cambiar sin
alterar el estado registrado. La frecuencia solo se almacena; no se programa un
job ni se habilita Beat en esta entrega.

## Diccionario público

| Campo | Tipo | Significado |
| --- | --- | --- |
| `id` | UUID | Identificador de integrations |
| `name` | texto | Etiqueta registrada |
| `integration_type` | enum | ERP, POS, PAYMENT, MAPS, SMS o EMAIL |
| `type` | enum | Alias compatible de integration_type |
| `provider` | texto o null | Etiqueta del proveedor |
| `status` | enum o null | ACTIVE, INACTIVE o ERROR histórico |
| `is_active` | booleano | El estado registrado es ACTIVE; no es una prueba de conexión |
| `sync_enabled` | booleano o null | Flag almacenado, sin garantía de worker ejecutándose |
| `sync_frequency_minutes` | entero o null | Frecuencia almacenada; valores históricos no positivos se exponen null |
| `consecutive_failures` | entero o null | Contador almacenado; negativos históricos se exponen null |
| `last_sync_at` | timestamp o null | Fecha almacenada, sin recibo externo certificado |
| `last_error_at` | timestamp o null | Fecha del error registrado, sin su texto |
| `sync_last_run`, `sync_next_run` | timestamp o null | Última/siguiente ejecución registradas |
| `created_at`, `updated_at` | timestamp o null | Fechas almacenadas |
| `created_by` | UUID o null | Usuario creador registrado |
| `has_endpoint` | booleano | Presencia de api_url |
| `has_credentials` | booleano | Presencia de credentials |
| `has_config` | booleano | Presencia de config |
| `has_webhook` | booleano | Presencia de webhook_url |
| `has_signing_secret` | booleano | Presencia de webhook_secret |
| `has_last_error` | booleano | Presencia del texto de error |
| `connection_verified` | false | No hay evidencia de conexión homologada en este contrato |

Las fechas UTC persistidas sin zona horaria se devuelven con offset UTC. Los nulos
históricos no se sustituyen por fechas o valores de éxito. Los indicadores has_*
solo señalan presencia de texto; no certifican JSON válido, URL segura, credencial
vigente, firma o capacidad de conexión.

La proyección y los DTO excluyen credentials, config, api_url, webhook_url,
webhook_secret, auth_type, token_expires_at, last_error_message y cualquier
payload/header/respuesta de WebhookEvent. Ni el detalle ni el listado ni el
diagnóstico ofrecen esos datos. Los valores siguen almacenados en sus columnas
existentes y no se modifican automáticamente.

## Diagnóstico honesto

Retorna `integration_id`, `status`, `outcome=not_checked`, `performed=false`,
`connection_verified=false`, `synchronization_available=false` y motivos locales.
Siempre informa `verified_adapter_required`; puede añadir `registry_inactive`,
`legacy_sync_flag_requires_review`, `endpoint_not_recorded` y
`credentials_not_recorded` según los campos observados.

No resuelve DNS, abre sockets, sigue URLs, llama /health ni modifica el estado o
los contadores. Por ello tampoco comprueba conectividad ni salud del proveedor.
No se envía un error privado del proveedor como diagnóstico público.

## Transacciones, concurrencia y conservación

Creación, PATCH y pausa guardan su cambio y AuditLog en la misma transacción.
Un error revierte ambos. AuditLog usa CREATE, CONFIG_CHANGE o STATUS_CHANGE,
resource_type=integration, ID UUID como texto y actor autenticado. Registra solo
los campos administrativos afectados. No copia config, secretos, URLs, payloads,
headers ni errores del proveedor.

PATCH y pausa bloquean la fila con FOR UPDATE y vuelven a evaluar el estado bajo
el lock. Dos pausas concurrentes generan un único cambio/auditoría. Dos cambios
de campos diferentes conservan ambos campos. Repetir el mismo PATCH sin cambios
no añade otra auditoría ni reescribe updated_at.

Pausar conserva credenciales, config, último sync, errores y eventos existentes.
Retira sync_next_run y el flag de programación. No cancela una operación que ya
esté ejecutándose en otro proceso; futuros consumidores deben respetar la pausa
y definir cancelación/reclamación. No hay borrado de registros ni de eventos.

POST no incorpora una clave de idempotencia y puede crear dos registros ante dos
solicitudes. Se permiten etiquetas duplicadas, como en el esquema anterior.
No se declara una garantía global de exactamente una vez.

## Servicio interno y envíos pendientes

El servicio usa UUID y conserva sus nombres principales. `get_integration` es una
lectura ORM interna; la API usa get_summary/list_integrations con DTO públicos.
El listado del servicio devuelve ahora esos DTO y tiene límites explícitos.

La creación interna admite configuración objeto JSON opcional, la valida sin NaN,
infinito, claves no textuales, objetos arbitrarios o ciclos, y serializa TEXT de
hasta 64 KiB UTF-8. Esta compatibilidad interna no expone provisión de configuración
por HTTP ni añade cifrado al almacenamiento histórico. Activación enabled=true
y cambios de estado distintos de INACTIVE se rechazan.

test_connection devuelve success=false/performed=false incluso para tipos antes
sin implementación. sync_with_pos/sync_with_erp devuelven rechazo explícito
verified_adapter_required; trigger_webhook devuelve false sin contactar el destino.
No se imprimen datos de pedidos, dinero, destinos ni errores con información privada.

register_webhook_event solo conserva eventos internos no confirmados, con UUID,
enum admitido, JSON acotado y código HTTP válido opcional. success=true se rechaza
porque falta evidencia externa verificable. El registro no implica un envío,
no programa reintentos y no representa un recibo del proveedor.

Las clases de prototipo en app/integrations mantienen trabajo pendiente: usan
contratos genéricos y no constituyen adaptadores homologados. No se conectan desde
esta API ni desde las delegaciones bloqueadas del servicio. Antes de usarlas se
requieren políticas de destino, DNS/SSRF, autenticación por proveedor, firmas,
eventos durables, límites de tiempo, reintentos e idempotencia con evidencia.

## Esquema SQL y pruebas

Se tipan 24 columnas de integrations y trece de webhook_events con Mapped y
mapped_column. Se conserva PostgreSQL DDL, UUID, nulabilidad, enums, defaults,
onupdate, FK e índices. El baseline anterior a la conversión está en
tests/fixtures/orm_integration_baseline.json. No hay migración en esta entrega.

Integrations conserva identidad/etiquetas, campos de conexión privados, estado,
fallos, configuración TEXT, programación, timestamps y creador. WebhookEvent
conserva identidad, integración, tipo, payload/headers JSON, resultado, respuesta,
error, fecha y reintentos. El esquema heredado no incorpora cifrado automático,
outbox ni prueba de aceptación del proveedor.

tests/test_integration_registry.py combina contrato SQL, validación pura y pruebas
PostgreSQL en esquemas privados sobre una base test_* explícita. Usa la aplicación
montada con JWT/middleware reales y prohíbe construir HTTPX AsyncClient para
detectar contactos externos. Comprueba permisos, revocación, proyección, fechas,
creación/pausa, rollback, concurrencia, nulabilidad y fallos honestos. El informe
raíz contiene los resultados finales y la deuda global de CI.

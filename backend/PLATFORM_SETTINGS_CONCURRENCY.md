# Configuración: revisiones y guardado concurrente

La entrega 86 cierra la carrera entre la lectura previa del cliente y el guardado
de configuración. La API exige la revisión consultada y la compara dentro de la
misma transacción que actualiza los valores y registra su auditoría.

## Contrato HTTP

1. `GET /api/v1/settings` devuelve los campos existentes y `revision`, un token
   opaco con formato `s1-` seguido por 64 dígitos hexadecimales. El cliente debe
   conservar el token recibido, sin calcularlo ni interpretarlo como una fecha.
2. `PATCH /api/v1/settings` envía únicamente los campos editados y el encabezado
   `If-Match: "s1-…"`, incluidas las comillas. `PUT` y las variantes con barra
   final exigen la misma precondición y conservan el comportamiento de actualización
   parcial del contrato anterior.
3. Una respuesta 200 contiene los valores confirmados y su nueva revisión. Un
   error de transporte después de enviar la petición puede representar un
   resultado incierto; consultar antes de repetir.

| Estado | Significado y recuperación |
| --- | --- |
| 400 | Revisión malformada, débil, múltiple o comodín; no se admite omitir la comparación. |
| 403 | El rol no permite guardar; solo SUPERADMIN puede hacerlo. |
| 412 | La revisión ya cambió. Recargar y volver a revisar el borrador antes de guardar. |
| 422 | Campos no permitidos o valores inválidos; tampoco se aceptan números no finitos. |
| 428 | Falta If-Match. Consultar la configuración y enviar su revisión. |

El GET sigue reservado a SUPERADMIN y GERENTE. Los permisos se comprueban antes
de ejecutar el handler. El encabezado If-Match ya está permitido por CORS.

## Transacción y revisión

Los ocho registros de configuración se cargan y bloquean con `SELECT … FOR
UPDATE` en orden de clave. Se refresca la identidad ORM para no comparar contra
una lectura anterior retenida en la sesión. Todos los escritores de estos
endpoints usan el mismo orden y conservan el bloqueo hasta el commit.

La revisión depende de las claves esperadas, sus valores, la fecha de actualización
y su actor. Los números JSON equivalentes como 0 y 0.0 se normalizan para que una
recarga no cambie el token por la representación del motor. La fecha de una
escritura avanza al menos un microsegundo respecto de la última guardada, incluso
si el reloj retrocede. Esto permite detectar un cambio seguido de una reversión.

Dos escritores con la misma revisión tienen un único ganador. El otro compara
contra el estado confirmado por el primero y recibe 412, sin guardar su payload
ni añadir una auditoría de éxito. La escritura y la auditoría son parte de una
sola transacción; un fallo debe provocar rollback de ambas. La respuesta se
captura después del flush y antes del commit para identificar exactamente la
operación confirmada, sin una lectura posterior que pueda observar otro escritor.

Las claves ausentes se inicializan con JSON null mediante `INSERT … ON CONFLICT
DO NOTHING`, en orden estable, sin inventar importes. Las lecturas iniciales
simultáneas no fallan por duplicar la clave primaria. Este mecanismo conserva la
inicialización que ya realizaba el GET; no requiere migraciones ni columnas nuevas.

## Interfaz y actualización de clientes

El frontend conserva su consulta previa: si cambió un campo editado desde que se
abrió el formulario, detiene el guardado. Si solo cambió otro campo, utiliza la
revisión fresca y envía su payload parcial. Un cambio posterior a esa consulta
se detecta ahora en el servidor, aunque sea de otro campo de configuración.

Ante 412, se muestra el conflicto, se conserva el borrador y se bloquea el
reintento. Recargar pide elegir entre conservar el borrador o descartarlo
explícitamente. Conservarlo no autoriza escribir con una revisión obsoleta.
El servicio rechaza lecturas sin una revisión válida y no realiza escrituras
sin ella. Se mantienen la protección de sesiones y las guardias de duplicados.

**Compatibilidad:** clientes anteriores que escriben sin If-Match recibirán 428.
Actualizar todos los consumidores de escritura junto con la API. El frontend
nuevo requiere la API nueva; coordinar la actualización de ambos. Las lecturas
anteriores siguen recibiendo sus campos, con la revisión adicional. No se ha
realizado ningún despliegue ni migración desde esta entrega.

## Pruebas y alcance

`tests/test_platform_settings_contract.py` verifica las cuatro rutas de escritura,
validación, permisos, lectura estable, acuses, auditoría y revisiones obsoletas.
`tests/test_platform_settings_postgresql.py` usa sesiones y conexiones independientes
para probar carreras de inicialización, un solo ganador, refresco del estado ORM
y rollback de valores y auditoría. Exige `TEST_DATABASE_URL` explícita con una
base PostgreSQL cuyo nombre empiece por `test_`; crea y elimina solo su esquema
privado. No usa DATABASE_URL como sustituto para elegir una base de integración.

Las pruebas SQLite verifican el contrato HTTP; no demuestran bloqueos de fila.
La garantía de concurrencia se comprueba en PostgreSQL, el motor de producción.
Escrituras SQL externas o nuevos consumidores que omitan este protocolo requieren
su propia coordinación; esta entrega no impide que un administrador de base de
datos altere registros directamente. No modifica la fórmula ni la moneda del
simulador, el formulario original de órdenes ni las reglas de cálculo de bonos.

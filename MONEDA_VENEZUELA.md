# Referencias BCV y cotizaciones USD/VES — entrega 90

Decisión de negocio: Venezuela, base USD y equivalente en bolívares con BCV.
Este incremento cubre referencias y cotizaciones independientes. No migra el
libro anterior ni convierte tarifas, bonos o retiros existentes.

## Uso

En el menú **USD / Bolívares**, gerencia y superadministración registran una
referencia después de consultar BCV. Deben indicar bolívares por dólar, fecha de
la publicación, nota y confirmación explícita. El diálogo permite revisar y
cancelar antes de escribir. Operadores pueden cotizar; no registrar tasas.

El día de uso procede del servidor en `America/Caracas`. Solo se crean nuevas
cotizaciones con una referencia registrada para ese día. En días sin publicación,
una persona autorizada debe comprobar la vigencia de la referencia anterior y
justificarla con una nota de al menos diez caracteres. No hay arrastre automático.

La pantalla admite coma o punto decimal, sin separadores de miles. Al guardar
una cotización, su enlace `?quote=<UUID>` permite recuperar el mismo comprobante
con autenticación. El operador solo recupera los que creó; gerencia,
superadministración y auditoría pueden consultar comprobantes por API. Esta
entrega no añade un portal de auditoría nuevo.

**El origen es manual (`MANUAL_BCV`, `automatically_verified: false`).** No se
presenta como una consulta oficial automática. El acceso HTTPS público al BCV
respondió 503 durante el desarrollo; no se desactivó TLS. El operador debe
consultar y validar la publicación oficial por un medio disponible. El sistema
no puede comprobar por sí mismo que el valor escrito coincide con ella.

## Contrato de API

Todas las rutas requieren sesión vigente y rol autorizado.

| Ruta | Función | Roles |
| --- | --- | --- |
| `GET /api/v1/currency/context` | Día, referencia actual e historial de 20 registros | SUPERADMIN, GERENTE, OPERADOR, AUDITOR |
| `POST /api/v1/currency/rates` | Añadir referencia o corrección | SUPERADMIN, GERENTE |
| `POST /api/v1/currency/quotes` | Conservar cotización | SUPERADMIN, GERENTE, OPERADOR |
| `GET /api/v1/currency/quotes/{id}` | Recuperar comprobante | Consulta; OPERADOR solo propio |

Para registrar una referencia se envían `request_key` UUID, `previous_rate_id`
(UUID de la referencia actual del día, o null), `valid_on`, `reference_date`,
`ves_per_usd` como cadena decimal positiva, `note` y `confirmed_bcv: true`.
Se admiten hasta ocho decimales y nueve cifras enteras en la tasa.

Para cotizar se envían `request_key`, `rate_id`, `amount_usd` como cadena decimal
no negativa de hasta doce cifras enteras y dos decimales, y `reference` de hasta
120 caracteres. Los importes y tasas de respuesta también son cadenas; no se
deben convertir a coma flotante para calcular. El equivalente VES usa HALF_UP a
dos decimales. Por ejemplo, 0,01 USD a una tasa **sintética** 1,5 produce 0,02 VES.

Una revisión anterior causa 412; la UI conserva el borrador y pide actualizar.
Sin referencia del día o ante cambio de fecha durante una escritura se devuelve
409. Repetir la misma clave, cuenta y contenido recupera el mismo registro,
incluso si su día ya terminó. Reutilizar la clave con contenido o cuenta distintos
devuelve 409. El navegador conserva la clave mientras reintenta una operación
sin respuesta concluyente. La concurrencia usa bloqueos transaccionales en
PostgreSQL; el registro y su auditoría se confirman juntos.

Los comprobantes indican `quotation_only: true` y `payment_confirmed: false`.
El contexto indica `scope: "quotation_only"`. Ninguno reserva fondos, modifica
saldos ni acredita transferencias. La conversión genérica heredada rechaza VES
y monedas desconocidas: no puede fabricar una equivalencia 1:1 para estos casos.

## Persistencia y migración

Alembic `20261114_bcv_currency`, después de `20261113_runtime_schema`, crea
`bcv_rates` y `usd_ves_quotes`, sus restricciones y protecciones de historial.
No modifica los importes de tablas anteriores. Las revisiones enlazan la
referencia anterior y los comprobantes conservan la referencia aplicada.
No se edita o borra un registro confirmado. La reversión de esta migración se
niega si las tablas contienen datos; no elimina historia para forzar un downgrade.

La migración se comprueba en bases de prueba independientes y en el laboratorio
marcado. Aplicarla a producción requiere el proceso de despliegue autorizado,
respaldo y validación de compatibilidad. Esta entrega no la ejecuta allí.

## Prueba real de laboratorio

Tras `python scripts/local_test.py up`, instala Playwright y usa Chromium local:

```bash
python frontend/e2e/local-currency.browser.py --artifacts-dir browser-real/currency
```

El ejecutor exige el marcador de la base dedicada y que la identidad HTTP coincida
con ella antes de escribir. Usa tasas etiquetadas como **datos sintéticos**, sin
consultar bancos o enviar mensajes. Comprueba cancelación, precisión, revisiones,
recuperación al recargar, reintentos, conflictos, permisos y vista móvil. Compara
conteos y hashes de órdenes, contabilidad, retiros y configuración antes y después.
Conserva referencias y comprobantes de prueba; no los borra para simular limpieza.

En CI se ejecuta después de los recorridos funcionales anteriores, respetando la
ventana real de cinco logins por minuto mediante `--wait-auth-window`. Los casos
PostgreSQL automatizados utilizan una base `test_*` explícita y esquemas propios.

Sigue pendiente llevar la política USD/VES a cada operación monetaria con una
migración explícita de datos identificables, automatizar BCV con disponibilidad
y trazabilidad verificables y elegir/homologar un proveedor de pagos.

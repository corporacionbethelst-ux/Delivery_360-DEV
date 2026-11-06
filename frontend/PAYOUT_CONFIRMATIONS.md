# Confirmación y recuperación de retiros — entrega 64

La API actual registra solicitudes y decisiones contables. Aprobar mediante
`PATCH /payouts/{id}/approve` registra un débito y devuelve `EN_PROCESO`.
La existencia de `processed_at` también se usa al rechazar: esa fecha por sí sola
no demuestra un pago bancario completado. Esta entrega no conecta una pasarela
ni homologa Stripe/Mercado Pago; tampoco ejecuta transferencias o webhooks reales.

## Nueva solicitud y reintento

- `payoutService.requestPayout` requiere una `idempotency_key` retenida por el
  caller. Ya no genera otra silenciosamente cuando falta. La página guarda
  primero el intento en sessionStorage, separado por usuario, y aborta si falla
  esa escritura. El generador de claves existente sigue disponible para crear
  un intento nuevo deliberado.
- La comparación monetaria usa centavos enteros seguros y valida la precisión
  decimal antes de convertir. La solicitud admite 10,00 a 99.999.999,99, como
  el endpoint. Los saldos agregados pueden superar el límite por solicitud.
  Booleanos, cadenas vacías, números no finitos y más de dos decimales fallan.
- El POST debe confirmar la misma clave, importe, método y sufijo de cuenta.
  Antes de borrar el intento o mostrar éxito, la página comprueba también
  `requested_by_user_id` contra el usuario del intento persistido.
- La recuperación exige esas mismas coincidencias. Puede devolver cualquier
  estado real del servidor, incluido RECHAZADO: encontrar una solicitud permite
  recuperar su estado, no reinterpretarlo como un pago completado.
- Un 404 de request-status es una observación puntual; el POST anterior aún
  podría confirmar después. Se conserva la clave y se permite consultar o
  reintentar exactamente la misma solicitud, aun con saldo menor/desconocido.
  El backend vuelve a autorizar y decide si la solicitud ya existe o puede crearse.
- Se conserva la política de liberar un intento nuevo ante un primer 400/422
  definitivo. Tras una respuesta anterior incierta, esos errores también
  conservan la clave. No hay reintentos financieros automáticos.
- `bank_account_id` se rechaza explícitamente: el endpoint no lo admite.
  `bank_account_last4` es un dato de verificación, no una cuenta bancaria
  tokenizada ni una ruta de transferencia.

## Sesión, concurrencia y errores

Cada método del servicio comprueba la generación de credenciales después del
HTTP, también cuando devuelve error o un 404. Las páginas comprueban de nuevo su
vigencia tras esperar al servicio. El cambio de cuenta/rol limpia el estado
privado; navegar a otro retiro también retira la continuación anterior.

Hay bloqueos síncronos para impedir doble envío y consulta/reintento simultáneos.
La inicialización recupera el intento antes de habilitar un formulario nuevo.
Los listados/detalle retiran lecturas anteriores al iniciar otra y conservan
resultados previos ante un fallo de refresco. Una aprobación confirmada permanece
visible aunque falle su recarga posterior; las acciones pendientes se bloquean
hasta poder revisar los datos. Antes de iniciar consultas complementarias de
repartidores, gerencia vuelve a verificar la sesión de la lectura original.

## Datos mostrados

- Se rechazan aliases de importe/método contradictorios e identidades incorrectas
  en detalle, decisión, búsqueda por clave y auditoría. Se rechazan duplicados,
  páginas demasiado grandes y resultados fuera del filtro solicitado.
- Fechas desconocidas/incorrectas permanecen null; no se usa la fecha actual.
  No se inventan método, cantidades de órdenes o saldos cero.
- `degraded: true` en /payouts/balance produce un error de disponibilidad, aunque
  contenga ceros. Un cero realmente medido sigue siendo válido. La recuperación
  de un intento continúa disponible aunque no se pueda leer el saldo.
- La página de retiro respeta la moneda informada por balance (hoy COP).
  Cuando la respuesta no informa moneda, las vistas lo indican y conservan los
  decimales; no asumen USD ni deducen moneda del método de pago.
- Los listados actuales muestran hasta 50 retiros y las métricas/filtros locales
  se identifican como pertenecientes a ese lote. `getAll` conserva su contrato
  de una página con limit/offset; no devuelve un total global ni agota páginas.
  Las dos etiquetas históricas PROCESADO/CANCELADO se pueden leer, pero no se
  envían como filtros de servidor: el enum vigente tiene seis estados.

## Límites y siguiente trabajo

La comparación frontend evita confirmaciones locales falsas; no sustituye las
reglas de autorización, reservas e idempotencia del servidor. Los clientes antiguos
todavía pueden usar el backend sin clave. sessionStorage es por pestaña; borrar
sus datos, usar otro navegador o abrir otra pestaña no ofrece recuperación global
ni exclusión mutua entre dispositivos. Los datos guardados no autorizan nada.

El serializer backend sigue publicando algunos placeholders (por ejemplo
orders_count=0) y no incluye moneda en cada retiro. No se reconstruyen datos
omitidos. La consulta paginada por offset tampoco ofrece una instantánea estable.

La homologación real necesita un contrato de proveedor, estados/recibos durables,
idempotencia de envío, verificación de firma y deduplicación de webhooks,
conciliación y pruebas sandbox. Debe mantenerse separada de la aprobación contable
actual. Quedan también E2E completos y el gate de cobertura del 50 %.

# Confirmación y recuperación de retiros — entregas 64–65

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
- Los listados muestran páginas de 50 retiros. Cada lectura pide 51 filas:
  la adicional permite habilitar Siguiente sin inventar total o número de páginas.
  Los offsets avanzan de 50 en 50; la fila adicional pasa a la página siguiente,
  no se presenta anticipadamente ni provoca consultas de su rider.
- El estado se filtra en el servidor y vuelve a offset 0. Buscar por ID/nombre/email
  sigue siendo local a la página visible y se indica así. Las métricas de gerencia
  resumen esa página, antes de la búsqueda local; no son totales globales.
- Si falla una página o filtro, se conserva la última página confirmada con su
  estado/offset reales; Reintentar consulta repite el intento que falló. Una
  consulta anterior no puede sustituir una posterior, tampoco sus errores.
- Si dos páginas contiguas repiten un ID visible, se conserva la anterior y se
  solicita volver al inicio. No se deduplican filas para disimular el cambio.
  Esto detecta algunos cambios, no todas las omisiones concurrentes de offset.
- getAll conserva su contrato de una página limit/offset; ahora copia los filtros
  del caller para validar la misma consulta que envió aunque el objeto se modifique.
  Las etiquetas históricas PROCESADO/CANCELADO siguen visibles, pero solo se ofrecen
  los seis estados canónicos como filtros de servidor.

## Recuperación de decisiones administrativas — entrega 65

Una aprobación/rechazo incierto conserva los datos previos y bloquea otra decisión.
Consultar estado del retiro solo lee detalle e historial; no vuelve a enviar PATCH.
Si ambas lecturas son válidas, se publica el estado observado. Un PENDIENTE leído
permite un nuevo clic deliberado; no demuestra que un request anterior se haya
cancelado. Los bloqueos, permisos y transacciones del servidor siguen siendo la
autoridad final. Un fallo de lectura conserva el bloqueo y permite volver a consultar.

Una decisión confirmada conserva su respuesta aunque falle la recarga posterior.
Se verifica también que método y sufijo de cuenta correspondan al retiro revisado.
La fecha de gestión y el rechazo tampoco equivalen a cancelar una transferencia
bancaria. No se añade ninguna llamada a una pasarela externa.

La recuperación de una lectura inicial fallida está disponible en el mismo detalle,
sin tener que navegar a otra pantalla. Las lecturas de nombres de riders están
limitadas a los IDs únicos de la página visible (máximo 50), verifican identidad y
sesión y muestran una indicación si no pueden completarse.

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

Detalle y validación de esta ampliación: [ENTREGA_65.md](ENTREGA_65.md).

# Repetición de asignaciones y confirmación real — entrega 62

Fecha: 31 de octubre de 2026, America/Caracas. Base: main
20bd3d8155b602f3970ad3ef9021aea19053069c, que incorpora el PR #302.

## Correcciones de revisión

El PR #302 introdujo dos errores P2 que se corrigen expresamente:

1. Repetir el rider existente sobre una entrega INICIADA reemplazaba started_at
   y accepted_at. El monitor calcula su plazo desde started_at y el cierre usa
   ese inicio para calcular duración; una repetición podía retrasar alertas y
   reducir artificialmente el tiempo transcurrido.
2. OrderService.create_order construía Order con assigned_rider_id antes del
   coordinador. La primera asignación aparecía como REASSIGN, con el mismo rider
   anterior/nuevo. Se retira ese campo del payload del constructor y solo el
   coordinador lo asigna. El esquema de entrada no se modifica.

Los tests nuevos cubren creación válida por el adaptador, no solo su rechazo,
y repetición de una asignación ya confirmada. Dos controles negativos ejecutan
las funciones exactas de la base en procesos separados: reproducen la alerta
vencida omitida y el tipo REASSIGN incorrecto. No se publica ese código antiguo.

## Repetición sin cambios

| Estado bajo bloqueo | Resultado |
| --- | --- |
| Order ASIGNADO + mismo rider + Delivery INICIADA con ese rider | Se confirma el estado existente, sin reescribir tiempos, filas ni recibos de negocio |
| Creación o asignación nueva | Order/Delivery/AuditLog se confirman juntos; la primera asignación es ASSIGN |
| Rider realmente distinto y entrega/ruta temprana elegible | Reasignación real con REASSIGN y clocks anterior/nuevo en JSON de auditoría |
| Entrega/ruta avanzada, vínculo contradictorio o pérdida de elegibilidad | Se conservan las restricciones y errores de la entrega 61 |

Se mantienen los bloqueos y todas las comprobaciones de usuario, documentos y
época autenticada. La repetición no sirve para eludir una revocación o asignar a
una cuenta ahora inactiva. Tampoco omite el control de evidencia operativa.

La repetición temprana preserva accepted_at, started_at y updated_at, incluso
si un reloj histórico es NULL. No inventa un inicio reciente para una fecha
desconocida ni certifica cumplimiento SLA. Esos datos históricos necesitan su
propia revisión. El helper devuelve el indicador interno changed; cuando es
False, la entrada de pedido omite aviso y publicación Redis, y la de entrega
omite su hook. No se inserta otra auditoría de asignación para una operación
sin cambios.

POST /deliveries/{id}/assign admite además repetir el mismo rider cuando la
entrega está INICIADA. Continúa rechazando cambiar de rider desde esa entrada
si dejó de estar PENDIENTE. Las rutas y cuerpos conservan el mismo OpenAPI.
OrderService.assign_rider_to_order comparte el comportamiento sin cambios.
El automático sigue admitiendo únicamente pedidos PENDIENTE.

Si una entrega INICIADA ya vinculada al mismo rider se coordina con una orden
histórica todavía PENDIENTE, se conserva su started_at existente al confirmar
la orden. Un cambio real de rider conserva la política previa de iniciar su
nueva etapa; audit_logs.old_values/new_values registra ambos tiempos. No se
reescribe el deadline del pedido ni se homologan aquí todos los SLA por etapa.

Esto no es idempotencia global por clave de solicitud: POST de creación todavía
puede crear otro pedido al repetirse, y un request antiguo cuyo rider difiere
del actual puede ser una nueva reasignación. La revisión optimista y las claves
durables de reintento continúan pendientes.

## Confirmación frontend

OrderList es un componente reutilizable; no se declara que todas las páginas
de despacho lo utilicen. Su callback anterior solo imprimía un mensaje y cerraba
el modal. Ahora espera la acción real de ordersStore y solo cierra tras una
respuesta coherente del servidor. Un error conserva el pedido y el formulario.

orderAssignmentPatch adapta el contrato HTTP real: assigned_rider, Delivery y
los IDs deben corresponder al pedido y rider solicitados, con ASIGNADO/INICIADA.
La respuesta se capturó mediante HTTP contra PostgreSQL de prueba y se guarda
como fixture frontend nuevo. No se requieren rol, fechas de alta u otros campos
de una cuenta User completa para mostrar el resumen del rider.

La proyección actualiza estado, referencia visible y resumen de entrega. Conserva
importes, cliente y direcciones del modelo de vista; no los reemplaza con campos
ausentes o defaults. Fechas/métricas opcionales desconocidas siguen desconocidas;
un cero medido se conserva. Una confirmación incompleta o contradictoria produce
error y no publica un éxito local. capturePrivateTask conserva el aislamiento de
cuenta si la respuesta llega después de cambiar la sesión. El callback padre de
OrderList vuelve a comprobar la sesión después de esperar al store, cerrando
también ese intervalo de continuación antes de publicar la confirmación local.

Si el padre entrega un array de órdenes propio, se muestra la confirmación local
solo mientras conserve exactamente el objeto de entrada confirmado. Un objeto
nuevo del padre prevalece. Esto evita ocultar una actualización posterior con
un override permanente; no sustituye revisiones del servidor ni sincronización
completa de todos los modelos de vista.

AssignRiderModal acepta callbacks async, bloquea confirmación, selección y cierre
durante el envío y contiene errores síncronos/asíncronos. El fallo permite revisar
y reintentar; no invoca cierre ni muestra éxito ficticio. La protección evita
envíos simultáneos desde esa instancia; no es una garantía contra otras pestañas
o contra pérdida de la respuesta después del commit. Los errores de carga de
repartidores se contienen, bloquean confirmación con una lista no actualizada y
permiten recargar; los rechazos tardíos tras desmontar no publican estado.

## Estadísticas y respuesta vacía legacy

orderService.getStats deja de devolver 450 pedidos, ingresos y series inventadas
cuando falla HTTP. El error se propaga y un payload con métricas desconocidas o
no finitas se rechaza; no se convierten en ceros. Los datos válidos y sus ceros
no se mutan. La ruta legacy /orders/stats sigue sin implementarse: no se añade
un endpoint estadístico ni se reemplaza el panel operativo existente.

orderService.delete ya acepta una respuesta HTTP exitosa sin contenido, conforme
a su retorno void, y continúa propagando errores. No se añade DELETE /orders ni
se ejecuta un borrado real; la operación disponible depende del backend. Esta
corrección no convierte una cancelación en eliminación física.

## Verificación y límites

Se añaden 16 casos backend y 49 frontend. Cubren relojes conocidos/NULL, alerta
vencida real, ausencia de recibos/hooks duplicados, primera creación, cambio real
de rider, permisos vigentes, solicitudes simultáneas, contrato HTTP, transporte
frontend real simulado, doble envío, error/reintento, props/store, cambio de
cuenta y métricas inválidas. La regresión completa y cobertura nueva se registran
en la entrega 62 de Implementacion_de_mejoras_V1.md.

Se mantienen 202 rutas, 194 contratos de dependencia y OpenAPI SHA256
84bef605f22c31d4e8b3d9279e812d05c3cc8d3d303f73c441248f307dba0172.
No hay cambios de columnas, migraciones, dependencias, flags ni workflows. Los
snapshots JSON y contratos físicos previos permanecen intactos; el fixture nuevo describe la respuesta
de una base de prueba, sin datos operativos reales. Mypy conserva sus opciones CI.

Continúan cobertura 50 %, claves durables y revisión optimista, outbox, capacidad,
antigüedad GPS, reparación histórica y política SLA entre etapas, proveedores
homologados, conciliación y el resto del roadmap. Jest y los servicios locales
no sustituyen validación operativa en producción ni pruebas E2E de todo el sistema.

# Asignación operativa y auditoría — entrega 61

Fecha: 31 de octubre de 2026, America/Caracas. Base: main
65876d582098c9cc8fbe6c6c5f3b890138af53a2, con el PR #301 fusionado.

## Entradas y elegibilidad

Las cuatro entradas HTTP comparten el coordinador interno order_assignment:

| Entrada | Comportamiento |
| --- | --- |
| POST /api/v1/orders con rider_id | Crea y asigna junto con Delivery y AuditLog; una denegación no deja un pedido parcial |
| PATCH /api/v1/orders/{id}/assign | Asigna o reasigna una orden PENDIENTE/ASIGNADO sin avance operativo incompatible |
| POST /api/v1/deliveries/{id}/assign | Conserva la precondición de entrega PENDIENTE y actualiza también la orden |
| POST /api/v1/orders/{id}/assign-auto | Conserva PENDIENTE, origen válido y ventana de cinco candidatos geográficos; bloquea y vuelve a comprobar cada candidato |

Un candidato debe tener Rider ACTIVO, User existente y activo con rol
REPARTIDOR, y los cuatro tipos documentales requeridos, sin duplicados,
aprobados y respaldados por archivos accesibles y no vacíos. Se reutiliza
document_readiness_error, sin autoaprobar documentos ni activar cuentas.

La asignación manual administrativa conserva la posibilidad de trabajar sin
GPS o conexión online. La automática exige también is_online=True, geometría
presente y coordenadas finitas dentro de rango. Se validan nuevamente después
de bloquear el Rider: la consulta inicial por cercanía no autoriza por sí sola.
La búsqueda nearby filtra cuentas inactivas/roles ajenos y rangos de posición;
es descubrimiento de candidatos, no certificación documental de cada fila.

OrderService.create_order y assign_rider_to_order reutilizan el coordinador
cuando reciben una asignación, con un responsable UUID real y vigente. Sus
fallos hacen rollback; los helpers internos no poseen el commit. Estos
adaptadores siguen siendo para código de confianza, no nuevas rutas públicas.
El cambio de assigned_rider_id mediante edición genérica y el paso directo a
ASIGNADO por cambio de estado se rechazan con 409: debe usarse la asignación.
Crear una orden sin asignación conserva su funcionamiento anterior.

## Transacción, evidencia y concurrencia

El orden de bloqueo de este coordinador es Order, Delivery, Route si existe,
Rider y Users ordenados por UUID. El bloqueo inicial de Order serializa otras
operaciones sobre esa misma orden. Las cuentas usan FOR SHARE: no se modifican,
pero un cambio concurrente de rol, actividad o época debe esperar al commit.
Los documentos se revisan bajo el bloqueo padre de Rider que también usan
los flujos documentales y de perfil/flota.

Después de las esperas se comprueba que el responsable siga activo, conserve
SUPERADMIN/GERENTE/OPERADOR y, en HTTP, mantenga la época JWT autenticada. El
valor de esa época se captura antes de cualquier recarga del usuario. Una
revocación durante la espera responde 401; perder el rol operativo responde
403. Un candidato no habilitado responde 400 en asignación manual/creación y
404 si no queda candidato automático disponible.

La búsqueda automática usa SKIP LOCKED al adquirir Rider. Puede usar el siguiente
candidato de la ventana si otro está bloqueado o ya no es elegible. Si ninguno
sirve, devuelve 404 sin asignar. No espera a otro bloqueo Rider mientras recorre
esa ventana. Sí puede esperar a una actualización de User; no es una política
general de latencia cero ni examina todos los riders de la plataforma.

No se reinicia una entrega con estado posterior a PENDIENTE/INICIADA, marcas de
llegada/salida/finalización o incidentes. Tampoco se reasigna una ruta iniciada,
completada, cancelada o con marcas operativas. La ambigüedad de entregas/rutas y
los vínculos Order/Delivery contradictorios requieren revisión con 409. Se evita
el antiguo borrado de timestamps e incidentes al reasignar. Una entrega temprana
sin esa evidencia puede cambiar de rider, dejando al anterior en AuditLog.
No se reparan datos históricos por deducción ni se replanifican rutas aquí.

Order, Delivery y AuditLog se confirman juntos. Una caída al guardar la auditoría
revierte la asignación y, si se estaba creando, la nueva orden. Se conserva el
recurso ORDER, se distingue ASSIGN/REASSIGN y se guardan el rider anterior/nuevo,
la entrega y la vía de entrada. La vía automática normaliza el recurso anterior
Order a ORDER para registros nuevos; no reescribe el histórico.

Desactivar una cuenta después de confirmar una asignación no cancela ni mueve
automáticamente sus pedidos. La prueba concurrente verifica que ese cambio
posterior se serializa, no que desaparezca toda obligación operativa pendiente.

## Motivos de aprobación: hallazgo de revisión #301

El adaptador RiderService admitía un motivo de hasta 2000 caracteres y lo
escribía completo en changes_summary, cuya capacidad física es VARCHAR(500).
PostgreSQL rechazaba los motivos de 501–2000 y revertía la decisión.

Se conserva el motivo admitido completo en new_values.reason, dentro del JSON
existente, y changes_summary contiene sus primeros 500 caracteres. No se añade
columna ni se amplía el esquema. Aprobación y rechazo se prueban con 500, 501 y
2000 caracteres Unicode; 2001 se rechaza antes de IO. Se mantienen el control
documental, permisos y auditoría atómica de la decisión.

| Campo físico | Uso en esta entrega |
| --- | --- |
| audit_logs.changes_summary, String(500) | Resumen acotado de la decisión; no es el motivo completo si supera 500 |
| audit_logs.new_values, JSON | reason completo, hasta 2000 caracteres admitidos por el adaptador |
| audit_logs.old_values/new_values, JSON | Vínculos anterior/nuevo de asignación y source; no son columnas nuevas |

AssignmentCandidate es un objeto Python en memoria, no una tabla. No hay
migraciones, columnas, dependencias, flags o endpoints nuevos.

## Interfaz y verificación

AssignRiderModal comprueba que la selección siga en la lista visible, activa y
online al confirmar; también bloquea durante carga, si el pedido ya está
asignado o dejó de estar PENDIENTE. Si la lista cambia, un UUID seleccionado
anteriormente no habilita el botón por sí solo. Se añade selección por teclado
y nombre accesible al cierre. La autorización final permanece en el servidor;
el formulario no certifica documentos ni reemplaza los bloqueos.

Hay 73 casos backend nuevos y once frontend nuevos. Incluyen las cuatro vías,
denegación sin escrituras parciales, rollback de auditoría, evidencia, esperas
PostgreSQL reales, revocación, bloqueo compartido de User, SKIP LOCKED con
alternativa, revisión de ubicación y trazabilidad de reasignación. Dos controles
negativos reintroducen únicamente los comportamientos anteriores en procesos
de prueba separados: reproducen truncamiento VARCHAR y aceptación indebida de
una cuenta inactiva. No forman parte de la fuente publicada.

Se mantienen 202 rutas, 194 contratos de dependencia y OpenAPI SHA256
84bef605f22c31d4e8b3d9279e812d05c3cc8d3d303f73c441248f307dba0172.
Los fixtures físicos existentes no se regeneran. Mypy continúa sin errores con
las opciones CI, ahora en 193 archivos; quedan las notas previas sobre cuerpos
sin anotaciones. El frontend tiene 782 tests aprobados / 55 suites y cobertura
de líneas 30,58 %: el gate 50 % sigue pendiente, sin reducirlo.

Los avisos manuales mantienen la sesión independiente de la entrega 60. La
bandeja automática sigue local y transaccional; el hook de la entrada de entrega
continúa post-commit. No se añade outbox, idempotencia de reintentos HTTP,
revisión optimista de asignación en el formulario, capacidad por rider, política
de antigüedad GPS o revisión completa de datos históricos. Continúan también
los proveedores homologados, conciliación, alertas, cobertura y validación
operativa del roadmap. No se declara producción completa.

## Actualización de la entrega 62

Se corrigen dos errores de esta entrega: reiniciar el reloj al repetir el mismo
rider y precargar el rider en OrderService.create_order antes de su primera
auditoría. La repetición temprana sin cambios conserva tiempos y no emite nuevos
recibos/hooks; no es idempotencia global por clave. Se conecta la confirmación
real de OrderList y se conserva el error ante estadísticas legacy no disponibles.
Detalles y compatibilidad: [ASSIGNMENT_REPLAY.md](ASSIGNMENT_REPLAY.md).

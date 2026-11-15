# Entrega 100 — órdenes visibles cuando una asignación requiere revisión

## Incidencia confirmada

En `/manager/operations/orders`, la sesión Superadmin recibía respuestas HTTP200
pero `validateHttpOrder` rechazaba una orden con identidades de repartidor
contradictorias. El rechazo de una sola fila impedía publicar todo el catálogo;
la pantalla mostraba «No se pudieron cargar los datos» sin identificar el motivo.

Se reprodujo el mismo error en Chromium sobre la versión anterior: una respuesta
HTTP200 conserva los datos de una orden real sintética y cambia solamente el
repartidor de su entrega. El cambio se hace en la respuesta del test, nunca en la
base. La prueba acredita el fallo original antes de verificar la corrección.

## Corrección

El listado operativo usa una lectura de revisión específica. Las órdenes con
vínculos de repartidor contradictorios se conservan en el listado y se marcan
«Revisión de asignación». La ficha muestra las referencias originales de la orden,
sus alias y su entrega. No se escoge automáticamente cuál corresponde ni se
modifica el historial para hacer desaparecer el aviso.

En esas filas se bloquean asignación, cambio de estado y cancelación. «Ver» abre
la ficha de revisión sin navegar hacia un detalle que exige vínculos coherentes.
Las órdenes sin conflicto mantienen sus controles habituales. La exportación
conserva todas las filas e indica la revisión, repartidor de orden y de entrega;
no atribuye el pedido a un repartidor elegido por el frontend.

La lectura anterior y las confirmaciones de escritura siguen siendo estrictas.
El modo de revisión no admite una entrega de otra orden, estados desconocidos,
identidades de orden duplicadas, artículos mal formados o precios incoherentes.
El indicador de revisión se calcula en el cliente; una bandera recibida del
servidor no puede desactivar las comprobaciones.

Las consultas de órdenes, repartidores y vehículos dejan de depender de una
promesa conjunta: un catálogo auxiliar fallido o lento no oculta órdenes ya
confirmadas. Se señala el recurso fallido y el motivo concreto. Un listado que
no pudo consultarse no se presenta como «No se encontraron órdenes». La
asignación manual queda pendiente mientras el catálogo de repartidores no esté
confirmado. Cambiar cuenta, credenciales o rol retira cargas anteriores.

Se aprovecha la relación canónica `assigned_rider` al mostrar nombres y vehículos,
conservando el alias anterior. Los identificadores ausentes y fechas desconocidas
se muestran sin inventar datos. El diseño de tarjetas y colores se conserva.

## Verificación y conservación

Pruebas focalizadas con el servicio y validador reales: respuesta HTTP200 con
conflicto, mezcla de filas correctas y en revisión, referencias conservadas,
operaciones bloqueadas, exportación, errores y esperas de catálogos auxiliares,
reintentos y cambios de cuenta. Se conservan los controles de precios y las
pruebas estrictas anteriores de asignación.

La nueva prueba Chromium se incorpora a CI. Usa cuentas sintéticas y solo GET;
comprueba catálogo completo, ficha de revisión, controles de filas correctas,
CSV, búsqueda, móvil, caída de repartidores, rechazo de un precio incoherente y
recuperación. Compara los hashes de órdenes, entregas y registros monetarios
antes/después y comprueba ausencia de escrituras de negocio y excepciones JS.

La rama parte del main `37fce8c8c403a13ef98927301f739e52353dfe6e`, que contiene
PR341. Se conserva un respaldo antes de trabajar y se verifican las filas y los
48 documentos previos. Los resultados finales, CI, ZIP, bundle y parche con
recuperación se guardan en los artefactos de entrega.

No se requiere migración ni se modifican registros existentes. Las asignaciones
históricas marcadas requieren revisar sus referencias para decidir cualquier
reparación posterior. Esta entrega soluciona el bloqueo de visualización, sin
convertir una inconsistencia en una asignación confirmada. El pendiente de
moneda de la auditoría operativa permanece aplazado por esta incidencia.

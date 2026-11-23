# Delivery360 — entrega 118

## Presentación solicitada de mensajes

Se añade un host central para errores y confirmaciones en modales centrados, con mensajes informativos y resultados correctos abajo a la derecha. Se sustituyen alert/confirm nativos y se conservan las confirmaciones de negocio existentes. Las elecciones asíncronas se cancelan al cambiar de sesión y se protegen frente a dobles invocaciones. Se comprueba cancelación sin mutación y posición real en Chromium. Ver MENSAJES_INTERFAZ.md. Este bloque no define una excepción ni emisión de OTP.

## Corrección del cierre de órdenes con OTP

El botón ENTREGADO del catálogo del gerente enviaba solamente new_status=ENTREGADO. El backend ya validaba el OTP de la entrega, pero el formulario no permitía introducirlo y el servicio frontend no lo transmitía. Por eso una entrega configurada con OTP respondía «Código OTP requerido o incorrecto».

Ahora el botón abre Confirmar entrega, con identificación de orden, campo OTP textual (conserva ceros iniciales), explicación, error en el propio diálogo y protección frente a confirmaciones simultáneas. Se mantiene la orden abierta para corregir un rechazo. Consultar estado permite recuperar una confirmación cuya respuesta se perdió mediante lectura, sin repetir la mutación. El formulario conserva el estilo azul/verde y se desplaza dentro del área visible en pantallas bajas.

La API acepta opcionalmente {"otp_code":"…"} en JSON, sin añadir el código a la URL de las nuevas solicitudes. El parámetro de consulta anterior sigue disponible por compatibilidad; si cuerpo y consulta proporcionan valores distintos se rechaza la solicitud. Se conserva la validación central del OTP, los permisos, la transición desde EN_RUTA, los bloqueos y la coordinación financiera existente.

## Uso local

En /manager/operations/orders, para una orden En ruta, pulsa ENTREGADO, introduce el código real si la entrega lo requiere y confirma. Si el código es incorrecto, corrígelo en el mismo diálogo. Si no queda clara la confirmación por un problema de conexión, utiliza Consultar estado antes de volver a enviarla.

Una entrega sin OTP configurado conserva el cierre sin código. Una entrega con OTP requerido, pero ausente o desconocido, necesita revisar su configuración/origen: esta entrega no inventa códigos, no los muestra desde la base y no desactiva la verificación. No se han modificado las órdenes originales del usuario. No hay migración nueva.

## Aceptación

Pruebas HTTP con persistencia controlada cubren código JSON correcto con ceros iniciales, ausente, vacío, incorrecto, cierre sin OTP y conflicto cuerpo/consulta; los rechazos conservan el estado y no llaman al cierre financiero ni commit. La prueba de compatibilidad por consulta se conserva. La interfaz comprueba el diálogo, la corrección tras rechazo y la recuperación de una respuesta perdida sin segunda mutación.

El ciclo del laboratorio asigna un OTP únicamente a una entrega de prueba y completa una orden desde la interfaz real del gerente tras dos rechazos. Comprueba 400/400/200, código en JSON y fuera de la URL, estados de orden/entrega y el snapshot monetario previo de la suite. Conserva las demás entregas del repartidor, reintentos y verificaciones de saldo.

Se prioriza esta incidencia reportada antes del bloque de avisos de asignación. Los demás pendientes de producción continúan en PRODUCCION_PENDIENTES.md; no se ejecutan despliegues, migraciones originales ni envíos externos.

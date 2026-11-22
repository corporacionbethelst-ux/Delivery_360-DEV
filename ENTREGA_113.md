# Delivery360 — entrega 113

Se amplía el ensayo mantenido de recuperación para arrancar las imágenes candidatas de API y frontend sobre la copia, con acceso exclusivamente loopback y datos reales del respaldo. La entrega 112 se conserva; la opción anterior sin web mantiene su comportamiento.

El modo web utiliza los puertos del laboratorio para coincidir con la URL compilada de Next, valida bindings y rechaza conflictos IPv4/IPv6 antes de crear recursos. Base/Redis siguen en una red interna sin puertos; API/web tienen una red de acceso local, CORS acotado, usuarios sin privilegios, raíz de solo lectura y proveedores desactivados. La red de acceso no se presenta como airgap.

El navegador inicia una sesión nueva, confirma acceso anónimo restringido, login real, identidad de una orden de la copia, zona, recarga y presentación desktop/móvil de órdenes y zonas. Las respuestas de backend son reales. Rechaza destinos ajenos, mutaciones de negocio y WebSocket no autorizados; solo permite heartbeat en las notificaciones de la copia. Comprueba desbordamiento y errores de página y deja capturas privadas por defecto. No guarda tokens, HAR ni sesiones.

CI ejecuta esta aceptación tras restaurar el respaldo y compara después el historial operativo/financiero. Se conserva el cierre por identidad, todos los volúmenes y las pruebas anteriores. El reporte HTTP sigue con14 comprobaciones y el visual añade12, separados para no presentar controles HTTP como pruebas de navegador. No cambia la interfaz del producto, endpoints ni esquema de negocio.

Guía actualizada: RECUPERACION_LOCAL.md. Continúan pendientes aceptación de otros recorridos/roles, staging, objetivos RPO/RTO/capacidad y operación productiva. Sin fusión, despliegue ni migración de producción automáticos.

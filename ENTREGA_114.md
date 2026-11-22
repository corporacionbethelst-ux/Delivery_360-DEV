# Delivery360 — entrega 114

El botón «Nueva Orden» quedaba parcialmente recortado a390px. La página no tenía overflow horizontal global porque un ancestro ocultaba el contenido; esa comprobación no bastaba para aceptar el diseño.

Las acciones ahora se distribuyen en dos columnas en móvil, con «Nueva Orden» a todo el ancho, y se reorganizan con wrap en pantallas mayores. La cabecera conserva un aspecto profesional con acentos azul/violeta. Búsqueda y filtros se apilan en pantallas pequeñas, tienen nombres accesibles y controles de44px. Se conservan navegación, permisos, descarga CSV y contratos de negocio.

`scripts/browser_layout.py` comprueba dimensiones, límites del viewport y ancestros con overflow, y puntos de interacción sin obstrucciones. Se usa en producción y en la restauración a320/390/768/1024/1440px. Una reproducción sintética confirma que rechaza el fallo incluso sin overflow global. La prueba de producción verifica filtros y navegación al formulario existente sin mutaciones de negocio. El ensayo restaurado conserva sus guardias de red, datos reales y comprobaciones de historial después del navegador.

La rama incluye íntegramente113 y main: PR355 se había integrado en `feat/restore-rehearsal` después de fusionar354 en main. Se preservan ambos estados mediante merge, sin reescribir commits ni modificar datos. Esta entrega propone su incorporación conjunta a main; no ejecuta esa integración ni un despliegue.

Validación y evidencias del commit candidato: `/workspace/work/entrega114`. No reutilizar como aprobación actual los resultados de113. La recuperación añade una comprobación de UI (13); los14 controles HTTP siguen separados. Producción añade cuatro comprobaciones al total anterior. La aceptación productiva, los demás roles, staging, RPO/RTO y capacidad siguen pendientes en `PRODUCCION_PENDIENTES.md`.

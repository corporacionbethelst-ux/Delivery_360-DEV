# Delivery360 — entrega 112

Se incorpora el procedimiento mantenido `scripts/recovery.py` y su sonda HTTP `scripts/recovery_probe.py`. El respaldo offline privado conserva dump y documentos con manifiesto SHA256, inventario de filas y metadatos de archivos. La restauración valida el paquete antes de crear recursos, rechaza destinos existentes y utiliza una base nueva desde template0 cuando finaliza la inicialización de PostgreSQL/PostGIS.

La comprobación cubre filas y columnas de todas las tablas públicas, incluidos conjuntos vacíos, head Alembic, bytes/permisos/UID/GID de documentos y arranque de la API. Comprueba acceso anónimo, login e identidad, órdenes, zonas, parámetros decimales y descarga autenticada del documento conservado. Después exige historia operativa y monetaria intacta. El login solo puede dejar sus metadatos y auditoría en la copia.

Cada ejecución usa recursos nuevos con labels propios, sin destino SQL arbitrario, sin seed, migración, proveedores ni pago bancario. Se detienen solo procesos/contenedores de esa ejecución y se conservan todos los volúmenes. Los respaldos y diagnósticos son privados; los reportes de CI no incluyen credenciales ni tokens. El modo de imagen usa red interna, usuario 10001 y filesystem de solo lectura; el modo nativo alternativo se limita a Linux y distingue sus restricciones en el reporte.

`local_test.py pause` permite detener API/web y `storage-up` arrancar únicamente DB/Redis para el respaldo, sin setup ni sembrado. CI mantiene las pruebas existentes y añade la restauración/arranque de API al final del laboratorio funcional. La captura de artefactos solo publica el reporte sanitizado.

Las pruebas de scripts verifican integridad, archivos exclusivos, tablas vacías, rutas/enlaces/tipos peligrosos de tar, permisos, propietario, rechazo de destinos existentes, espera del postmaster final, identidad de limpieza, secreto nuevo, ausencia de efectos externos y protección de credenciales en la sonda. La prueba real local recuperó 50 tablas, 1.041 filas y 52 documentos y aprobó las 14 comprobaciones completas sin modificar la fuente.

Guía: RECUPERACION_LOCAL.md. El ensayo es local, offline y representativo del laboratorio conservado. Siguen pendientes restauración y aceptación en staging, objetivos RPO/RTO, rendimiento y alertas/procedimiento operativo de producción. No equivale a certificación de recuperación productiva. No modifica frontend, endpoints ni esquema de negocio, y no fusiona ni despliega producción.

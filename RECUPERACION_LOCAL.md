# Respaldo offline y ensayo de recuperación local

La entrega 112 incorpora un procedimiento mantenido para el laboratorio marcado de Delivery360. Comprueba el respaldo y arranca la API contra una copia restaurada. No es un importador de producción ni acredita objetivos RPO/RTO, capacidad, staging o recuperación ante una caída completa de infraestructura.

## Preparar el respaldo

Conservar `.delivery360-testing`, sus credenciales y los volúmenes existentes. Ejecutar desde la raíz del repositorio con Python 3.11 o superior y Docker local. Un daemon remoto se rechaza. El laboratorio debe existir y contener datos y documentos representativos; estas operaciones no lo inicializan ni rellenan datos faltantes.

```bash
python scripts/local_test.py pause
python scripts/local_test.py storage-up
python scripts/recovery.py backup
```

`pause` detiene API y web del laboratorio. `storage-up` arranca únicamente PostgreSQL/Redis, sin setup, migración ni sembrado. Si hay una API nativa u otro cliente conectado a la base manual, detenerlo primero: el respaldo exige ausencia de conexiones de cliente ajenas. No parar servicios de otra instalación.

El último comando devuelve un `backup_id`. El directorio privado `.delivery360-testing/recovery/backups/<backup_id>/` contiene `database.dump`, `uploads.tar.gz` y `manifest.json`. Se crean archivos nuevos con permisos 0600 y directorios privados; no se sobrescriben respaldos. El manifiesto se publica al final, con SHA256, inventario de tablas, filas y documentos, permisos y propietarios. Se verifica el estado de datos y archivos antes y después de obtener el respaldo offline. No sustituye una estrategia de snapshot online con escrituras concurrentes.

Conservar el directorio completo: el dump contiene hashes de contraseñas y el archivo de documentos contiene datos privados. No subirlos a Git ni a los artefactos públicos de CI. El manifiesto detecta corrupción; no es una firma que autentique un respaldo de origen desconocido. El alcance local admite archivos de respaldo de hasta 256 MiB, documentos individuales de hasta 32 MiB y hasta 10.000 miembros del archivo. Requiere PostGIS/PostgreSQL 16, como `compose.testing.yml`.

## Restaurar y comprobar la API

Usar una imagen API local construida desde el código candidato. El laboratorio normal ya construye `delivery360-local-test-api:<instance>`; `<instance>` está en `.delivery360-testing/config.json`. Se exige una imagen ya disponible: la restauración usa `--pull=never`.

```bash
python scripts/recovery.py restore <backup_id> --api-image delivery360-local-test-api:<instance> --report recovery-result.json
```

Los identificadores del comando deben sustituirse por los valores devueltos o conservados por el propio laboratorio. Cada ejecución crea un `run_id` nuevo, una red interna, bases y volúmenes propios. Si un nombre ya existe, se rechaza antes de crearlo. No admite un destino de base de datos arbitrario. No sobrescribe el reporte si existe.

Se espera a PostgreSQL como proceso principal, además de `pg_isready`: la imagen PostGIS puede aceptar conexiones durante su inicialización temporal. Después se crea una base vacía desde `template0` y se ejecuta `pg_restore --exit-on-error`. Se comparan todas las columnas/filas de las tablas públicas, incluidas tablas vacías, y el head Alembic. Se recuperan los documentos con UID/GID 10001 y sus modos explícitos, sin depender de la umask del proceso. Se rechazan rutas absolutas, escapes, enlaces, dispositivos, duplicados, propietarios inesperados y bits privilegiados antes de crear recursos de restauración.

La API restaurada usa un secreto JWT nuevo, sin credenciales de proveedores ni trabajadores, notificaciones, correo o facturación activos. No se ejecutan seed ni comandos de migración. La imagen se ejecuta con usuario 10001, raíz y uploads de solo lectura, capacidades retiradas y sin publicación de puertos. El reporte conserva el identificador de imagen y hashes de respaldo, sin credenciales ni tokens.

Las pruebas verifican readiness de API/PostgreSQL/Redis, rechazo de acceso anónimo, login e identidad Superadmin, lectura de órdenes, zonas y configuración exacta, y descarga autenticada de un documento cuyos bytes deben coincidir con el respaldo. El login puede cambiar sus propios metadatos y auditoría en la copia; el historial operativo/monetario y la configuración conservada deben permanecer iguales. Es una prueba HTTP de backend, no aceptación visual completa de frontend sobre una restauración.

## Alternativa nativa en Linux

Para un entorno de desarrollo Linux con dependencias backend ya instaladas:

```bash
python scripts/recovery.py restore <backup_id> --python /ruta/al/venv/bin/python --report recovery-native-result.json
```

La API corre en el host, con socket reservado en `127.0.0.1`, un directorio de documentos propio y entorno explícito; PostgreSQL/Redis siguen en la red privada Docker, sin puertos publicados. Se comprueban los labels antes de usar sus direcciones. Este modo requiere conectividad Linux hacia el bridge Docker; en Docker Desktop usar el modo de imagen. El reporte distingue ambos modos: no equipara las restricciones del proceso nativo con las del contenedor de producción.

## Cierre y fallos

Los procesos y contenedores propios se detienen al terminar, incluso ante fallos controlados. Los volúmenes, respaldos y estados se conservan. El comando de cierre puede repetirse:

```bash
python scripts/recovery.py stop <run_id>
```

Se exige coincidencia de nombres y labels; para un proceso nativo se comprueba también su identidad de entorno antes de señalar su grupo. No se detienen contenedores de otras instalaciones ni se solicita eliminar volúmenes. Tras una interrupción brusca, revisar `.delivery360-testing/recovery/runs/<run_id>/state.json` y ejecutar el cierre anterior. No borrar un volumen por el mero hecho de que un intento haya fallado.

Los diagnósticos y logs con posibles detalles sensibles quedan privados en `.delivery360-testing/recovery/`. Solo `result.json` o el archivo indicado por `--report` son reportes sanitizados. Un intento incompleto no publica un reporte aprobado. Reservar espacio para las imágenes, copias de ejecución de Docker y volúmenes nuevos: VFS puede necesitar varias veces el tamaño de las imágenes. La herramienta no aplica limpiezas generales para conseguirlo.

En CI se ejecuta después de los recorridos funcionales: se pausa el origen, se crea el respaldo, se detiene el laboratorio original conservando volúmenes y se restaura en recursos nuevos con la imagen candidata. Solo el reporte sanitizado de 14 comprobaciones se añade al artefacto funcional. Los demás controles y el límite de tiempo se mantienen.

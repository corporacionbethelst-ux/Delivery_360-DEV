# Entrega 88 — Laboratorio de pruebas funcionales locales

Base main `6b2c75474994631f7fccbbb47b2a2f068714baee`, árbol
`10417af66ec57800e49b008f5eeecce4bacfb985`. La entrega 87 fue integrada por el
propietario mediante PR #329; su CI completo terminó aprobado. Rama:
`feat/local-functional-test-environment-v1`.

## Arranque y datos reales de prueba

`scripts/local_test.py` configura y arranca un Compose independiente con frontend,
API, PostgreSQL/PostGIS y Redis. Genera secretos privados fuera de Git y confirma
interfaz, dependencias y autenticación de cinco roles antes de indicar que está
listo. La guía [PRUEBAS_LOCALES.md](../PRUEBAS_LOCALES.md) incluye los comandos,
accesos, recorrido inicial y solución de problemas.

El inicializador valida conexiones, entorno y marcador de instancia antes de
preparar seis cuentas por rol, una zona, un repartidor desconectado y tres órdenes
pendientes. Usa las migraciones oficiales y no reutiliza los seeds históricos.
Al reiniciar conserva contraseñas, cambios y órdenes. Detener no borra volúmenes.
El CLI rechaza daemons remotos y las redirecciones HTTP a otros orígenes.

## Esquema y contenedores

Una base creada desde cero reveló tablas mapeadas sin migración: productividad,
SLA y eventos webhook, además del valor AUDITOR ausente en el enum PostgreSQL.
La revisión aditiva `20261113_runtime_schema` completa ese esquema sin modificar
cuentas existentes. Rechaza tablas con columnas incompletas; el downgrade se
niega a eliminar historial y conserva el significado del rol AUDITOR.

El scheduler de tracking puede desactivarse en el laboratorio; su valor habitual
continúa habilitado. Correo, notificaciones externas y emisión fiscal quedan
desactivados en este Compose. Las imágenes evitan copiar dependencias entre
capas de compilación; el backend instala sus dependencias fuera de `/app` y la
imagen final mantiene usuario sin privilegios.

## Comprobación funcional

El recorrido Chromium `local-functional.browser.py` solo permite escrituras tras
confirmar el marcador del laboratorio. Comprueba login real, cambio y restauración
de configuración, rechazo de una revisión obsoleta, simulación sobre la base
migrada, diseño móvil, creación y cancelación de una orden y bloqueo de escritura
para gerencia. No intercepta ni sustituye las respuestas de la API.

Los resultados concluyentes, logs, capturas y artefactos por commit se conservan
en `/workspace/work/entrega88`.

El laboratorio permite comenzar pruebas funcionales locales cuando `up` confirma
que está listo. La validación de proveedores reales, pagos, carga, restauración y
staging queda para etapas posteriores. Sin merge, deploy ni migraciones sobre
instalaciones productivas.

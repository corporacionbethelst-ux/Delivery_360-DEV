# Entrega 82 — Administración de usuarios

Fecha: **9 de noviembre de 2026, America/Caracas**.
Rama: `feat/user-administration-reliability-v1`.
Base main: `db53dc46277017828f254eb678846b63b5ae21a1`, árbol
`1af4c77c1ce487a575fb85fe5d79075f93670fc8`. El propietario integró la
entrega 81 mediante PR #323; su CI completo terminó aprobado.

## Presentación y comportamiento

Las tres páginas de usuarios —listado, alta y edición— adoptan el lenguaje del
formulario de orden: encabezado azul/cian, identidad azul, permisos violeta y
credenciales ámbar. Alta y edición comparten un formulario, con controles
etiquetados, acciones visibles, avisos de resultado y presentación adaptable.

- El correo manual se conserva al cambiar o abandonar nombre y apellido. Se
  elimina la generación automática de una dirección que podía sobrescribirlo.
  Teléfono tiene un campo que coincide con el contrato real. Se retiran biografía
  y notas del formulario anterior porque no se guardaban en la API.
- Los seis roles reales del backend incluyen **Auditor**, incorporado al tipo
  UserRole. Gerencia no puede crear ni modificar superadministradores. Las fichas
  correspondientes son de lectura; superadministración sí puede gestionarlas.
  El propio rol y estado quedan bloqueados conforme a la política del servidor.
- El listado consulta rol y estado en el servidor, incluyendo `is_active=false`.
  Presenta 50 cuentas y consulta 51 para confirmar la página siguiente. Búsqueda
  local por nombre, correo, teléfono o ID, con acentos normalizados. Contadores
  de la página, consulta confirmada y hora en Caracas; sin total global supuesto.
- Datos y alcance anteriores se conservan ante fallos. Una respuesta vacía
  confirmada se distingue de una lectura fallida. Se rechazan identidades
  duplicadas y respuestas que no corresponden al filtro solicitado. Roles y
  estados desconocidos permanecen explícitos. El desplazamiento de la tabla
  móvil admite teclado y no ensancha la página.

## Guardado, sesión y revisiones

Lecturas anteriores no reemplazan una nueva consulta. Cambios de ficha, cuenta,
rol o credenciales retiran resultados y operaciones anteriores mediante la
frontera de acceso existente. Un fallo de lectura o un ID distinto no habilitan
un formulario con datos predeterminados. Una revisión ausente permite ver la
ficha, pero bloquea su modificación hasta recargar.

Los borradores validan nombres, email, teléfono, roles y estado antes de enviar.
Las contraseñas conservan sus bytes y se validan por longitud de 8–128 caracteres
Unicode, contenido no vacío y confirmación exacta. Los campos y acciones quedan
bloqueados durante el guardado, con protección síncrona contra doble envío.
El conflicto de email permite corregir sin perder el borrador ni su revisión.

La edición conserva `expected_user_revision`. El acuse debe identificar la misma
cuenta y aportar la revisión siguiente antes de cambiar la contraseña. Datos y
contraseña siguen siendo operaciones separadas; un resultado parcial se informa
y exige recargar antes de repetir. El temporizador de salida se cancela al
abandonar la ficha o cambiar de sesión. Una respuesta de una ficha retirada no
inicia el cambio de contraseña de otra cuenta.

Desactivar confirma nombre, email e ID y explica la revocación de sesiones y la
conservación de datos históricos. Se mantiene la revisión de la fila seleccionada
incluso si se actualiza el listado. No se ofrece desactivación propia, de una
cuenta ya inactiva, sin revisión o sin permisos. La operación pendiente bloquea
duplicados, filtros, recargas y cierre del diálogo. Un conflicto requiere cerrar
y actualizar. Después del éxito se consulta de nuevo; si falla esa lectura, no
se repite la escritura ni se inventa el nuevo estado de la fila.

## Validación

| Control | Resultado local |
| --- | --- |
| Casos nuevos | **58 aprobados** |
| Regresión focalizada | **67 pruebas / 3 suites aprobadas**, con los nueve casos anteriores de revisiones |
| Suite frontend completa | **2530 pruebas / 118 suites aprobadas**, 63,085 s |
| Cobertura global | **61,85 % sentencias; 58,15 % ramas; 58,48 % funciones; 61,21 % líneas** |
| Mínimos y selección | Sin cambios; pasan los cuatro mínimos de 50 % |
| TypeScript y build con lint | Aprobados; **48 páginas**, 17 advertencias existentes |
| Chromium | **106 comprobaciones**: usuarios 15 y los nueve smokes anteriores 91 |
| Navegador | Datos sintéticos, **cero escrituras de negocio y cero excepciones JavaScript** |
| Formato y workflow | Prettier, Black y actionlint aprobados |

Jest verifica payloads, revisión capturada, doble envío, cambios de sesión y
resultados parciales con servicios simulados. Se añade el ResizeObserver mínimo
de jsdom requerido por el Switch real dentro de un formulario; el layout se
comprueba en Chromium. Los tests anteriores de revisiones conservan sus
aserciones y usan la frontera autenticada y la recarga explícita actuales.

Chromium usa el build standalone real, intercepta las lecturas de negocio y
bloquea las escrituras y WebSockets. Comprueba escritorio, móvil, tabla por
teclado, roles, validación, reintentos y cancelaciones. El nuevo smoke se suma al
job frontend-container requerido, conservando los nueve anteriores. Estas
comprobaciones no certifican escrituras integrales contra staging ni accesibilidad
integral. Logs y capturas: `/workspace/work/entrega82`.

Backend, servicio de usuarios, dependencias y formulario original de orden sin
cambios. No se atribuye una nueva corrida backend local. La publicación por rama
y PR está autorizada para esta entrega y las próximas; CI remoto observado por
SHA y registrado en el PR y los archivos de evidencia. Sin merge, deploy,
migraciones ni operaciones productivas del agente. Continúan pendientes
infraestructura, staging, carga, restauración y proveedores; main seguía sin
protección en la consulta de esta entrega. Se conservan ZIP sin archivos de
entorno, bundle incremental verificado, patch, hashes y evidencia de CI.

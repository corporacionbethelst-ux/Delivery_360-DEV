# Entrega 79 — Perfil y documentación de repartidores

Fecha: 8 de noviembre de 2026, America/Caracas.
Base main: `5109fc040fdf4f301342149b15674dc580ae04cd`, árbol
`277bad3bd204971bfe663bdaf86d0aad7b936769` (entrega 78, PR #320 integrado por
el propietario).
Rama: `feat/rider-profile-documents-reliability-v1`.
El CI completo de la entrega 78 terminó aprobado. La rama se actualizó sobre main
antes de publicar; su árbol base coincide con el usado en las pruebas locales.

## Presentación

Perfil y documentos adoptan los componentes compartidos de operaciones, con la
referencia del formulario de orden: encabezado azul/cian en perfil, violeta en
documentación, vehículo violeta, nivel ámbar y valores financieros verde/azul.
Se conservan la estructura de la ficha, el acceso a documentación y las acciones
reales. Las tarjetas, controles visibles y diálogos se ajustan a móvil; se revisan
capturas del perfil, ubicación, documentos, rechazo y subida.

## Perfil con datos confirmados

- Los datos ausentes no se convierten en saldos cero, entregas cero, Bronce,
  todas las zonas ni fecha actual. Se preservan ceros reales y precisión numérica.
  La ficha no declara moneda COP, fondos disponibles para retiro ni porcentajes
  de bonificación que su respuesta no informa. Se retira el botón deshabilitado
  de historial que no llevaba a una pantalla.
- El vehículo de empresa se resuelve desde la asignación incluida y sus IDs
  coincidentes, sin reutilizar la placa de un vehículo propio anterior.
- La ubicación muestra el último par válido de coordenadas, incluso desconectado,
  con su fecha real si existe. Comprueba ambos valores finitos y sus rangos;
  cero no se considera ausencia. Sustituye el mapa decorativo y la señal marcada
  como activa por datos históricos explícitos, sin seguimiento en vivo inventado.
- Las fechas UTC del backend sin sufijo se interpretan como UTC y se presentan en
  America/Caracas. Ausentes o inválidas indican que no fueron informadas.
- La lectura verifica que el ID devuelto coincida con la ruta. Lecturas de rutas,
  cuentas o credenciales anteriores no sustituyen la nueva ficha. Los fallos de
  actualización conservan la consulta confirmada y ofrecen reintento.
- El cambio de estado identifica nombre e ID en un diálogo y bloquea duplicados.
  El endpoint devuelve un acuse parcial: se vuelve a leer el perfil, sin inventar
  un perfil completo o una conexión automática. Un conflicto de activación también
  recarga, porque el backend puede restringir al repartidor por documentación.
  Un fallo del cambio conserva la ficha y el diálogo. Si el cambio termina bien
  pero falla la lectura posterior, se informa cada resultado sin repetir el PATCH.

## Documentos y operaciones

Lectura para SUPERADMIN, GERENTE y OPERADOR; aprobar, rechazar, eliminar y subir
siguen limitados a gerente/superadmin. La autorización del servidor permanece
intacta. La frontera de sesión y la identidad de ruta retiran formularios,
resultados tardíos y descargas al cambiar la ficha o las credenciales.

La lista distingue fallo inicial, vacío confirmado y fallo de recarga. Conserva
filas confirmadas ante el fallo, pero bloquea nuevas mutaciones hasta reintentar.
Rechaza respuestas duplicadas o documentos con un rider_id informado distinto de
la ruta; admite las respuestas anteriores que no incluyen ese campo opcional.
Estados desconocidos no se presentan como pendientes. Las acciones ya no dependen
de que el puntero esté sobre la tarjeta.

Las revisiones de aprobación, rechazo, eliminación y descarga conservan el
contrato existente. Cada acción captura el documento mostrado; un rechazo abierto
mantiene esa revisión aunque cambie la lista. Un conflicto recarga sin repetir la
mutación. Aprobar y eliminar mantienen confirmación nativa con IDs; rechazar
mantiene el diálogo y exige un motivo no vacío de hasta 2000 caracteres.

Una operación pendiente bloquea las demás mutaciones y las recargas. El cierre
del diálogo pendiente se impide; un fallo normal conserva el motivo o el archivo
y tipo elegidos. Un resultado tardío de otra ficha no notifica ni inicia lecturas.
La subida ofrece solo los cuatro tipos del backend, retirando el certificado de
antecedentes que siempre era rechazado. Reutiliza la validación existente de
extensión, MIME declarado y tamaño máximo 10 MiB antes del servicio. Esto no
sustituye la validación de bytes del servidor.

## Evidencia local nueva

| Control | Resultado |
| --- | --- |
| Casos adicionales | **52 aprobados**, perfiles, permisos, documentos, cargas y retiro de operaciones |
| Regresión focalizada con revisión documental anterior | **57 pruebas / 2 suites aprobadas** |
| Suite frontend completa | **2341 pruebas / 113 suites aprobadas**, 36,828 s |
| Cobertura global | **58,53 % sentencias; 54,83 % ramas; 54,32 % funciones; 57,70 % líneas** |
| Mínimos y selección de cobertura | Sin cambios; pasan los cuatro mínimos de 50 % |
| TypeScript y build con lint | Aprobados; **48 páginas**, 18 advertencias existentes |
| Chromium sobre build final | **65 comprobaciones**: perfil/documentos 16 y los seis smokes anteriores 49 |
| Navegador | **0 escrituras de negocio y 0 excepciones JavaScript**, datos sintéticos interceptados |
| Descarga | PDF sintético descargado desde el endpoint autenticado con If-Match de la revisión mostrada |
| Formato y workflow | Prettier, Black y actionlint aprobados |

Jest simula los servicios y comprueba escrituras correctas, fallos, conflictos y
respuestas tardías. Chromium utiliza el bundle standalone real y bloquea métodos
de escritura: comprueba presentación, validación, permisos, cancelaciones y una
descarga sintética. El nuevo smoke se incorpora al contenedor requerido de CI,
conservando los seis anteriores. No certifica revisión o subida integral contra
staging ni accesibilidad integral.

Backend, servicios, dependencias y formulario original de orden sin cambios.
El tipo RiderDocument añade únicamente el rider_id opcional que devuelve el
endpoint de gerencia. No se atribuye una corrida backend local nueva.
El propietario autorizó explícitamente publicar esta entrega y abrir su PR.
El CI remoto se observa por SHA y se distingue de estas pruebas locales. El
registro queda en el PR y `/workspace/work/entrega79/ci-observation.json`.
Bundle incremental, patch, ZIP de fuentes sin archivos de entorno, hashes,
registros y capturas se conservan en `/workspace/work/entrega79`.
Sin merge, deploy, migraciones ni operaciones productivas desde el agente.
Continúan pendientes las verificaciones de infraestructura, staging, carga,
restauración y proveedores de las entregas anteriores.

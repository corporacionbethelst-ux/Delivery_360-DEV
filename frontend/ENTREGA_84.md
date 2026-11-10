# Entrega 84 — Roles y permisos

Fecha de registro: **10 de noviembre de 2026, UTC**.
Rama: `feat/role-permission-review-v1`.
Base main: `59405226ad1c88606dd209807e4865ab90e0c8a6`, árbol
`df8b22f62a443f0a60c7cc88c43e519c6cc8148e`. El propietario integró la entrega
83 mediante PR #325; su CI completo terminó aprobado.

## Presentación y consulta

Roles y Permisos adopta el encabezado azul/cian y las tarjetas e indicadores de
la línea visual de órdenes. Las tarjetas de roles tienen acento violeta, conteo
de cuentas, identificadores completos y permisos desplegables con controles
nativos. El catálogo agrupa las fichas por módulo y conserva módulos desconocidos
como texto. La navegación a Gestión de cuentas usa su ruta existente.

La pantalla muestra **capacidades declaradas**, no promete accesos efectivos:
la autorización se verifica en cada operación. Los endpoints de la API siguen
admitiendo lectura administrativa para gerencia y superadministración; Auditor
y los demás roles no obtienen acceso nuevo a esta página. La comparación no
modifica permisos ni asignaciones.

- Roles y catálogo de permisos tienen consultas, errores, horas y reintentos
  independientes. Un fallo conserva la última lectura confirmada del origen
  correspondiente. Una consulta inicial fallida no se presenta como vacía.
- Se retira la lista local de permisos de respaldo: un error del catálogo ya no
  muestra capacidades de ejemplo como si las hubiera confirmado el servidor.
  Los IDs declarados por roles sin ficha disponible permanecen visibles.
- Se conservan cero cuentas, listas de permisos vacías y banderas false reales.
  El total suma solo las cuentas de los roles cargados e incluye activas e
  inactivas; no representa usuarios conectados ni cuentas fuera de esos roles.
- La búsqueda de roles considera nombres, IDs, descripción y permisos declarados.
  La búsqueda de permisos considera ID, nombre, descripción y módulo. Ambas
  normalizan acentos. Los filtros son locales y no generan HTTP por cada tecla.
- Una selección de rol o módulo que desaparece durante una recarga sigue
  identificada como no disponible; no se cambia silenciosamente por Todos.
  Las horas de ambas lecturas se muestran en America/Caracas. Son dos consultas
  independientes; la API no proporciona una revisión conjunta de la matriz.

## Comparación y CSV

Se pueden seleccionar de **dos a tres roles**. La matriz conserva el orden elegido
y compara el catálogo cargado más las referencias declaradas por esos roles sin
ficha. Los estados **Declarado / No declarado** son texto y color; no significan
conceder, revocar ni comprobar permisos efectivos de una solicitud.

Las vistas muestran todos los permisos, solo los compartidos o solo diferencias.
Buscar permisos y filtrar módulo afectan el catálogo y la comparación; filtrar
tarjetas de roles no retira las columnas ya seleccionadas. Hay botones para
retirar un rol o vaciar la selección. Si un rol seleccionado desaparece del
catálogo tras recargar, su ID sigue visible y debe retirarse para volver a comparar.
La tabla móvil admite desplazamiento horizontal con teclado, foco visible e
indicación de uso; no ensancha el documento.

CSV descarga exactamente las filas visibles y los roles seleccionados, incluyendo
las fechas confirmadas de ambos catálogos. Se genera localmente a partir de esas
lecturas: no existe una llamada a un endpoint de exportación de roles. Reutiliza
la codificación CSV que protege prefijos de fórmula, Unicode, comillas y saltos
de línea, y que libera enlaces y Blob URLs después de iniciar la descarga.

La descarga se bloquea mientras hay una lectura pendiente o fallida, si falta un
origen confirmado, si quedan roles seleccionados sin ficha o no hay filas visibles.
Un error al preparar el archivo permite reintento y no presenta éxito ficticio.

## Servicio y ciclo de vida

El servicio valida arrays, identidades y slugs únicos, nombres, módulos, tipos,
permisos sin duplicados, conteos enteros seguros no negativos y bandera de sistema.
Deja de inventar cero cuentas, permisos vacíos o is_system=true cuando faltan los
campos. Identidades y módulos nuevos se preservan. Los mapas admiten literalmente
nombres como __proto__ sin convertirlos en propiedades del prototipo.

Ambas lecturas quedan vinculadas a su generación de credenciales. La frontera
de acceso existente se monta antes de consultar y retira catálogo, selección y
estado local al cambiar cuenta, rol o credenciales. Las respuestas de una lectura
anterior o de StrictMode no reemplazan la lectura vigente.

Las firmas create/update/delete del servicio se conservan para compatibilidad,
pero rechazan localmente las mutaciones que el backend ya prohíbe sobre sus roles
de sistema. La interfaz no ofrece creación, edición ni eliminación de roles.
Los endpoints, la matriz declarada y los controles de acceso del backend no cambian.

## Evidencia

| Control | Resultado local |
| --- | --- |
| Casos nuevos | **70 aprobados**: 42 contratos de servicio y comparación, 28 de página y sesión |
| Suite frontend completa | **2694 pruebas / 122 suites aprobadas** |
| Cobertura global | **64,09 % sentencias; 60,27 % ramas; 61,28 % funciones; 63,66 % líneas** |
| Mínimos y selección | Sin cambios; pasan los cuatro mínimos de 50 % |
| TypeScript y build con lint | Aprobados; **48 páginas**, 16 advertencias existentes |
| Chromium | **137 comprobaciones**: roles 16 y los once smokes anteriores 121 |
| Navegador | Lecturas sintéticas y CSV local real; **cero escrituras de negocio y cero excepciones JavaScript** |
| Formato y workflow | Prettier, Black y actionlint aprobados |

Jest verifica respuestas incompletas, cero y false, duplicados, sesiones retiradas,
StrictMode, filtros, comparación, selección y alcance del CSV. Chromium revisa el
bundle standalone real en escritorio y móvil, descarga y lee archivos CSV,
comprueba prefijos de fórmula y usa el teclado para desplazar la matriz. El nuevo
smoke se añade al frontend-container requerido conservando los once anteriores.
No se certifican accesibilidad integral ni flujos de negocio contra staging.

Backend y dependencias sin cambios; no se atribuye una nueva corrida backend local.
El CI remoto se registra por SHA en el PR y en `/workspace/work/entrega84` junto a
logs, capturas, manifest y verificación. Se conservan ZIP sin archivos de entorno,
bundle incremental verificado, patch y hashes. Publicación por rama y PR previamente
autorizada; sin merge, deploy, migraciones ni operaciones productivas del agente.
Formulario original de orden sin cambios. Continúan pendientes infraestructura,
staging, carga, restauración, proveedores y protección de main.

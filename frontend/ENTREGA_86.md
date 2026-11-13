# Entrega 86 — Configuración con revisión atómica

Base main: `17662e197918c85b2d7e72b0abb56e6e0bb620d1`, árbol
`6910e8c2c050d6048ea48da59052bfcaf0b1a334`. Rama de trabajo:
`fix/platform-settings-atomic-revisions-v1`.

## Protección frente a cambios simultáneos

La API devuelve una revisión opaca de configuración y exige `If-Match` en PATCH,
PUT y sus variantes con barra final. Compara la revisión con los registros
refrescados y bloqueados en PostgreSQL. La comparación, actualización y auditoría
se ejecutan dentro de la misma transacción, sin commit entre la comprobación y
la escritura. Dos escritores con la misma revisión tienen un solo ganador; el
otro recibe 412 y no sobrescribe valores ni añade una auditoría de éxito.

La inicialización de claves ausentes utiliza inserciones que toleran conflictos
de clave primaria. Las consultas iniciales simultáneas mantienen un registro por
clave. Se conservan null, cero, false y la precisión de los importes. La revisión
normaliza representaciones numéricas equivalentes y detecta cambios seguidos de
una reversión. La respuesta identifica el guardado propio sin una consulta
posterior al commit que pueda observar otra escritura.

El backend rechaza claves desconocidas y números no finitos. Solo SUPERADMIN
guarda; GERENTE continúa consultando y simulando. Los modelos físicos, permisos,
dependencias y rutas se conservan. Los controles del esquema OpenAPI reconocen
únicamente el delta explícito de revisión, If-Match y prohibición de campos extra;
los snapshots históricos anteriores permanecen intactos.

## Formulario y recuperación

El servicio valida la revisión de cada lectura y la envía al guardar. Se mantiene
la consulta previa que detecta cambios en los campos editados y permite conservar
cambios concurrentes a otros campos mediante el payload parcial. La API cierra
ahora la carrera que quedaba entre esa consulta y el PATCH.

Un 412 muestra el conflicto, conserva el borrador y bloquea el reintento con la
revisión anterior. Recargar pide elegir si se conserva o se descarta el borrador.
Se mantienen la confirmación de valores guardados y propuestos, el bloqueo de
duplicados y la retirada de respuestas de sesiones anteriores. El aviso utiliza
el panel ámbar existente y la acción azul, con comprobación visual en móvil.
El formulario original de órdenes y la fórmula del simulador no cambian.

## Imports y verificación

Se comprobó que `import jwt` resuelve exclusivamente a **PyJWT 2.15.1**, la versión
de requirements, y que el módulo heredado jose no está instalado. `pip check`
no encuentra requisitos incompatibles. Los tests de seguridad JWT, revocación,
contratos de autenticación e imports forman parte de la suite backend.

| Control | Resultado local |
| --- | --- |
| Casos nuevos | 40: 30 backend y 10 frontend |
| Contrato HTTP y PostgreSQL nativo de configuración | 30 aprobados |
| Arranque, imports y preservación de API | 88 aprobados |
| Suite backend completa con PostgreSQL/PostGIS y Redis temporales | 2626 aprobadas, 2 omitidas; 695,58 s; cobertura total redondeada de 73 % |
| Suite frontend completa | 2790 pruebas / 124 suites aprobadas |
| Cobertura frontend | 65,20 % sentencias; 61,47 % ramas; 62,40 % funciones; 64,92 % líneas |
| TypeScript y build con lint | Aprobados; 48 páginas y 16 advertencias preexistentes |
| Configuración en Chromium | 15 comprobaciones; 2 PATCH sintéticos, cero escrituras reales y cero excepciones JavaScript |
| Navegador completo exigido por CI | 152 comprobaciones / 13 smokes aprobados; cero escrituras reales y excepciones JavaScript |
| Backend estático | Flake8, Black y mypy aprobados; 195 módulos revisados por mypy |

Los logs y la verificación por SHA se conservan en
`/workspace/work/entrega86/verification.json` y en el PR de esta entrega. Las dos
omisiones de la suite backend corresponden a los SDK opcionales Firebase y
Twilio no instalados; las pruebas PostgreSQL nuevas se ejecutaron, sin omisiones.

## Compatibilidad y alcance

**Los clientes de escritura deben actualizarse:** sin If-Match la API responde
428. El frontend nuevo necesita la API nueva; coordinar ambos componentes al
desplegar. Las lecturas conservan sus campos y añaden revision. No se requieren
migraciones ni paquetes nuevos. El protocolo completo y sus límites están en
[backend/PLATFORM_SETTINGS_CONCURRENCY.md](../backend/PLATFORM_SETTINGS_CONCURRENCY.md).

La concurrencia se comprueba en PostgreSQL con conexiones independientes;
SQLite solo verifica el contrato HTTP. No se atribuye esta garantía a escrituras
SQL externas que omitan el protocolo. El navegador usa una compilación de
producción local con API sintética; no certifica E2E de staging. Continúan
pendientes la infraestructura, staging, carga, restauración, proveedores,
protección de main y la revisión de moneda y modelo de proyección del simulador.

Se conservan evidencia, capturas, ZIP sin archivos de entorno, patch y bundle
fuera del repositorio. Publicación por rama y PR previamente autorizada; sin
merge, deploy, migraciones ni operaciones productivas del agente.

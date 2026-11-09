# Entrega 78 — Repartidores y registro fiable

Fecha: 8 de noviembre de 2026, America/Caracas.
Base main: `ad8c214477ebcefde908a339be693a6d33e486f0`, árbol
`f46f07a41e8781f95839ff782d0e44cfa7e7f413` (entrega 77, PR #319 integrado
por el propietario; su CI completo terminó aprobado).
Rama: `feat/rider-catalog-and-registration-v1`.

## Presentación y catálogo

El catálogo y el registro de repartidores adoptan los encabezados, tarjetas y
controles compartidos de operaciones. Se conserva la referencia del formulario
de nueva orden, sin modificarlo: azul para identidad, violeta para vehículo y
ámbar para zona/acceso. Se revisaron capturas de escritorio y móvil de ambas vistas.

La búsqueda por nombre, contacto, placa e ID admite tildes y filtra los registros
cargados junto con el estado. Los contadores explican ese alcance. Los enlaces
reales de perfil y documentos identifican al repartidor y funcionan con teclado.
Se retira el menú sin acción y el editor modal que no podía abrirse.

Una ausencia de estado o disponibilidad no se presenta como Pendiente o
Desconectado. Los vehículos de empresa se muestran desde la asignación incluida
en el repartidor, verificando que sus IDs coincidan. Consultar vehículos
disponibles para resolver una asignación existente era incorrecto: esos vehículos
ya asignados quedan fuera del catálogo de disponibilidad. Se elimina esa lectura
adicional y la sustitución por datos de vehículo propio anteriores.

El listado admite SUPERADMIN, GERENTE y OPERADOR, de acuerdo con la lectura del
backend. El alta sigue reservada a SUPERADMIN y GERENTE. La frontera compartida
acepta roles explícitos, conservando los dos roles anteriores como valor por
defecto. El servidor mantiene su autorización. Cambios de cuenta, credenciales o
rol retiran lecturas anteriores; un fallo de actualización conserva la última
consulta confirmada. Un fallo inicial se distingue de un catálogo vacío.

## Registro y asignación

- El documento CPF se incluye ahora en el payload que ya admite y persiste el
  backend. Se valida su límite de almacenamiento de 14 caracteres. No constituye
  verificación de identidad ni validación fiscal de documentos de un país.
- Se exige nombre y apellido reales, sin completar partes inventadas. Se recortan
  espacios de contacto, documento y zona. La contraseña exige ocho caracteres,
  conforme al servicio existente, y rechaza una cadena formada solo por espacios.
- Se retira la fecha de nacimiento: era obligatoria en pantalla, pero el contrato
  y el modelo actuales no permiten guardarla. No se añade un campo ficticio ni
  una migración.
- Las consultas de disponibilidad distinguen fallo de resultado vacío y retiran
  respuestas de una propiedad anterior. Cada selección conserva su vehículo y
  revisión; los conflictos requieren recarga explícita como antes.
- La prueba con Radix real detectó una selección que quedaba vacía al reemplazar
  las opciones después de una consulta vacía. La rama del campo tiene identidad
  propia y solo acepta candidatos presentes. Un evento vacío transitorio no borra
  la selección confirmada. Se verifican recarga, selección y revisión en Chromium.
- Se bloquean campos durante el envío y después del éxito; un cerrojo inmediato
  impide duplicados. Resultados y temporizadores de navegación se retiran al
  desmontar la pantalla. Un error de navegación posterior al alta informa que el
  registro ya se completó, sin ofrecerlo como creación fallida.

## Evidencia local nueva

| Control | Resultado |
| --- | --- |
| Casos adicionales | **32 aprobados**, catálogo, roles, registro y asignación |
| Regresión focalizada con asignación existente | **37 aprobados / 2 suites** |
| Suite frontend completa | **2289 pruebas / 112 suites aprobadas**, 42,332 s |
| Cobertura global | **57,67 % sentencias; 53,45 % ramas; 53,46 % funciones; 56,69 % líneas** |
| Mínimos y fuentes de cobertura | Sin cambios; los cuatro mínimos de 50 % pasan |
| TypeScript, lint y build | Aprobados; **48 páginas**, 19 advertencias existentes, sin desactivar reglas |
| Chromium sobre build final | **49 comprobaciones**: repartidores 9, flota 15, entregas 8, catálogo auditoría 7, detalle 7 y smoke de producción 3 |
| Tráfico de negocio en navegador | Datos sintéticos interceptados, **0 escrituras y 0 excepciones JavaScript** |
| Formato y workflow | Prettier, Black y actionlint aprobados |

Jest simula los servicios y comprueba payloads, guardados, errores y respuestas
tardías. Chromium usa el bundle standalone real, valida interacciones y bloquea
escrituras de negocio; no certifica un alta integral contra staging. El nuevo
smoke de repartidores se incorpora al contenedor requerido de CI, conservando los
cinco anteriores. Backend, servicios, dependencias y formulario original de orden
sin cambios; no se atribuye una corrida backend local nueva.

El propietario autorizó explícitamente publicar la rama y abrir el PR. El CI
remoto se observa por SHA y su resultado se distingue de estas pruebas locales.
El estado de publicación y CI queda en el PR y en
`/workspace/work/entrega78/ci-observation.json`.
Bundle incremental, patch, ZIP de fuentes sin archivos de entorno, hashes,
registros y capturas se conservan en `/workspace/work/entrega78`.

Sin merge, deploy, migraciones ni operaciones productivas desde el agente.
Siguen pendientes las verificaciones de infraestructura, staging, carga,
restauración y proveedores documentadas anteriormente. Main continúa sin
protección en la consulta remota de esta entrega; esta mejora no certifica
preparación completa para producción.

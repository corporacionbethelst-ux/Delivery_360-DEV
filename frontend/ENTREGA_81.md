# Entrega 81 — Centro personal de alertas

Fecha: 8 de noviembre de 2026, America/Caracas.
Base main: `2815ac9774ead59d36cc1b0d92a6625b86f14a2c`, árbol
`4b0e9d86640be28c599c6c16d9f61f4397b3d23b` (entrega 80, PR #322 integrado por
el propietario). El CI completo de la entrega 80 terminó aprobado.
Rama: `feat/personal-alert-center-reliability-v1`.

## Presentación y alcance

Gerencia y operador utilizan un centro compartido, con encabezado azul/cian,
tarjetas de consulta, indicadores de página y etiquetas de severidad, lectura y
tipo. Sigue la referencia del formulario de orden sin modificarlo. Los controles
de lectura y descarte quedan visibles, con enlaces reales a orden y repartidor;
la navegación de vuelta y órdenes respeta el modo de la pantalla. Se revisaron
capturas de escritorio, móvil, tarjeta y ambos diálogos.

La pantalla identifica las alertas como una bandeja personal de notificaciones
operacionales. Leer o descartar no resuelve la incidencia operativa ni confirma
un SLA. Una alerta crítica mantiene su severidad al leerse. Se retiran los mensajes
de Todo limpio o sistema sin alertas que una consulta parcial no podía afirmar.
Las fechas son absolutas en America/Caracas; las fechas futuras no se convierten
en Justo ahora, y las inválidas o ausentes quedan explícitas.

## Consulta y acciones

- El estado consulta al servidor: todas, no leídas o leídas. Búsqueda con tildes y
  severidad filtran únicamente la página cargada, con alcance y contadores claros.
- Se muestran hasta 50 registros. Una lectura de 51 permite confirmar si existe
  otra página sin inventar un total global; el siguiente offset avanza 50. Los
  registros descartados se ocultan localmente sin convertir el resultado parcial
  en una afirmación global. La paginación por offset no congela el conjunto ante
  notificaciones nuevas o eliminadas.
- Una consulta fallida conserva tarjetas, filtro confirmado y hora de lectura.
  Si se solicitó otro estado, ambas consultas se distinguen y las acciones quedan
  bloqueadas hasta confirmar la nueva. Un fallo inicial no simula vacío, cero o
  fecha exitosa. El reintento conserva exactamente el estado y offset solicitados.
- Las respuestas anteriores no reemplazan una consulta nueva. Cambios de cuenta,
  rol o credenciales retiran lecturas, acciones y diálogos; la frontera de acceso
  se monta antes de consultar para los tres roles operativos. StrictMode y
  desmontajes también retiran resultados antiguos.
- Leer todas requiere confirmación que explica su alcance: todas las alertas
  personales no leídas, incluidas otras páginas y las excluidas por filtros locales.
  Se anuncia el contador real devuelto por el servidor, conservando cero.
- Descartar identifica título e ID en un diálogo y mantiene el endpoint DELETE.
  Una operación pendiente bloquea duplicados, recargas, cambios de consulta y
  cierre del diálogo. No se actualizan las filas mediante suposiciones optimistas.
  Después del éxito se consulta nuevamente la primera página del estado elegido.
- Un resultado incierto conserva los registros y requiere una lectura confirmada
  antes de repetir una acción. Si el guardado se confirmó pero falla la lectura
  posterior, se informa cada resultado sin repetir la escritura.

## Servicio y contratos

El servicio deja de convertir cuerpos que no son arrays en una bandeja vacía.
Valida filtros, límite 1–200, offset entero, límite de respuesta, identidades
únicas, campos del contrato y coherencia entre isRead, status y estado solicitado.
Tipos y severidades desconocidos se preservan con presentación neutra; no se
convierten en SYSTEM o LOW. Las fechas no informadas siguen siendo desconocidas.
Los IDs se codifican completos en las acciones.

Las respuestas quedan vinculadas a la generación de credenciales original.
Los acuses individuales deben identificar la alerta solicitada, y el contador
global debe ser un entero no negativo. Se conservan los endpoints y la autorización
personal del backend. Los consumidores anteriores mantienen sus URLs sin offset;
la prueba heredada se actualiza para usar el acuse real del backend en lugar de
undefined. No se cambian las APIs de incidencias operativas, SLA o la campana.

## Evidencia local nueva

| Control | Resultado |
| --- | --- |
| Casos nuevos | **75 aprobados**, contratos, páginas, acciones y sesión |
| Regresión focalizada | **87 pruebas / 3 suites aprobadas**, con el panel anterior |
| Suite frontend completa | **2472 pruebas / 117 suites aprobadas**, 42,392 s |
| Cobertura global | **61,02 % sentencias; 57,13 % ramas; 57,36 % funciones; 60,27 % líneas** |
| Mínimos y selección | Sin cambios; pasan los cuatro mínimos de 50 % |
| TypeScript y build con lint | Aprobados; **48 páginas**, 18 advertencias existentes |
| Chromium sobre build final | **91 comprobaciones**: centro de alertas 14 y los ocho smokes anteriores 77 |
| Navegador | Datos sintéticos, **0 escrituras de negocio y 0 excepciones JavaScript** |
| Formato y workflow | Prettier, Black y actionlint aprobados |

Jest simula los servicios y comprueba acciones confirmadas, errores, contadores,
reconsultas y resultados tardíos. Chromium usa el bundle standalone real y bloquea
escrituras; comprueba presentación, filtros, paginación, respuestas malformadas,
reintentos y cancelaciones. No certifica acciones integrales contra staging ni
accesibilidad integral. El nuevo smoke se añade al contenedor requerido de CI,
conservando los ocho anteriores. Evidencia en `/workspace/work/entrega81`.

Backend, dependencias y formulario original de orden sin cambios. No se atribuye
una nueva corrida backend local. El propietario autorizó publicar esta entrega y
las próximas mediante ramas y PRs, sin fusionar ni desplegar. El CI remoto se
observa por SHA y se distingue de las pruebas locales; registro en el PR y
`/workspace/work/entrega81/ci-observation.json`.
Se conservan bundle incremental, patch, ZIP sin archivos de entorno, hashes y
capturas. Sin merge, deploy, migraciones ni operaciones productivas del agente.
Continúan pendientes infraestructura, staging, carga, restauración y proveedores.

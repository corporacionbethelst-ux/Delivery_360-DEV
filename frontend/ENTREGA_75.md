# Entrega 75 — Operaciones con una identidad visual coherente

Fecha: 8 de noviembre de 2026, America/Caracas.
Base limpia: `99310d91c548b1cfddb191b216c543aa44910174`, árbol
`4f0d913ea983fb2829c5b77c65b76c632a4fe979` (entrega 74, PR #316 fusionado por el propietario).
Rama: `feat/operations-visual-polish-v1`, revisión contra main.

## Cambios

Se adopta como referencia el formulario actual de nueva orden: secciones claras,
iconos con color, fondos suaves, acciones principales azules y jerarquía sobria.
El formulario mantiene su estructura y su código sin modificaciones.

La línea se aplica a tres pantallas:

1. **Entregas registradas:** encabezado azul/cian, filtros agrupados, indicadores
   con alcance explícito, etiquetas de estado y SLA, tabla más legible y botones
   con iconos. El total filtrado, las filas de la página y las coincidencias locales
   se distinguen; no se añaden métricas inventadas.
2. **Catálogo de auditoría:** encabezado índigo/violeta, indicadores por categoría,
   tarjetas de repartidor con identidad y disponibilidad claras, filtros uniformes
   y acceso al detalle más visible.
3. **Detalle de auditoría:** secciones de órdenes, entregas y contabilidad con iconos
   y acentos diferenciados, datos agrupados y navegación uniforme. Las órdenes de
   apoyo siguen separadas de las entregas registradas.

`OperationsUI.tsx` comparte encabezados, avisos, indicadores, etiquetas y estilos
de controles. Es presentación, sin estado privado, cálculos financieros ni llamadas
a API. Se mantienen los hooks, servicios, permisos, consultas confirmadas, retiros
por sesión, reintentos, IDs y CSV existentes. Los desconocidos se muestran en tonos
neutros; cero y false conservan su significado. El verde de disponibilidad o SLA
no implica confirmación bancaria.

En móvil, las acciones y encabezados se apilan; los controles ajustan al ancho y
las tablas desplazan su contenedor. Se añaden foco visible y desplazamiento con
teclado en entregas, cabeceras de columna explícitas, iconos decorativos ocultos
al lector y respeto de movimiento reducido en indicadores de carga. No se declara
una certificación integral de accesibilidad.

La [guía visual](VISUAL_GUIDELINES.md) deja este criterio documentado para las
actualizaciones siguientes, respetando la estructura y el carácter del sistema.

## Validación de esta entrega

| Control | Resultado local nuevo |
| --- | --- |
| Regresión inicial de las tres páginas | **51 pruebas aprobadas** |
| Suite frontend final | **2208 pruebas / 109 suites aprobadas**, 29,623 s |
| Cobertura global | **54,82 % sentencias; 50,80 % ramas; 50,32 % funciones; 53,46 % líneas** |
| Umbrales y selección de cobertura | Sin cambios; los cuatro mínimos de 50 % pasan |
| TypeScript y ESLint | Aprobados; 21 advertencias anteriores, sin desactivar reglas |
| Build final | **48 páginas**, Next 15.5.29 standalone, Inter real y API `/api/v1` |
| Chromium sobre build final | **25 comprobaciones**: entregas 8, catálogo de auditoría 7, detalle 7 y producción 3 |
| Escritorio y móvil | Capturas revisadas; escritorio 1440 px y móvil 390 px |
| Contratos preservados en navegador | Filtros, paginación, errores/reintentos, CSV, cambio de ruta y logout |
| Teclado | El contenedor de entregas recibe foco y ArrowRight desplaza la tabla |
| Tráfico de negocio en navegador | Datos sintéticos interceptados, **0 escrituras y 0 excepciones JavaScript** |
| Python de smokes | Black aprobado |
| Backend y dependencias | Sin cambios en este delta; no se atribuye una nueva corrida backend local |

Las capturas móviles usan el viewport y desactivan las transiciones durante la
captura, evitando imágenes intermedias. La toma de la tabla espera el pintado
después del desplazamiento. Los smokes conservan todos sus controles anteriores;
no se sustituyen por capturas estáticas ni se desactivan fallos para hacerlos pasar.

El CI completo de la entrega 74 terminó aprobado. Esta entrega se revisa con su
propio SHA y su propio CI, sin heredar ese éxito. El estado observado se registra
en el PR y en `/workspace/work/entrega75/ci-observation.json`.

## Publicación y alcance

PR sin draft contra main, sin merge ni deploy desde el agente. Se conservan bundle
incremental, patch, ZIP de fuentes sin archivos de entorno, hashes y capturas en
`/workspace/work/entrega75`. Las validaciones son locales y de CI; no se accede a
pagos, mensajería, facturación o datos productivos. Las validaciones de staging,
infraestructura y proveedores pendientes en la entrega anterior siguen pendientes.

# Entrega 80 — Mapa de repartidores y consultas fiables

Fecha: 8 de noviembre de 2026, America/Caracas.
Base main: `ac28753ed8ea8e3e2e098e16b50e933e60d43413`, árbol
`ce65bb3cc435454ab84ef0d125bd23c183157718` (entrega 79, PR #321 integrado por
el propietario). El CI completo de la entrega 79 terminó aprobado.
Rama: `feat/rider-map-reliability-v1`.

## Mapa y presentación

El mapa de flota sigue la referencia del formulario de orden y los últimos
catálogos: encabezado azul/cian, tarjetas de consulta y filtros, indicadores con
alcance explícito y sección cartográfica violeta. Listado y mapa permanecen en el
flujo de la página; en móvil se apilan y se pueden alcanzar mediante scroll.
Se elimina el encabezado flotante que tapaba contenido y el listado absoluto que
ocultaba el mapa móvil. Los controles conservan etiquetas y foco por teclado.

Se conservan coordenadas cero y posiciones históricas de repartidores
desconectados. Ambos valores deben ser números finitos y cumplir los rangos
latitud ±90 / longitud ±180; ausencia, cadenas y valores fuera de rango no crean
marcadores. La ausencia se describe sin diagnosticar una avería GPS. Estado y
disponibilidad desconocidos no se convierten en Pendiente o Desconectado.

El título describe un mapa de últimas ubicaciones registradas. Cada tarjeta y
popup muestra la fecha real en America/Caracas; las fechas ausentes o inválidas
no se sustituyen por Ahora. La hora de consulta se informa por separado y solo
cambia después de una lectura confirmada. La consulta periódica no se presenta
como seguimiento continuo ni confirma la vigencia de una señal histórica.

El encuadre inicial utiliza los puntos válidos; una consulta sin posiciones usa
una referencia mundial, sin inventar un centro en São Paulo. Centrar funciona
también en cero, y Ajustar a los puntos visibles encuadra el filtro actual. Los
filtros ajustan el encuadre; las recargas periódicas conservan la vista elegida.
Un ResizeObserver mantiene el tamaño de Leaflet al cambiar el diseño y se retira
al desmontar. Los cambios de vista se realizan sin animaciones de vuelo.

La búsqueda por nombre, contacto, placa o ID admite tildes. Combina estado,
conexión y validez de ubicación localmente sobre la consulta confirmada, sin
peticiones nuevas. El vehículo de empresa usa la asignación incluida con IDs
coincidentes; no reutiliza una placa propia anterior. Las tarjetas permiten abrir
el perfil aun sin coordenadas. Los marcadores admiten teclado y su popup conserva
estado, email, vehículo y fecha, con enlaces reales a perfil y teléfono. El enlace
teléfono se ofrece solo para un número utilizable; sustituye Contactar sin acción.

## Lecturas y fallos

- Frontera de sesión para SUPERADMIN, GERENTE y OPERADOR, antes de montar el mapa.
  Cambiar cuenta, rol o credenciales retira lecturas, timers y el mapa anterior.
  No se modifica la autorización del backend ni se añaden escrituras de negocio.
- Las lecturas manuales y automáticas se serializan. Se programa la siguiente
  consulta 20 segundos después de terminar la anterior, incluido el caso de error.
  No se acumulan intervalos mientras una petición sigue pendiente.
- El usuario puede pausar y reanudar. Ocultar la pestaña cancela el próximo timer;
  mostrarla vuelve a consultar si el modo automático está habilitado, sin solapar
  una petición pendiente. Una petición ya enviada puede terminar mientras la
  pestaña está oculta. Desmontar o el ciclo de StrictMode retira respuestas antiguas.
- Un fallo inicial no informa un listado vacío, contadores cero o fecha exitosa.
  Un fallo posterior conserva la consulta confirmada y ofrece reintento. Los
  fallos de transporte usan un aviso claro en español.
- El fallo de teselas informa que el fondo cartográfico no se cargó, conservando
  listado, coordenadas y marcadores. Reintentar recrea la capa. Se mantiene el
  proveedor OpenStreetMap existente y su atribución; los iconos son HTML local,
  sin descargar iconos externos.

## Evidencia local nueva

| Control | Resultado |
| --- | --- |
| Casos adicionales | **56 aprobados**, mapa, permisos, filtros, ciclos de consulta, sesión, Leaflet y recuperación |
| Suite frontend completa | **2397 pruebas / 115 suites aprobadas**, 41,529 s |
| Cobertura global | **59,45 % sentencias; 55,61 % ramas; 55,64 % funciones; 58,64 % líneas** |
| TypeScript y build con lint | Aprobados; **48 páginas**, 18 advertencias existentes |
| Chromium sobre build final | **77 comprobaciones**: mapa 12 y los siete smokes anteriores 65 |
| Navegador | **0 escrituras de negocio y 0 excepciones JavaScript** |
| Formato y workflow | Prettier, Black y actionlint aprobados |

La cobertura final y los registros se conservan en
`/workspace/work/entrega80/verification.json`. Los mínimos de 50 % y la selección
de fuentes permanecen intactos.

Jest prueba la coordinación y los comandos de Leaflet con servicios simulados.
Su referencia de estilos apuntaba a identity-obj-proxy, que no estaba instalado;
se sustituye por un stub local de hojas globales, sin nuevas dependencias. El CSS
real y Leaflet se comprueban en el navegador sobre el bundle standalone.

Chromium intercepta datos de negocio y todas las teselas, rotuladas como prueba
local sin cartografía real. Comprueba marcadores reales de Leaflet, centrado,
popup con teclado, enlaces, filtros, pausas/reanudación, fallos de lectura y fondo,
recuperación y ajuste de los puntos dentro de la vista móvil. No certifica
disponibilidad del proveedor externo, precisión geográfica ni carga con flotas
productivas. El smoke se añade al contenedor requerido de CI, conservando los
siete anteriores. Las capturas utilizan datos y teselas sintéticos.

Backend, servicios, dependencias y formulario original de orden sin cambios. No se
atribuye una nueva corrida backend local. El propietario autorizó explícitamente
publicar esta entrega y las próximas mediante ramas y PRs en el mismo repositorio,
sin fusionar ni desplegar. El CI remoto se observa por SHA y se distingue de estas
pruebas locales. Registro en el PR y `/workspace/work/entrega80/ci-observation.json`.
Bundle incremental, patch, ZIP de fuentes sin archivos de entorno, hashes,
registros y capturas se conservan en `/workspace/work/entrega80`.
Sin merge, deploy, migraciones ni operaciones productivas desde el agente.
Continúan pendientes infraestructura, staging, carga, restauración y proveedores.

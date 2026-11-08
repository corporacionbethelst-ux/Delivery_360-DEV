# Entrega 76 — Flota con color, claridad y controles accesibles

Fecha: 8 de noviembre de 2026, America/Caracas.
Base limpia: `8a77eab2c0d34d962227047d551c480cc5337e64`, árbol
`e40079c6188a85c6dd378c417831354cf08bacd7` (entrega 75, PR #317 fusionado por el propietario).
Rama: `feat/fleet-visual-polish-v1`, revisión contra main.

## Cambios visuales y de uso

Se continúa la referencia del formulario de nueva orden, conservando su estructura
y código. Se revisan tres pantallas de flota:

- **Inventario de vehículos:** encabezado azul/cian, filtros con alcance explícito,
  iconos de vehículo coherentes, tabla más legible y acciones siempre visibles con
  nombre accesible. El contenedor de la tabla permite foco y desplazamiento con
  teclado en móvil. Las confirmaciones de baja conservan sus revisiones y conflictos.
- **Registro de vehículo:** identificación azul, seguro ámbar y observaciones
  violeta; controles uniformes y acciones adaptables a móvil. El selector de tipo
  queda asociado a su etiqueta. Se mantienen campos, payload y flujo de registro;
  los años fraccionarios se rechazan antes del servicio, que ya los rechazaba.
- **Zonas:** encabezado índigo, tarjetas con acentos del color configurado, enlaces
  nativos y una vista esquemática identificada como tal. Muestra hasta ocho
  coincidencias de la consulta cargada; no representa un mapa geográfico.

El encabezado compartido admite una etiqueta de sección opcional para distinguir
flota de operaciones. Los encabezados anteriores mantienen su texto predeterminado.
No se aplican estilos globales a módulos sin revisar.

## Correcciones de fiabilidad y representación

Una lectura antigua de vehículos ya no reemplaza una búsqueda posterior. La
consulta cargada se identifica por su búsqueda y tipo; un fallo conserva la última
consulta confirmada. Las lecturas de zonas también retiran respuestas anteriores.
Las respuestas recibidas después de desmontar la lectura no actualizan la pantalla.

Un fallo inicial no se presenta como inventario o catálogo vacío. Los estados de
vehículo desconocidos se muestran explícitamente sin romper la tabla. Un ID de
repartidor sin nombre no aparece como Sin asignar; la fecha de seguro ausente se
indica como no informada.

Los contadores de zonas ausentes no se convierten en cero. Las tarifas conservan
cero y se presentan con moneda no informada porque esta consulta no proporciona
moneda; no se añade un símbolo monetario arbitrario ni se realiza conversión.
Crear una zona preserva decimales en la tarifa, rechaza nombres vacíos tras trim,
expone nombres y selección de colores y bloquea el borrador mientras guarda.
El estado pendiente de eliminación se restablece al terminar, permitiendo otra
operación confirmada posterior. Las confirmaciones existentes siguen siendo
obligatorias; ninguna prueba de navegador envía una escritura de negocio.

Se conserva el alcance acotado: vehículos solicita hasta 500 registros; zonas
explicita la primera página de hasta 100. Buscar zonas filtra solo lo cargado.
No se añade paginación completa ni se afirma un total global.

## Evidencia nueva

| Control | Resultado local |
| --- | --- |
| Casos nuevos de flota | **12 aprobados**, carreras, desconocidos, errores, precisión y formularios |
| Regresión inicial de vehículos y operaciones | **62 pruebas aprobadas** |
| Suite frontend final | **2220 pruebas / 110 suites aprobadas**, 41,651 s |
| Cobertura global | **56,00 % sentencias; 51,55 % ramas; 51,73 % funciones; 54,84 % líneas** |
| Mínimos globales y fuentes incluidas | Sin cambios; los cuatro mínimos de 50 % pasan |
| TypeScript, ESLint y build | Aprobados; **48 páginas**, 20 advertencias existentes, sin desactivar reglas |
| Navegador sobre build final | **33 comprobaciones**: flota 8, entregas 8, catálogo auditoría 7, detalle 7, producción 3 |
| Flota en Chromium | Búsqueda/reintento, confirmación/cancelación, teclado, esquema acotado, decimales, colores y validación local |
| Tráfico de negocio | Lecturas sintéticas interceptadas; **0 escrituras y 0 excepciones JavaScript** |
| Capturas | Escritorio y móvil, incluido diálogo de zona; revisión visual de las tres pantallas |
| Formato y release | Prettier, Black del smoke, **8 unittest** y actionlint 1.7.7 con SHA256 oficial verificado |
| Backend, servicios, dependencias y formulario original de orden | Sin cambios; no se atribuye una nueva corrida backend local |

Las pruebas de creación y eliminación usan servicios simulados dentro de Jest.
El navegador solo prueba formularios inválidos, selección y cancelación: bloquea
cualquier método de escritura. Las pruebas con respuestas parciales o estados
futuros comprueban representación robusta; no cambian el contrato de la API.
El nuevo smoke se añade al contenedor frontend de CI conservando los cuatro
scripts anteriores. No se declara certificación integral de accesibilidad.

El CI completo de la entrega 75 terminó aprobado. Esta revisión tiene su propio
SHA y CI; su estado observado se conserva en el PR y en el workspace. El cierre
local no hereda un resultado global de un commit anterior.

## Entrega y límites

Se publica un PR sin draft contra main, con bundle incremental, patch, ZIP de
fuentes sin archivos de entorno, hashes, registros y capturas en
`/workspace/work/entrega76`. No se ejecutan merge, deploy ni operaciones productivas.
Continúan pendientes las validaciones de infraestructura, staging y proveedores
documentadas en entregas anteriores.

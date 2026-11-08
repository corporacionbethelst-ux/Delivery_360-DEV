# Línea visual Delivery360

Referencia indicada por el propietario: el formulario de nueva orden, en
`src/app/(dashboard)/manager/operations/orders/new/page.tsx`. Conservar su
estructura y su uso de colores por sección, manteniendo una interfaz profesional.
Aplicar este criterio a las próximas mejoras frontend.

## Color con propósito

- Base blanca y gris muy claro; títulos en slate oscuro, textos secundarios legibles.
- Azul para la acción principal y la gestión operativa; índigo/violeta para auditoría.
- Verde para disponibilidad o cumplimiento confirmado; ámbar para atención y estados
  pendientes; rojo/rosa para fallos. Desconocidos y cancelados, en tonos neutros.
- El color siempre acompaña una etiqueta. No convertir ausencia de datos en éxito,
  importes agregados en saldo disponible ni estado contable en confirmación bancaria.
- Fondos de sección suaves, bordes finos, esquinas redondeadas y sombras discretas.
  Reservar los colores saturados para iconos, indicadores y acciones principales.

## Estructura y comportamiento

Mantener el orden de las secciones, formularios, tablas, filtros, permisos y acciones
del flujo existente. Los encabezados explican el propósito de la página; los iconos
ayudan a reconocer secciones sin sustituir sus títulos. Usar una jerarquía de títulos
y espaciado uniforme. Evitar paneles o gráficas que solo decoren o inventen métricas.

Los indicadores deben aclarar su alcance: consulta filtrada, página o coincidencias
locales. Conservar cero, false, IDs y datos desconocidos. Los estados de carga,
fallo y vacío deben distinguirse y mantener el reintento existente.

En móvil, los encabezados y acciones se apilan. Los controles y las tarjetas se
ajustan al ancho disponible. Las tablas extensas desplazan su propio contenedor,
con foco visible y acceso por teclado. Los iconos decorativos usan `aria-hidden`;
los controles conservan nombres accesibles. Respetar la preferencia de movimiento
reducido y evitar animaciones decorativas permanentes.

## Reutilización y comprobación

`src/components/operations/OperationsUI.tsx` reúne encabezado, títulos de sección,
tarjetas de indicadores, etiquetas, avisos, vacíos y estilos de controles del módulo
de operaciones. Es presentación: los hooks, servicios y reglas de negocio conservan
la responsabilidad sobre datos y acciones. No imponer estos estilos globalmente a
formularios o módulos que todavía no se han revisado.

La entrega 76 aplica estos componentes también al inventario y registro de
vehículos y al catálogo de zonas, con una etiqueta de sección propia de flota.
Se mantienen azules para identificación, ámbar para seguro y violeta para
observaciones/cobertura. Las acciones de fila deben permanecer visibles en móvil
y teclado; las paletas de color deben ofrecer nombres accesibles y selección
explícita. Los esquemas de zonas se identifican como esquemas y muestran su límite.

Antes de publicar una actualización visual, comprobar el build real en escritorio y
móvil, revisar capturas y ejecutar las regresiones relevantes. Las pruebas Chromium
existentes de entregas y auditoría interceptan datos de negocio: permiten revisar
presentación, navegación, CSV y reintentos sin enviar operaciones reales.

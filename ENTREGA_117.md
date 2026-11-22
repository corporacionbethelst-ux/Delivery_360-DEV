# Delivery360 — entrega 117

La revisión de la entrega 116 detectó que la barra secundaria del repartidor móvil cubría el encabezado de la campana global. El recibo persistido seguía disponible, pero la comprobación de visibilidad del DOM no detectaba esa superposición.

La barra del repartidor pasa a z-20, debajo del encabezado global z-30. Sus menús conservan su contexto y la navegación existente. Se mantienen el diseño, los importes, las consultas y los contratos financieros; no se modifica el componente de la campana ni se añade una migración.

La aceptación de producción incorpora el layout real del repartidor en cuatro anchos (320, 390, 768 y 1024 px). Comprueba encabezado, cuerpo del recibo y enlace mediante nueve puntos de impacto por elemento, además del ancho disponible, apertura/cierre con la campana y cierre exterior con el menú secundario abierto. El mismo control se aplica al recibo del ciclo funcional con backend real. La prueba nueva falla contra la compilación de 116 por el encabezado cubierto antes de aplicar la corrección.

Este bloque cierra el defecto visual documentado, no los demás pendientes de producción. Continúan los avisos de asignación y otros eventos sin persistencia transaccional, la aceptación de recorridos restantes, homologación externa y objetivos operativos descritos en PRODUCCION_PENDIENTES.md. No se habilitan proveedores, despliegues ni migraciones de la base original.

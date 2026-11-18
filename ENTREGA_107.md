# Delivery360 — entrega 107

Los listados de órdenes del operador y del repartidor, el detalle de orden del
operador y el detalle de entrega consultan el precio versionado exacto. La fuente
es `pricing` de la orden: subtotal, envío, total y artículos con textos decimales
y revisión. Se valida coherencia con BigInt y se presenta USD con sus centavos,
sin transformar el precio a Number ni reconstruirlo desde alias numéricos.

Una orden antigua sin ese precio queda con aviso de revisión. Un precio inválido
no se reemplaza por el importe de compatibilidad, los artículos anteriores o un
cero. Un precio exacto cero permanece visible. Cantidad o precio unitario ausente
en un artículo de subtotal conservado no se inventan.

El repartidor ve «Precio de la orden» en lugar de «A cobrar»: el total del precio
no equivale al saldo pendiente después de abonos ni confirma cobros o ganancias.
Los libros de cobros, devoluciones, créditos, reservas y disponibilidad siguen
siendo independientes. No se cambian reglas de cobro ni se altera el precio.

El detalle de entrega consulta la orden identificada por `order_id` y comprueba
ambos extremos del vínculo con la entrega. No utiliza importes anidados ni alias
de la entrega como fuente monetaria. Si falla esa consulta, conserva el detalle
operativo y ofrece reintentar solo el precio. Un fallo de actualización señala
la lectura anterior como última confirmada. Cambiar de ruta, vínculo, cuenta o
credenciales descarta las continuaciones pendientes y las lecturas de otra sesión.

Se mantienen permisos y contratos HTTP existentes; no hay endpoint ni migración
nuevos. Los precios históricos Float y sus monedas originales siguen almacenados
sin backfill o reetiquetado. El resolutor numérico anterior permanece por
compatibilidad, sin consumidores activos en estas pantallas.

La interfaz conserva su estructura y usa tarjetas azules/verdes, avisos ámbar,
revisión visible y tablas de artículos con desplazamiento interno en móvil.
El detalle usa la asignación canónica del repartidor para no presentar una orden
asignada como vacante. El formulario de creación y edición de órdenes conserva
su diseño y comportamiento.

## Validación y prueba

Las pruebas comprueban centavos, cero, importe máximo, artículos exactos,
ausencia, corrupción, identidades, permisos, cambio de sesión y reintentos.
También verifican la asignación canónica del repartidor. El recorrido Chromium
consulta datos reales como Operador, Gerente, Superadmin y repartidor, verifica
escritorio/móvil y compara huellas de las tablas para impedir escrituras de
negocio en la prueba. Los resultados completos de cobertura, tipos, compilación,
CI y recuperación se registran en `work/entrega107`.

Conservar cambios propios y respaldar la base local antes de reconstruir:

```sh
docker compose up -d --build --no-deps backend frontend
```

Recargar con Ctrl+F5. Como operador, abrir `/operator/orders`, el detalle de una
orden con precio registrado y el de su entrega: deben coincidir total, envío y
revisión. Como repartidor, abrir `/rider/my-orders`: los precios exactos conservan
sus centavos y una ausencia no muestra cero. Revisar también móvil. No borrar ni
volver a sembrar volúmenes.

El laboratorio conserva sus 123 órdenes, 90 entregas y 52 documentos, con respaldo
privado antes y después. No se fusiona main, despliega ni migra producción.
El siguiente bloque revisa saldos del perfil y tarifas de zonas. Bancos, BCV
automático, staging y aceptación siguen en PRODUCCION_PENDIENTES.md.

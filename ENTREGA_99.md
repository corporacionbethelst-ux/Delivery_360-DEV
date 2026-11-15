# Entrega 99 — solicitud de retiro con importes exactos

El formulario consulta `/payouts/balance/exact`, valida al propietario y conserva
los centavos con cadenas decimales y BigInt. Acepta punto o coma decimal, rechaza
más de dos decimales, compara el saldo exacto y limita el retiro a 99.999.999,99 USD.
Un fallo de lectura deja el saldo no disponible y bloquea solicitudes nuevas.

El POST existente `/payouts/request` recibe `amount` como texto canónico, por
ejemplo `10.01`, y moneda USD explícita. Su modelo Decimal ya admite este formato;
no se modifica el servidor, la reserva canónica ni las rutas anteriores.
Las respuestas numéricas anteriores se validan en su rango de centavos admitido;
los clientes anteriores y su contrato de compatibilidad permanecen disponibles.

## Recuperación y sesión

Se mantienen las intenciones v1 y sus claves: los centavos enteros están limitados
a 9.999.999.999, muy por debajo del límite seguro de Number. El único paso a Number
al crear la intención convierte un entero BigInt ya acotado, sin multiplicar ni
redondear importes. Las intenciones antiguas se recuperan sin cambiar de clave.

La pérdida de una confirmación conserva la solicitud para consultar o reintentar
la misma clave. Un 404 solo indica ausencia observada y no autoriza descartar la
intención. Se comprueban propietario, clave, importe, método y sufijo bancario;
el perfil también se comprueba cuando existe un saldo confirmado. Cambiar cuenta,
rol o credenciales retira continuaciones anteriores. Doble envío en el mismo render
se bloquea antes de llamar al servidor.

Una solicitud recuperada muestra su importe confirmado como USD aunque falle la
lectura del saldo. El resumen deja de mostrar «moneda no informada» en ese caso.
Las confirmaciones ajenas o contradictorias no limpian los datos de recuperación.
El servicio captura una copia de la intención antes de esperar respuestas.

## Diseño y validación

Se conserva la estructura del formulario con cabecera verde/cian, tarjetas de
saldo, detalles y confirmación; las cifras se adaptan a móvil. El corte del saldo
se muestra en Caracas y las ayudas explican la revisión de la solicitud.

Pruebas de frontend: último centavo disponible, máximos, formato, coma decimal,
metadatos anteriores, fallos de lectura/escritura, propietario/rol, doble envío y
respuestas tardías. La integración Axios usa la respuesta real sintética del
contrato de saldo exacto y comprueba la retirada de continuaciones.

El ciclo Chromium existente incorpora siete comprobaciones: gana fondos mediante
entregas reales del laboratorio, solicita 10,01 desde la interfaz, comprueba 10.01
en PostgreSQL, pierde deliberadamente la respuesta del POST y recupera la misma
solicitud al recargar con la lectura del saldo caída. No hay otro POST ni otra
clave; después se conservan las pruebas de rechazo, liberación de reserva y
aprobación contable. El cierre sigue siendo 11 ganados menos 10 retirados = 1 USD.

Resultados finales y CI se conservan en los artefactos de esta entrega. Los datos
y documentos previos se comparan contra el respaldo; se conservan los nuevos
registros sintéticos y los volúmenes del laboratorio.

## Continuidad y pendientes

La rama parte de main `c98ef8feef88d98210c8a5a5c93cbe43c5c1484d`, que ya contiene
PR340 de la entrega 98. No se modifica main ni se fusionan PR del propietario.
Esta entrega no requiere migración ni recalcula asientos históricos.

Quedan otros consumidores numéricos activos (auditoría operativa, históricos y
vistas de bonos), revisión de moneda histórica, liquidaciones VES con BCV
conservado y conciliación bancaria homologada. No se interpreta una solicitud o
aprobación contable como transferencia bancaria. No se despliega producción.

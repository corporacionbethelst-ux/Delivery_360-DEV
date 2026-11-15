# Entrega 98 — ganancias exactas y propias del repartidor

Inicio, Productividad y Mis Ganancias consultan créditos registrados y saldos
exactos. Se corrige el inicio, que sumaba precios de órdenes entregadas como si
fueran ganancias y sustituía una semana en cero por ingresos históricos. Una
orden sin asiento no genera ingresos en estas pantallas.

## Continuidad

PR 339 de la entrega 97 estaba abierto al iniciar. La rama
`feat/exact-rider-earnings-v2` parte de su código
`4d6467bc1704504ef73eb305acc62320a411b7c9`, conservando todos sus avances. PR 339 se fusionó en GitHub durante el trabajo; se verificó su merge
`58c0650d270351981eaa49ee38c8d8a49e59d7d9`. El nuevo PR tiene base main.
No se fusionan ramas del propietario ni se modifica main para crear la entrega.

## Comportamiento

- `/financial/riders/me/report`: solo REPARTIDOR, ligado a la sesión y sin
  selectores de otra cuenta. Una sentencia determina propietario, filas y corte.
  Incluye historial completo hasta 10.000 movimientos, créditos históricos,
  hoy/últimos 7 días en Caracas y detalle con exclusiones. Un exceso devuelve 409.
- `/payouts/balance/exact`: valores Decimal del mismo cálculo canónico de
  reservas. El retiro ya asentado no se descuenta de nuevo; un completado sin
  débito mantiene reserva. Se revisa la cadena USD y se serializa la lectura con
  la fila del rider. Incoherencia responde 409, sin devolver saldo ficticio.
- Los importes viajan como cadenas y las pantallas usan BigInt. Las rutas
  numéricas anteriores conservan sus contratos y las escrituras no se amplían.
- El historial y saldo tienen cortes independientes. Un fallo del saldo bloquea
  el botón de retiro; un historial confirmado puede seguir exportándose. Un
  fallo de ganancias se distingue de un historial realmente vacío.
- Moneda sin verificar, movimientos sin procesar, fechas ausentes/futuras y
  tipos ajenos quedan separados, sin sumarlos a USD. No se mezclan wallets en
  centavos, precios de órdenes ni cotizaciones VES.
- Exportación del snapshot completo, con propietario, corte, conteos y huella.
  Los cambios de cuenta/rol invalidan datos y continuaciones anteriores.
- El formulario de solicitud mantiene su validación e idempotencia anteriores y
  vuelve a comprobar disponibilidad al guardar. Su contrato de compatibilidad
  y los demás consumidores numéricos siguen pendientes de migración.

No se requiere migración de base ni se recalculan asientos o saldos históricos.
No se realizan transferencias, conciliación bancaria o mensajes externos.

## Validación y laboratorio

Pruebas reales PostgreSQL: aislamiento de propietario, permisos, ausencia de
perfil, cero demostrado, créditos/débitos/ajustes, reservas sin doble descuento,
historia sin moneda, cadena incoherente, límite completo y lectura concurrente.
Los contratos anteriores de retiros se conservan y se prueban por separado.

Las pruebas de frontend verifican los tres consumidores, el contrato contra
respuestas sintéticas reales, cifras incoherentes, cuenta/rol, exportación y
fallos sin ingresos inventados. El ciclo operativo crea su repartidor sintético
y deja una continuación privada 0600 dentro del estado del laboratorio, fuera
de los artefactos publicados. La nueva prueba utiliza esa identidad real; no
modifica credenciales ni perfiles existentes. El ciclo deja su rider de prueba
offline después de completarlo.

Se respalda la base anterior y se comparan los campos de sus filas originales.
Los registros sintéticos nuevos se conservan. Sus documentos se copian al
volumen propio sin sobrescribir contenido diferente; los anteriores permanecen.
Los resultados finales, CI y recuperación se registran en los artefactos de
entrega. No se despliega ni se migra producción.

## Pendientes

Migrar los consumidores restantes de contratos numéricos, revisión explícita de
moneda histórica, liquidaciones VES con BCV conservado y conciliación bancaria
homologada para las entidades indicadas por el usuario. Consultar
PRODUCCION_PENDIENTES.md para los criterios restantes de producción.

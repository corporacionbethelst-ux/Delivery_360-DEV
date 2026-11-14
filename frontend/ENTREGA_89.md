# Entrega 89 — Ciclo real de entrega y liquidación contable

Base main `497fe9c4e761ddcb2a6985893c80649dbe7580cb`, entrega 88 integrada
por el propietario y CI anterior completo aprobado. Rama
`feat/real-delivery-lifecycle-v1`.

## Correcciones del recorrido

El inicio de entrega actualiza orden y entrega bajo el mismo bloqueo y la misma
transacción. Guarda UTC sin zona horaria, como exige el esquema PostgreSQL,
conserva el inicio ya registrado y fija la salida de recogida. Rechaza estados
incoherentes que reabrirían una orden finalizada. Iniciar no genera dinero.

Las coordenadas cero se conservan al avanzar o finalizar una entrega. Diez
regresiones reprodujeron los problemas anteriores; se añadieron también controles
para órdenes entregadas, fallidas o canceladas con una entrega histórica incoherente.
Un comercio cerrado puede reportarse desde la asignación o la recogida, sin
fingir una salida a ruta. Servicio, endpoint unificado y botones del repartidor
comparten esa posibilidad; la causa sigue siendo obligatoria y el bono único.
El diálogo conserva su presentación e incorpora nombres y etiquetas accesibles.

Login y recuperación de sesión comparten un destino según el rol: operador a
`/operator`, repartidor a `/rider` y administración a `/manager`. Se conservan
rutas internas permitidas, incluidos subapartados, y se rechazan destinos externos,
prefijos parecidos y rutas normalizadas hacia otra área. No cambia la autorización
de API ni la presentación del formulario original de órdenes.

## Prueba funcional nueva

`frontend/e2e/local-lifecycle.browser.py` exige el marcador de laboratorio y
confirma que la identidad de API coincide con la base marcada antes de escribir.
Crea un repartidor exclusivo de cada ejecución, con saldo cero; carga cuatro
documentos sintéticos y los aprueba mediante las revisiones reales. No modifica
los perfiles ni la configuración existentes.

Un operador crea/asigna órdenes; el repartidor recoge, inicia ruta y completa
una desde la interfaz real, comprobada también en móvil. En total se verifican
cuatro éxitos, comercio cerrado reportado desde la UI de recogida, un fallo sin
bono y una cancelación. Finalizar
dos veces no duplica los asientos. La documentación pendiente y la cancelación
por operador se rechazan.

El saldo se gana mediante esas operaciones: 4 × 2,50 + 1 = 11 unidades de prueba.
Una solicitud de 10 reserva saldo una sola vez, incluso al repetirse; el sobregiro
falla y rechazarla libera la reserva. Otra solicitud aprobada registra un único
retiro contable y deja saldo 1. Se comprueban los seis asientos e identidades.
El estado sigue EN_PROCESO: no se ejecuta ninguna transferencia bancaria.

El recorrido pasa **12 comprobaciones reales, cero excepciones JS**. Conserva
IDs parciales de sus datos para diagnosticar interrupciones. CI lo ejecuta después
del laboratorio de la entrega 88. El smoke anterior también admite histórico
ya poblado, sin exigir que permanezca vacío después de completar entregas.

Las pruebas nuevas de login pasan **19 casos**, y hay dos casos de UI para fallar
antes de salir; suite frontend completa: **2839 pruebas / 125 suites**.
Última suite completa backend: **2704 aprobadas, 2 omitidas**. La revisión final
de avance y fallos tempranos pasa **21 casos nativos PostgreSQL**, incluidos ocho
añadidos después de esa suite; CI ejecuta el conjunto ampliado completo.
Los resultados, compilación y evidencias por commit se
conservan en `/workspace/work/entrega89`.

Siguiente bloque confirmado: Venezuela, USD como base y VES con tasa diaria BCV.
El trabajo de moneda no convierte ni reetiqueta importes históricos en esta
entrega. Registro de alcance: [pendientes de producción](../PRODUCCION_PENDIENTES.md).

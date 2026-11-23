# Delivery360 — entrega 120

## Campana de asignaciones después del commit

La entrega 119 conserva el aviso de asignación junto con la operación. Esta
entrega añade la señal `NEW_NOTIFICATION` que permite a la campana actualizar
su bandeja y contador sin que el usuario tenga que abrirla para reconciliar.
Se reutilizan el canal privado Redis, el WebSocket autenticado y la lectura
REST existentes; no cambia el diseño ni el contrato del frontend.

La señal se prepara con el identificador del comprobante IN_APP y solo se
programa después del commit de la transacción exterior. Los eventos de un
savepoint confirmado permanecen provisionales hasta ese commit; un rollback
del savepoint, de su padre o de la transacción exterior los descarta. Repetir
una asignación sin cambios conserva su comprobante y no produce otra señal.

## Aislamiento y fallos

El publicador usa una sesión propia vinculada al mismo motor que confirmó la
asignación. Consulta el comprobante ya persistido y una cuenta destinataria
activa. La señal contiene únicamente identificador, título, código de evento y
fecha. El WebSocket vuelve a comprobar identidad y propiedad del aviso antes
de enviar su contenido al usuario.

La sesión de negocio no se comparte con la tarea posterior. El cliente Redis
pertenece a esa tarea y se cierra al terminar o cancelarse. La publicación tiene
un límite de cinco segundos y conserva referencias a las tareas hasta su fin.
Un fallo de Redis, de lectura posterior o una cancelación no revierte la
asignación ni cambia estados financieros o el aviso guardado.

La bandeja persistida sigue siendo la fuente de verdad. Una caída entre commit
y publicación puede perder esta señal opcional; abrir o reconciliar la bandeja
recupera el aviso. No se garantiza recepción WebSocket ni entrega externa
exactamente una vez. Una sesión ligada directamente a una conexión conserva
la recuperación REST y omite esta señal para evitar compartir su transacción.

## Verificación

Las pruebas cubren commit, rollback, cierre sin commit, fallo de restricción,
savepoints, rollback de un padre, reutilización de sesión, aislamiento entre
sesiones y fallo/cancelación del transporte. La integración usa PostgreSQL,
Redis de loopback en la base de pruebas 15 y el WebSocket ASGI real.

Se comprueba que una asignación confirmada llega una sola vez al destinatario,
que otra cuenta no recibe el aviso, que un rollback no anuncia la asignación y
que Redis no disponible conserva la recuperación por REST. Las regresiones de
asignación, SLA, WebSocket y contratos de API acompañan esos casos.

No hay migración ni nuevo endpoint. Los servicios originales permanecieron
detenidos durante las pruebas; el laboratorio usa datos sintéticos y puertos
dedicados. La rama parte de `b71148c`, con las entregas 118 y 119 ya integradas.

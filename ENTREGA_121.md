# Delivery360 — entrega 121

## Recuperación de avisos con WebSocket conectado

Una conexión abierta no acredita que hayan llegado todas las señales. Si el
proceso se interrumpía después de guardar un aviso y antes de publicarlo, la
campana podía conservar un contador antiguo hasta abrir la bandeja, aunque el
WebSocket siguiera respondiendo correctamente.

El cliente ahora reconcilia la bandeja persistida aproximadamente cada cinco
minutos mientras su conexión en tiempo real está autorizada y abierta. Los
mensajes normales siguen actualizando la campana inmediatamente. La comprobación
es una lectura REST; no crea avisos ni incrementa el contador desde estimaciones.

## Controles conservados

La consulta de recuperación exige la misma identidad y el mismo token que el
socket. Reutiliza la cancelación, secuenciación y comprobaciones de sesión de
las lecturas existentes. Una respuesta tardía de otra cuenta no puede reemplazar
el contenido actual. Al desmontar el componente o cambiar la sesión se cancela
el temporizador junto con las solicitudes anteriores.

Cuando falla el tiempo real se mantiene la consulta alternativa existente,
configurada por defecto cada 60 segundos. El nuevo temporizador no añade otra
consulta simultánea en ese modo. También cede ante una reconciliación inmediata
que ya esté programada por un mensaje o por marcar un aviso como leído.

Un fallo de lectura conserva los datos conocidos y muestra el error existente;
el siguiente ciclo puede recuperarlos. El periodo es por instancia activa y
puede verse afectado por la suspensión de pestañas del navegador. No garantiza
entrega externa ni sustituye la persistencia transaccional del backend.

## Verificación

Las pruebas verifican recuperación de una señal perdida con un socket sano,
ausencia de consultas cada minuto en ese modo, ausencia de consultas duplicadas
en el modo alternativo, descarte de respuestas de otra cuenta y recuperación
tras fallo de lectura. La limpieza de temporizadores se verifica después de
desmontar el componente.

Se mantienen el diseño de la campana, los endpoints, los comprobantes, los
permisos y los estados financieros. La rama parte de `021afc4`, con las entregas
118, 119 y 120 ya integradas. La publicación en main se realizará después de
aprobar los controles de la entrega.

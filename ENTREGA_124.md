# Delivery360 — entrega 124

## Cola externa de avisos de cierre

Los eventos `entrega_completada`, `entrega_fallida` y `orden_cancelada` conservan
su comprobante interno. Además pueden registrar un aviso externo para la misma
cuenta de repartidor cuando hay notificaciones habilitadas, cuenta vigente,
plantilla activa con canal base PUSH/SMS/EMAIL y preferencia compatible.
La cola comparte la transacción del cierre: no hay llamadas a proveedores dentro
de la operación de negocio. No se reconstruyen envíos de cierres históricos.

Se conservan el texto y la referencia de la orden que corresponden al evento.
Las variables no disponibles, incluidas cantidades monetarias u OTP, dejan el
aviso externo bloqueado para revisión; el comprobante interno permanece válido.
El consumidor revalida cuenta, asignación, estado de orden/entrega, plantilla,
canal y preferencias antes del intento. Una pausa o configuración/destino ausente
se difiere sin incrementar el contador de intentos.

## Resultado incierto sin reenvío automático

Antes de invocar al adaptador se confirma un marcador persistente de intento,
con UUID, fecha UTC y huella/destino enmascarado. El registro queda PENDIENTE y
sin próxima ejecución automática. Esto cubre también una interrupción antes de
contactar realmente al proveedor: el marcador no afirma que el envío ocurrió.

Una aceptación positiva literal del adaptador se confirma como ENVIADO. Un
resultado negativo, excepción, cancelación o fallo del commit posterior conserva
el estado incierto y no vuelve a invocar automáticamente al adaptador. Los
adaptadores booleanos actuales no permiten distinguir todos los rechazos seguros
de una aceptación cuya respuesta se perdió. Por eso se prioriza la revisión.

El protocolo evita una segunda invocación de la aplicación para ese registro;
no garantiza exactamente una entrega externa. Los SDK pueden realizar sus propias
operaciones de transporte y PUSH puede dirigirse a varios dispositivos. ENVIADO
representa aceptación del adaptador/proveedor, no lectura ni pago bancario.

## Revisión de Gerente/Superadmin

La página `/notifications` incorpora un panel administrativo con consulta
explícita y paginación: cola, resultados sin confirmar y registros que necesitan
revisión técnica. Muestra la referencia conservada, cuenta, canal, destino
enmascarado y hora de Caracas, sin exponer credenciales ni tokens de dispositivos.

El modal permite confirmar una aceptación verificada mediante una referencia, o
registrar que el resultado sigue sin confirmarse. Esta segunda decisión mantiene
la retención y no reenvía. Ambas registran auditoría. Cada decisión lleva UUID de
revisión y de intento: repetir la misma solicitud no duplica auditoría ni cambia
su significado; una clave reutilizada con otros datos se rechaza. Se revalida el
rol vigente antes de decidir, y se conserva la revisión junto con el resultado.

Las dos rutas nuevas son:

- GET `/api/v1/notifications/terminal-dispatch/review`
- POST `/api/v1/notifications/terminal-dispatch/{notification_id}/review`

Los avisos externos de estos tres eventos no pueden borrarse o marcarse leídos
desde la bandeja personal, ni generarse mediante test-send o el envío genérico.
La retención mantiene los pendientes inciertos. Las respuestas tardías no
actualizan otra sesión; los reintentos tras una respuesta ambigua conservan la
misma decisión. Los errores de validación permiten corregir la referencia.

## Validación y límites

Pruebas de PostgreSQL con adaptadores simulados cubren los tres eventos y canales,
políticas, rollback de negocio, fallos antes/después del intento, dos workers,
aceptación tardía, revisión concurrente, auditoría e idempotencia, retención,
permisos y ausencia de backfill. El frontend comprueba consulta, validación,
reintentos, estados inciertos y aislamiento de sesión. Los contratos históricos
de la API se conservan con un delta explícito para las dos rutas nuevas.

No hay migración de esquema: se reutilizan NotificationLog, su payload versionado
y AuditLog. No se modifican importes, bonos ni saldos. Las pruebas no envían
mensajes reales ni habilitan credenciales de proveedores.

Este protocolo se aplica a los nuevos avisos externos de cierre. Los reintentos
anteriores de asignaciones, retiros y otros eventos mantienen su comportamiento;
queda extenderles la gestión de ambigüedad con su validación específica. También
quedan la consulta automática de resultados, contratos de idempotencia por
proveedor, plantillas/destinos reales y homologación de servicios en Venezuela.
No se considera completada la preparación para producción.

Base: `d30d915` (entrega 123). La integración exige revisar el código y aprobar CI
completo para el commit candidato. El despliegue de aplicación es una acción aparte.

# Delivery360 — entrega 115

Se abordan tres pendientes locales: aislamiento por rol, persistencia del aviso interno de solicitud de retiro y precisión monetaria de notificaciones.

SessionGate comprueba la sección con el perfil verificado por la API antes de montar contenido o sus efectos. La cookie de rol no concede acceso. Cliente/Auditor llegan a una pantalla explícita de portal pendiente con cierre de sesión, sin bucle hacia Gerencia; sus portales de negocio siguen pendientes. El servidor conserva la autorización efectiva.

El ensayo restaurado comprueba identidad, lectura permitida/denegada de retiros y acceso de pantalla para seis roles en contextos nuevos sin cookie de rol. Añade 18 controles a los 13 anteriores. No simula respuestas ni muta negocio; compara el historial después de cerrar los contextos. Producción añade dos regresiones con cookies falsificadas y ausencia de consultas privadas.

El aviso de solicitud de retiro se agrega a la misma transacción que solicitud e historial, con campos compatibles con Notification, JSON y USD explícito. El reintento idempotente no duplica el aviso. Se comprueban fallo de commit/inserción y concurrencia PostgreSQL con sesiones distintas. El aviso es in_app, sin envío externo ni confirmación de transferencia. Si no puede persistirse, tampoco se confirma una solicitud parcial. No hay migración ni reescritura histórica.

payout_context calcula centavos con Decimal, rechaza importes inválidos sin fabricar cero, conserva moneda histórica ausente y evita sobrescribir campos monetarios con contexto adicional. Las plantillas nuevas de seed usan texto USD confirmado y distinguen aprobación contable de transferencia. Las plantillas existentes/personalizadas no se sobrescriben y requieren revisión.

No se garantiza entrega externa exactamente una vez ni se resuelven todos los hooks post-commit. Aprobación/rechazo y otros eventos aún necesitan persistencia durable y coordinación de envío. Siguen pendientes recorridos de negocio, moneda histórica, RPO/RTO/capacidad e integraciones externas. El usuario confirmó continuar en local, sin servidor ni dominio.

Validación local: TypeScript, build, 3529 tests frontend/159 suites, 54 dirigidos backend, 46 PostgreSQL/recuperación, 12 hooks PostgreSQL, 56 scripts y 9 controles Chromium con API sintética. La CI del candidato y sus artefactos validan el ensayo completo real; no reutilizar como aprobación resultados previos. Continuidad y evidencias: /workspace/work/entrega115.

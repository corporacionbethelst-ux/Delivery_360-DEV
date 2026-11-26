# Delivery360 — entrega 127

## Diagnóstico privado de canales externos

Gerente y Superadmin pueden consultar en `/notifications` la configuración local
de correo SMTP, SMS Twilio y PUSH FCM. La consulta es explícita y de solo lectura.
La pantalla distingue canal pausado, configuración pendiente y datos locales
presentes, sin afirmar que un proveedor autenticó o entregó un mensaje.

GET `/api/v1/notifications/providers/diagnostics` devuelve exclusivamente códigos
de comprobación y estados permitidos, fecha UTC, alcance local y la declaración
`external_delivery_verified=false`. Tres modelos de respuesta rechazan campos
adicionales. No devuelve host, usuario, contraseña, token, SID, teléfono,
remitente, proyecto ni ruta del archivo de credenciales. No registra valores
privados ni texto de excepciones de los detectores.

La respuesta usa `Cache-Control: no-store` y `Vary: Authorization, Cookie`.
Conserva la autenticación y el permiso vigente; el middleware no cachea APIs.
La interfaz descarta respuestas de otra sesión y conserva la última consulta si
falla una actualización, identificándola como anterior. El error aparece en un
modal central y la confirmación de consulta usa el aviso inferior derecho.

## Comprobaciones y límites

SMTP comprueba habilitación, host presente sin espacios, puerto, presencia de
credenciales, formato del remitente efectivo, TLS exclusivo y tiempo de espera.
El remitente considera NOTIFICATION_EMAIL_FROM con fallback a EMAIL_FROM,
igual que el transporte. EMAILS_ENABLED es independiente de la pausa global.

SMS comprueba formato de cuenta AC y remitente E.164, presencia de token,
componente opcional y tiempo de espera. PUSH comprueba referencia de credenciales,
metadatos del archivo local regular/no vacío/accesible, componente opcional y
tiempo de espera. No lee el JSON, no carga claves, no inicializa SDK ni consulta
DNS del remitente o conexiones con los proveedores.

Datos locales presentes no validan contenido JSON, identidad, permisos remotos,
saldo/cuotas, rutas hacia Venezuela, reputación del remitente, destinatarios ni
recepción. No se realizan envíos de prueba ni se modifican variables, plantillas,
colas, órdenes, retiros o movimientos. La configuración real continúa en el
entorno seguro de la API; ver PROVEEDORES_NOTIFICACIONES.md.

## Verificación

Pruebas de controles locales, errores y ocultación de valores, ausencia de lectura
de claves/inicialización/red, permisos de seis roles y autenticación PostgreSQL,
no caché y ausencia de escrituras. El frontend comprueba consulta explícita,
duplicados, estados contradictorios, modal de recuperación y aislamiento de sesión.
El delta de una ruta GET y tres modelos mantiene los contratos API anteriores.

No hay migración de esquema. No se habilitan proveedores ni se envían mensajes
reales. La homologación y consulta de resultados siguen pendientes, junto con
aceptación operativa, infraestructura, capacidad y recuperación productiva.
Base: `21f8edf` (entrega 126). La integración requiere revisión y CI completo del
commit candidato. No se despliega la aplicación en esta entrega.

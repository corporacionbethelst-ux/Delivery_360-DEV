# Configuración y diagnóstico de correo, SMS y PUSH

## Consulta segura

Entra como Gerente/Superadmin en `/notifications` y pulsa «Consultar
configuración». La consulta no envía ni acredita mensajes. «Datos locales
presentes» describe controles locales; la aceptación y recepción reales necesitan
homologación independiente con el proveedor y destinos autorizados.

Los valores se configuran en el entorno de ejecución de la API o mediante el
gestor de secretos del servidor. Este panel no guarda credenciales. No publiques
valores reales en Git, capturas, chats, reportes ni imágenes de contenedores.
Un archivo `.env` de Compose puede servir solo para interpolación: verifica que
las variables lleguen efectivamente al proceso de API. Tras cambiarlas, reinicia
únicamente ese servicio según la configuración del proyecto y vuelve a consultar.

## Correo SMTP

| Variable | Uso |
| --- | --- |
| `NOTIFICATIONS_ENABLED` | Habilitación global de canales externos. |
| `EMAILS_ENABLED` | Habilitación del transporte de correo. |
| `SMTP_HOST`, `SMTP_PORT` | Servidor y puerto del proveedor. |
| `SMTP_USER`, `SMTP_PASSWORD` | Credenciales privadas de autenticación. |
| `SMTP_TLS`, `SMTP_SSL` | Solo una modalidad debe estar activa. |
| `SMTP_TIMEOUT_SECONDS` | Mayor que cero y hasta 60 segundos. |
| `NOTIFICATION_EMAIL_FROM` | Remitente específico de notificaciones, opcional. |
| `EMAIL_FROM` | Remitente usado si no hay override de notificaciones. |

Las combinaciones habituales son STARTTLS/587 (`SMTP_TLS=true`,
`SMTP_SSL=false`) o TLS implícito/465 (`SMTP_TLS=false`, `SMTP_SSL=true`),
según el proveedor. No se acepta transporte sin cifrar. El formato del remitente
no demuestra autorización de su dominio; confirma esa autorización con el
proveedor. Esta consulta diagnostica el remitente de notificaciones; otros usos
de correo pueden tener sus propias comprobaciones y destinatarios.

## SMS Twilio

`TWILIO_ACCOUNT_SID` identifica la cuenta (formato AC y 32 caracteres
hexadecimales); `TWILIO_AUTH_TOKEN` es privado; `TWILIO_FROM_NUMBER` usa E.164.
El diagnóstico no autentica la cuenta ni verifica saldo, permisos, origen del
número, rutas o disponibilidad para destinatarios venezolanos.

## PUSH FCM

`FCM_CREDENTIALS_JSON_PATH` debe señalar un archivo regular, no vacío y legible
para el usuario del proceso de API. La ruta debe existir dentro del servicio o
contenedor, no solo en el host. Monta las credenciales de forma privada y de solo
lectura; no las incluyas en la imagen. `FCM_PROJECT_ID` es un override opcional;
su correspondencia remota no se verifica por esta consulta.

El diagnóstico solo inspecciona metadatos y acceso local. No lee ni valida el
contenido JSON, la clave o sus permisos en Firebase. Los dispositivos registrados
y la recepción del usuario tampoco se comprueban aquí.

## Componentes y comprobación real

Los SDK opcionales están fijados en `backend/requirements-notifications.txt`
y se instalan junto con `backend/requirements.txt` en un entorno o imagen
controlados. El Dockerfile base instala los requisitos principales; no presupone
estos componentes opcionales. Su incorporación a la imagen elegida debe
mantener el usuario sin privilegios y los controles de CI.

`NOTIFICATION_PROVIDER_TIMEOUT_SECONDS` está entre 1 y 60 segundos. La presencia
del paquete no confirma que sus dependencias, credenciales o proveedor funcionen.

Antes de operar, homologar con autorización destinos, permisos, remitentes y
resultados reales. Los avisos transaccionales conservan la protección ante
resultados inciertos: no se reenvían automáticamente. El diagnóstico no modifica
ni libera esos registros, ni reconstruye envíos históricos o confirma pagos.

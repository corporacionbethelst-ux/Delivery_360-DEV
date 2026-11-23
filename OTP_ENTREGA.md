# Generación y comunicación del OTP de entrega

## Base preparada

`initialize_delivery_otp` prepara un código de seis dígitos con `secrets.randbelow`.
Conserva ceros iniciales y cualquier código existente para que un reintento no
invalide el código que ya tenga el destinatario. Solo admite entregas abiertas
configuradas con `ProofType.OTP`; no cambia otras modalidades de prueba.

El llamador debe autorizar al usuario y bloquear la fila de entrega antes de
invocarla. La función no confirma transacciones, no envía mensajes y no expone
el código en respuestas de catálogo, auditoría o logs.

La generación está conectada a una operación explícita de correo. No se ejecuta
automáticamente al desplegar ni modifica otras modalidades de prueba. La
validación obligatoria del OTP permanece vigente.

## Uso desde la aplicación

1. Registra el correo del destinatario en el formulario de la orden.
2. Para una orden en ruta cuya entrega esté configurada con prueba OTP, entra
   como Gerente o Superadmin en `/manager/operations/orders`.
3. Pulsa **ENTREGADO** y después **Enviar OTP por correo**. No se envía nada al
   abrir el modal ni se marca la orden como entregada al enviar el correo.
4. El destinatario recibe el código y lo comunica al repartidor cuando recibe
   el pedido. Introduce ese código y pulsa **Confirmar entrega**.

`POST /api/v1/orders/{order_id}/delivery-otp/email` requiere gerencia, orden en
ruta, una sola entrega coherente con su repartidor y prueba OTP. Revalida la
cuenta y su versión de sesión. El código y una solicitud de auditoría se
confirman antes del transporte SMTP. No se mantiene el bloqueo de la orden
durante el envío. Se limita a una solicitud por orden cada 60 segundos, incluso
entre procesos y ante solicitudes simultáneas, mediante bloqueo de la orden y
consulta de auditoría persistida.

El resultado `accepted` significa que el servidor SMTP aceptó el mensaje; no
garantiza recepción en bandeja. Los fallos se muestran dentro del modal. Se
conserva el código para el siguiente intento. Una interrupción entre confirmar
el intento y guardar el resultado deja una solicitud con resultado desconocido;
no implica éxito y permite reintentar tras la espera. El código no se devuelve a
la pantalla ni se incluye en auditoría o respuestas de catálogo.

## Configuración y límites

Configura en el entorno del backend `EMAILS_ENABLED`, `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `SMTP_TLS`, `SMTP_SSL` y
`SMTP_TIMEOUT_SECONDS`, siguiendo los archivos `.env.example`. Usa TLS o SSL
según tu servidor. No guardes credenciales en Git. Si falta configuración o el
correo del destinatario es inválido, se rechaza antes de generar un código.

La integración reutiliza el transporte autenticado SMTP existente. Las pruebas
usan destinatarios sintéticos y transporte simulado: no se han enviado mensajes
reales ni configurado credenciales. Para pruebas reales de recepción hay que
configurar SMTP y usar una orden de prueba con destinatario controlado.

El canal opcional implementado es correo. WhatsApp/SMS y consulta manual del
código por personal no están habilitados. No se fuerza OTP en órdenes que
usan otra modalidad, no se reemplazan códigos previos y no se migran datos.

## Verificación

Las pruebas de inicialización, servicio HTTP y PostgreSQL cubren generación,
ceros iniciales, permisos, reintentos, persistencia anterior al transporte,
rechazo de entregas finalizadas, simultaneidad y ausencia de cambios monetarios.
Los contratos históricos de la API siguen intactos; la nueva ruta y su esquema
se fijan por separado en `delivery_otp_email_delta.json`.

Las pruebas del formulario verifican solicitud explícita, bloqueo de doble
clic, errores, respuestas no confirmadas y descarte de resultados de otra sesión.

# Delivery360 — entrega 132

## Perfil propio del repartidor

La página `/rider/profile` sustituía una carga fallida con datos del navegador,
no protegía sus respuestas tardías con la generación de credenciales y anunciaba
éxito antes de verificar el resultado. Además enviaba todos los campos del
vehículo incluso al cambiar únicamente el contacto y deducía efectos documentales
desde el texto de errores.

La vista ahora se monta únicamente para un perfil verificado REPARTIDOR. Sus
consultas y acciones quedan ligadas a usuario, rol, revisión de sesión y generación
de credenciales, con comprobación antes de GET/PUT incluso si cambió localStorage
antes de que React lo observe. No usa el perfil antiguo como fallback ni persiste
borradores. Una carga fallida bloquea la edición y abre un modal de recuperación.

La lectura valida la identidad de usuario separada del UUID de repartidor, mantiene
estable el UUID de perfil y exige revisiones personales y de asignación válidas.
Proyecta solo los campos necesarios: no muestra saldos, notas ni otros atributos
privados de la respuesta. Verifica los vínculos de vehículo de empresa y conserva
tipos históricos sin sustituirlos al guardar información personal. Incluye PATINETA
entre las selecciones válidas, conforme al enum existente del backend.

## Guardado y concurrencia

Guardar envía únicamente campos modificados y sus precondiciones correspondientes:
revisión personal para nombre/apellido/teléfono y revisión de asignación cuando
cambia el vehículo propio. No manda campos de nivel, disponibilidad, propiedad o
asignación administrativa. Los campos de empresa quedan de solo lectura; sus datos
personales siguen siendo editables sin reenviar el vehículo. Se validan los límites
de longitud del modelo y los nombres vacíos. Cambiar y volver al original elimina
el cambio pendiente.

Un cambio de tipo o placa propia requiere confirmación central antes de enviarse,
explicando su efecto documental y de disponibilidad. Un error no se interpreta como
una invalidación documental ni provoca una redirección automática. Después de
verificar el vehículo actual se ofrece revisar documentos por un enlace explícito.
Las reglas de invalidación y auditoría existentes del backend permanecen intactas.

Se bloquean clics duplicados y escrituras durante la recuperación. Se valida el
perfil del acuse y los campos enviados; después se consulta antes de confirmar éxito.
Si se pierde el acuse, queda un resultado incierto. Si el acuse fue confirmado y
falla la lectura, se conserva esa distinción tras más fallos. La recuperación solo
hace GET, sin repetir PUT. Un 409 exige consulta y revisión explícitas, sin renovar
la revisión y reenviar automáticamente. Las diferencias conservan únicamente los
campos solicitados, y los campos no tocados adoptan el último valor consultado.
Adoptar los valores actuales no escribe.

Una consulta manual con borrador requiere decisión central. Si falla la consulta
autorizada para descartarlo, conserva el borrador bloqueado hasta recuperar datos
válidos. Los cambios concurrentes siguen protegidos por las revisiones existentes;
la lectura posterior no representa un bloqueo ni un snapshot atómico entre endpoints.

## Presentación y validación

Encabezado celeste/índigo/violeta, tarjetas personales, vehículo y documentación,
controles adaptables, decisiones/errores centrales y confirmaciones inferiores
derechas. Corrige también el singular del contador de preferencias de notificación.

Pruebas específicas comprueban revisiones, identidad, canales de error, recuperación,
doble clic, cambio de sesión, respuestas tardías, campos parciales y vehículos.
Chromium con API sintética verifica escritorio, 320/390px, modales y los flujos de
recuperación sin reenvío. CI añade API real en laboratorio marcado: usuario,
repartidor y documento desechables; un cambio personal con respuesta perdida,
consulta de recuperación y un cambio de placa confirmado. Comprueba la revisión
documental, el cierre de disponibilidad y un único evento de auditoría de flota.
Retira exclusivamente los registros de prueba y compara 24 tablas originales,
incluidos usuarios, repartidores, documentos, auditoría, historial y libros monetarios.

No modifica backend, migraciones, dependencias, saldos, pagos o credenciales reales.
Continúan pendientes homologación externa, aceptación de otros recorridos/roles,
carga representativa e infraestructura y recuperación productivas.

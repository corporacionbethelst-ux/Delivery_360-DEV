# Mensajes y confirmaciones de la interfaz

La aplicación monta una sola instancia de FeedbackHost en el layout raíz. Los errores y avisos que requieren atención se muestran en un modal centrado, con título, icono, texto y botón Entendido. Las confirmaciones ofrecen Cancelar y Confirmar. Escape o cerrar el diálogo cancela una confirmación; nunca acepta la operación.

Los resultados correctos y la información no bloqueante aparecen en la esquina inferior derecha mediante Sonner, con cierre accesible y margen adaptable. Los mensajes de validación dentro de formularios y las advertencias persistentes de lectura conservan su contexto; un modal no sustituye sus restricciones sobre datos sin confirmar.

## Uso

```tsx
import { showAlert, confirmAction, toast } from '@/lib/feedback';

showAlert('No se pudo completar la operación.');
toast.info('Lectura actualizada.');
toast.success('Operación confirmada por el servidor.');
```

Para operaciones privadas, capturar la sesión antes de esperar la elección y comprobarla después. Proteger también contra dos invocaciones simultáneas; la cola visual no sustituye la idempotencia del negocio ni los controles del servidor.

```tsx
const task = capturePrivateTask();
if (!(await confirmAction('¿Continuar con esta operación?')) || !task.isCurrent()) return;
await service.mutate();
task.assertCurrent();
```

La cola conserva avisos consecutivos y evita duplicar el mismo error pendiente. Al cambiar las credenciales se descartan mensajes anteriores y las confirmaciones pendientes se resuelven como canceladas. Al desmontar el host también se cancelan. Los textos se renderizan como texto, sin HTML interpretado.

Al cambiar de página se cancelan sus diálogos pendientes. La comprobación de ruta también impide aceptar una confirmación anterior antes de que React termine la navegación. Las notificaciones informativas se conservan al navegar dentro de la misma sesión para que pueda leerse el resultado de una operación completada.

Se sustituyen los cuadros nativos alert/confirm en órdenes, turnos, documentos, perfiles, contactos, integraciones y exportación. Los errores imperativos que usaban Sonner pasan por el mismo sistema central. CSV conserva su contenido, escape y descarga; el aviso informa de que se preparó el archivo, no de una operación financiera.

## Alcance de OTP

La presentación no genera códigos, no convierte una alerta en prueba de recepción y no autoriza una entrega sin el OTP que exige el backend. La captura y transmisión JSON de la entrega118 se conservan. Sigue pendiente definir la emisión/obtención del código o una modalidad administrativa explícita para el caso reportado; no se incorpora una excepción de validación mediante este cambio visual.

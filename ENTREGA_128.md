# Delivery360 — entrega 128

## Runtime opcional de SMS y PUSH verificable

El backend permite construir expresamente la variante que incorpora los SDK de
Twilio y Firebase fijados en `requirements-notifications.txt`:

```bash
docker build --build-arg NOTIFICATION_PROVIDERS=true -t delivery360-backend:notifications backend
```

El valor predeterminado es `false`; cualquier otro valor falla. Los requisitos
principales y opcionales se resuelven juntos y `pip check` bloquea dependencias
incompatibles. La imagen conserva usuario sin privilegios, healthcheck y comando
de arranque. No se incluyen credenciales ni herramientas de pruebas.

## Controles de publicación

Las matrices de seguridad y contenedor comprueban ambas variantes. Cada entorno
resuelto produce inventario y análisis de vulnerabilidades HIGH/CRITICAL. Las
dos imágenes deben arrancar con base y Redis aislados, filesystem de solo lectura,
capacidades retiradas y los controles HTTP existentes. El control final de release
exige el éxito de todas las variantes; un fallo no cancela la otra comprobación.

`scripts/check_notification_runtime.py` ejercita los SDK instalados mediante
transportes sustituidos, credencial anónima y destinos sintéticos, además de
comprobar la pausa global. CI lo ejecuta sin red y con filesystem de solo lectura;
el script también bloquea conexiones y DNS. No usa credenciales del entorno ni
lee el archivo privado de Firebase. La variante base comprueba la ausencia de
ambos SDK. Estos contratos prueban compatibilidad local, no homologación real.

## Límites

La publicación canónica sigue construyendo la variante base. Elegir y desplegar
una imagen con componentes opcionales es una decisión operativa separada; no se
cambia automáticamente Compose, Kubernetes, configuración, colas ni canales.
La presencia de paquetes no autentica proveedores ni acredita aceptación,
recepción o pago. Siguen pendientes homologación real con destinos autorizados,
consulta de resultados, aceptación, capacidad e infraestructura productiva.
No hay cambios de API, frontend, esquema o datos financieros.

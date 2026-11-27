# Delivery360 — entrega 129

## Referencia de rendimiento local con datos conservados

Añade `scripts/local_read_benchmark.py`: ensayo acotado de GET de órdenes,
zonas y configuración exacta, primero secuencial y luego con hasta cuatro lectores.
Comprueba identidad Docker/Compose, puerto loopback y marcador de base antes de
HTTP. Usa una sesión del laboratorio y no admite destinos ni escrituras arbitrarias.

Registra latencias, percentiles de éxitos, errores sin detalles privados y
throughput por etapa. Los fallos permanecen en el denominador y no se reintentan.
Compara las tablas operativas/monetarias protegidas antes y después. No cambia
rate limits, usuarios de negocio, dinero, órdenes, colas o configuración.
El login modifica únicamente los metadatos de autenticación habituales.

CI ejecuta el ensayo después de los recorridos reales y antes de la restauración,
respeta la ventana de solicitudes y conserva el informe. Los contratos comprueban
aislamiento, ausencia de credenciales en métricas, bloqueos de redirección,
rechazo de destinos/puertos ajenos, límites, concurrencia real del pool,
estadística, errores HTTP y detección de cambios en snapshots financieros.

No hay cambios de frontend, API, esquema o reglas de negocio. No se despliega la
aplicación ni se habilitan proveedores. Esta referencia breve no acredita capacidad
productiva ni cumplimiento de objetivos todavía no acordados. Siguen pendientes
homologación externa, aceptación, carga representativa e infraestructura y
recuperación productiva. Ver RENDIMIENTO_LOCAL.md.

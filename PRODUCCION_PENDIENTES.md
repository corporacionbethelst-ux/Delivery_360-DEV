# Cierre para producción — orden acordado

Actualizado con la entrega 90. Este registro distingue implementación local,
pruebas y operación externa. No asigna porcentajes sin criterios de aceptación.

## 1. Ciclo operativo completo

La entrega 89 comprueba por HTTP y Chromium reales: alta del repartidor,
documentos y revisión, permisos, asignación, recogida, ruta, entrega, fallos con
y sin bono, cancelación, saldos, reserva/rechazo y aprobación contable de retiros.
La UI real del repartidor completa una orden; las repeticiones no duplican bonos
ni reservas. También permite reportar comercio cerrado sin salir de la recogida.
Quedan la aceptación del usuario y repetir el recorrido en staging.
Una aprobación contable EN_PROCESO no acredita una transferencia bancaria.

## 2. Moneda y pagos — bloque en curso

Decisión confirmada por el usuario: **Venezuela, base contable USD y conversión a
VES con la tasa oficial BCV del día**.

La entrega 90 incorpora un registro diario de referencias BCV verificadas
manualmente y cotizaciones independientes USD/VES: precisión decimal, redondeo
HALF_UP, fecha del servidor en Caracas, revisión concurrente, reintentos sin
duplicados y comprobantes que conservan su tasa. Las referencias y cotizaciones
persistidas rechazan UPDATE, DELETE y TRUNCATE. Una corrección crea otra revisión.
La API y la pantalla indican que el origen es manual y que no confirman pagos.

Faltan la obtención automática fiable del BCV y la adopción de USD en todos los
flujos contables, tarifas, bonos, órdenes, facturas y retiros. La nueva herramienta
es de cotización (`quotation_only`); no acredita que el libro histórico ya esté
en USD. Los importes anteriores sin moneda verificable requieren revisión; no
se reetiquetan COP como USD ni se convierten usando la tasa actual. La consulta
HTTPS al BCV respondió 503 en este entorno; no se sustituyó por tasas de prueba
ni se omitió la verificación TLS. Véase [MONEDA_VENEZUELA.md](MONEDA_VENEZUELA.md).

El banco/proveedor de pagos todavía no está seleccionado. La integración exige
confirmación externa verificable, prevención de duplicados y conciliación; no
se declara un pago ejecutado a partir de un cambio de estado local.

## 3. Integraciones y facturación

Completar y homologar los proveedores necesarios para el lanzamiento: pagos,
notificaciones, mapas y conectores comerciales elegidos. Confirmar el alcance
fiscal para Venezuela; los adaptadores DIAN/SAT existentes no acreditan emisión
oficial ni cobertura del país seleccionado.

## 4. Procesamiento fiable

Completar persistencia de eventos pendientes, recuperación de tareas tras caídas,
reintentos y conciliación sin efectos duplicados. Verificar la coordinación de
workers y programación, con observabilidad operativa.

## 5. Staging e infraestructura

Preparar dominio, TLS, secretos, PostgreSQL/Redis y almacenamiento persistente;
validar migraciones y compatibilidad de versiones con datos representativos.

## 6. Recuperación y rendimiento

Restaurar realmente un respaldo de base y documentos, comprobar recuperación
ante fallos y ejecutar pruebas de carga con objetivos de capacidad acordados.
Verificar alertas y procedimiento de reversión del despliegue.

## 7. Aceptación y pantallas

Pruebas manuales del negocio en escritorio/móvil y corrección de incidencias.
Completar los recorridos propios de CLIENTE/AUDITOR si forman parte del alcance
del lanzamiento; disponer del rol en API no equivale a tener su portal completo.

## 8. Publicación controlada

CI del commit candidato aprobado, protección efectiva de main y environments,
credenciales mínimas, imágenes identificadas por digest y plan de despliegue
revisado. La aplicación del despliegue productivo sigue siendo una acción
separada autorizada explícitamente; no se realiza desde este registro.

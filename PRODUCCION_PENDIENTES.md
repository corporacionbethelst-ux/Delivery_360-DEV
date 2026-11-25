# Cierre para producción — orden acordado

Actualizado con la entrega 123. Este registro distingue implementación local,
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

La entrega 91 identifica nuevas órdenes, movimientos y retiros en USD, separa
saldos/reservas de registros sin moneda y conserva el historial anterior en null.
Impide aprobar un retiro antiguo contra USD, reetiquetar unidades o sobrescribir
una caché sin moneda verificable. Los reportes USD excluyen datos sin denominación;
la UI conserva su historial y deja de inferir ganancias desde órdenes sin asiento.

La entrega 92 guarda precios nuevos de órdenes con NUMERIC y artículos decimales,
protege ediciones por revisión y conserva los Float anteriores. Los reportes añaden
un subconjunto exacto, sin convertir los indicadores históricos.

La entrega 93 vincula el precio exacto y su revisión a un comprobante USD/VES con
referencia BCV conservada. Incluye revisión visual, reintentos sin duplicados,
permisos, recuperación por enlace e historial inmutable. Una cotización de orden
no acredita cobro ni modifica saldos; los cambios posteriores no recalculan el
documento anterior.

La entrega 94 incorpora cobros de clientes en efectivo USD/VES, transferencia y
pago móvil VES, con abonos parciales y revisión manual por otro gerente o
superadministrador. Los pendientes reservan capacidad sin acreditar cobro; solo
la decisión independiente reconoce USD verificados. Conserva cotización y BCV,
referencia única por caja/cuenta, auditoría e historial inmutable, con reintentos
sin duplicados. El precio se protege mientras existan cobros pendientes o
verificados. Una cancelación expone una devolución pendiente y conserva el cobro.

La entrega 95 añade devoluciones parciales o totales de cobros verificados en
órdenes canceladas o fallidas. Conserva la moneda y BCV del cobro original, con
asignación acumulada de centavos y una sola solicitud en curso por cobro.
Distingue solicitud, aprobación independiente, ejecución declarada y verificación
independiente de la salida. Una ejecución observada mantiene su reserva hasta
comprobar el pago o confirmar expresamente que no salió dinero. El historial es
inmutable y el saldo neto de devolución procede de un libro separado.

La entrega 96 añade el libro exacto de cobros y devoluciones verificados: USD
contable y monedas originales USD/VES separadas, totales por día/medio/caja,
fechas de Caracas y CSV completo del mismo snapshot. No suma libros de riders,
no reconoce pendientes y no representa utilidad ni confirmación bancaria.
La entrega 97 migra las pantallas Resumen y Reportes a una consulta decimal:
precios exactos de órdenes, movimientos procesados del libro canónico y
solicitudes de retiro se presentan separados, con exclusiones trazables y CSV
completo del mismo snapshot. Se retiran de estas vistas los indicadores que
mezclaban devengos con retiros para estimar margen. No se deduce utilidad ni
confirmación bancaria. Las rutas numéricas anteriores permanecen como
compatibilidad; falta migrar a sus demás consumidores y revisar moneda histórica.

La entrega 98 migra las lecturas de Inicio, Productividad y Mis Ganancias del
repartidor a importes exactos. Corrige las ganancias inferidas desde el precio
de órdenes y separa los créditos registrados del saldo disponible. El saldo
exacto conserva el cálculo canónico de reservas, verifica el libro USD y no
habilita retiros con cifras por confirmar. El formulario de solicitud conserva
su contrato e idempotencia anteriores; sigue pendiente migrar sus límites de
compatibilidad y los demás consumidores numéricos.

La entrega 99 completa el formulario de retiro con importes exactos e
idempotencia conservada. La entrega 100 resuelve la carga del catálogo de órdenes
cuando una asignación necesita revisión, conservando las referencias originales.
La entrega 101 migra el resumen y catálogo de auditoría de repartidores a cadenas
USD exactas, con corte de una sola sentencia, exclusiones trazables y consulta
directa por perfil. No resta solicitudes pendientes para inventar disponibilidad.
La entrega 102 migra el listado y detalle de transacciones del gerente a registros
decimales: conserva signo, moneda original, saldos ausentes y filas con importes
por revisar. Añade lectura coherente, CSV trazable y una presentación adaptable.
La entrega 103 migra el historial y la administración de retiros a páginas
decimales exactas y un detalle con historial completo del mismo corte SQL. Conserva
cursores HMAC y contratos de mutación, con confirmación de decisiones comprobada
en centavos y recuperación explícita. Añade CSV de página y separa saldos históricos,
subtotal de solicitudes y disponibilidad.
La entrega 104 migra las tablas del detalle de auditoría: precios NUMERIC
versionados, bonos conservados y movimientos exactos, con CSV de las páginas y
metadatos independientes. No convierte precios Float históricos ni deduce la
moneda del bono desde la orden. La entrega 105 registra USD en los nuevos snapshots de bono, junto con importe,
tipo y fecha, y protege su identidad y campos contra cambios, borrado y truncado
en PostgreSQL. Los snapshots anteriores mantienen la moneda NULL, incluidos los
bonos cero y cierres sin snapshot. Los fallos no bonificables no crean moneda ni
un crédito cero. La auditoría v2 muestra la unidad conservada; la v1 permanece
compatible.
La entrega 106 migra la configuración y simulación de bonos a texto decimal,
con revisión s2 sobre el JSON almacenado, auditoría del valor original y guardado
concurrente protegido. El escenario usa exclusivamente snapshots USD del mismo
corte SQL y hace explícitos los registros excluidos. Productividad y el detalle
de órdenes del repartidor consultan bonos y componentes conservados por una
lectura exacta del propietario, sin COP, estimaciones desde configuración actual
ni aritmética Float del desglose. Cero y ausencia siguen separados. Los contratos
numéricos anteriores permanecen como compatibilidad; continúa la revisión de los
demás consumidores monetarios y de los requisitos externos.

La entrega 107 migra los precios de los listados de operador y repartidor y los
detalles de orden/entrega a la lectura versionada de la orden. Conserva centavos,
artículos y revisión, separa cero y ausencia, y comprueba el vínculo entrega/orden.
Los errores de precio no ocultan el detalle operativo ni reconstruyen importes.
El total se presenta como precio registrado, sin afirmar deuda pendiente, cobro
verificado o ganancia. No añade endpoints ni migra datos. Quedan los multiplicadores de zonas y los consumidores aún no revisados.
La entrega 108 sustituye los saldos del perfil por libro USD, reservas y disponible
canónicos, con acceso financiero para Gerente/Superadmin, aislamiento de sesión
y reintento independiente. El Operador conserva únicamente el perfil operativo.
No modifica históricos ni confirma pagos bancarios.
El plugin tailwindcss-animate se clasifica como herramienta de construcción,
con versiones intactas y controles de seguridad conservados. El aviso abierto
GHSA-fc5q-39xc-vjpf de picomatch sigue pendiente para esas herramientas; la
clasificación no equivale a un parche del proveedor.

Faltan la revisión explícita de moneda histórica, el cierre de los demás reportes
monetarios sobre decimales, la conciliación bancaria automática de cobros y devoluciones y la
aplicación de tasas BCV conservadas a liquidaciones VES
y la obtención automática fiable del BCV. La cotización independiente o ligada a la orden sigue siendo
`quotation_only`; no acredita conversión de saldos anteriores o pago bancario.
La consulta HTTPS al BCV respondió 503 durante el bloque de referencias; no se
sustituyó por tasas de prueba ni se omitió TLS. Véase
[MONEDA_VENEZUELA.md](MONEDA_VENEZUELA.md).

Bancos indicados por el usuario: Banco de Venezuela, Banesco, Provincial,
Mercantil y BOD. Falta verificar los canales oficiales y la entidad operativa
actual de BOD, obtener acceso técnico y homologar cada integración. No se
asocian automáticamente los alias históricos de cajas/cuentas a un banco.
La integración exige
confirmación externa verificable, prevención de duplicados y conciliación; no
se declara un pago ejecutado a partir de un cambio de estado local.

## 3. Integraciones y facturación

Completar y homologar los proveedores necesarios para el lanzamiento: pagos,
notificaciones, mapas y conectores comerciales elegidos. Confirmar el alcance
fiscal para Venezuela; los adaptadores DIAN/SAT existentes no acreditan emisión
oficial ni cobertura del país seleccionado.

## 4. Procesamiento fiable

La entrega 119 guarda el comprobante visible de asignación y los canales externos
permitidos junto con la orden, entrega y auditoría, desde los puntos de entrada
manual, automático y de servicios. Conserva reintentos sin duplicados y utiliza
el consumidor persistido; detiene envíos cuya asignación ya no corresponde al
destinatario. La entrega 120 añade la señal WebSocket después del commit
exterior, con aislamiento de sesión y recuperación REST ante fallo de Redis.
La entrega 121 reconcilia periódicamente la bandeja incluso con un WebSocket
sano, para recuperar señales perdidas sin exigir abrir la campana.
La entrega 122 agrega el comprobante interno de entrega completada en los tres
puntos de cierre, dentro de su transacción operativa y financiera, con deduplicación
y señal privada posterior al commit. Conserva OTP y no acredita pagos externos.
La entrega 123 incorpora avisos internos de fallo y cancelación, con rollback,
deduplicación, propiedad y señal posterior al commit. El fallo en gerencia exige
motivo y cierra orden/entrega mediante la operación coordinada; bloquea el cambio
genérico incompleto y conserva las observaciones. No reconstruye avisos históricos.
Faltan los canales externos de cierre y la conciliación de resultados ambiguos.
Ver ENTREGA_123.md.
Ver ENTREGA_119.md, ENTREGA_120.md y NOTIFICACIONES_DURABLES.md.

La entrega116 agrega comprobantes de solicitud/aprobación/rechazo a la bandeja visible y deja los canales externos autorizados en la cola existente, junto con la transacción financiera. Comprueba cancelación y consumidores simultáneos, protege pendientes frente a retención y añade programación Celery explícita. No garantiza exactamente una entrega externa ni convierte aceptación del proveedor en entrega/pago; quedan los otros eventos y la conciliación de resultados ambiguos. Ver NOTIFICACIONES_DURABLES.md.

La entrega 115 persiste el aviso interno de solicitud de retiro junto con solicitud e historial. Comprueba rollback y reintentos concurrentes sin avisos duplicados. Cierra la ventana de pérdida de ese aviso específico; no equivale a una cola durable para todos los eventos ni a entrega bancaria o externa exactamente una vez.

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

La entrega 118 corrige el cierre con OTP desde el catálogo del gerente: diálogo de confirmación, código en JSON, errores corregibles y consulta de recuperación. Añade envío explícito al correo del destinatario por Gerente/Superadmin, con generación segura si falta el código, preservación de códigos previos, auditoría y espera entre reintentos. Requiere SMTP configurado y correo válido; falta validar recepción real con el proveedor elegido. Conserva la validación central y la compatibilidad de la API. Se prioriza la incidencia reportada antes de continuar los avisos de asignación.

La entrega 117 corrige la superposición de la barra secundaria del repartidor sobre el encabezado de la campana. La aceptación comprueba puntos de impacto del encabezado, recibo y enlace en cuatro anchos con el layout real y en el ciclo funcional; no basta la visibilidad del DOM. Conserva el aspecto y los contratos financieros.

La entrega 115 verifica el rol de API antes de montar pantallas, da salida explícita a perfiles sin portal y añade aceptación restaurada de identidad/acceso para seis roles. No completa sus recorridos de negocio ni los portales de Cliente/Auditor.

Pruebas manuales del negocio en escritorio/móvil y corrección de incidencias.
Completar los recorridos propios de CLIENTE/AUDITOR si forman parte del alcance
del lanzamiento; disponer del rol en API no equivale a tener su portal completo.

## 8. Publicación controlada

CI del commit candidato aprobado, protección efectiva de main y environments,
credenciales mínimas, imágenes identificadas por digest y plan de despliegue
revisado. La aplicación del despliegue productivo sigue siendo una acción
separada autorizada explícitamente; no se realiza desde este registro.

La entrega 99 migra el formulario de solicitud a saldo exacto y montos USD en
texto decimal, conservando claves v1 y recuperación incluso sin saldo disponible.
El ciclo real comprueba reserva de 10.01 y recuperación tras perder la respuesta
sin duplicados. Continúan pendientes otros consumidores numéricos y las respuestas
de compatibilidad del servidor; no se considera conciliación ni liquidación bancaria.

La entrega 100 corrige el bloqueo del listado de órdenes por un vínculo de
repartidor contradictorio: lectura de revisión, referencias conservadas y cambios
bloqueados solo en las filas afectadas. No repara automáticamente el historial.
Los catálogos auxiliares ya no ocultan órdenes confirmadas. Se prioriza esta
incidencia reportada; la migración monetaria de auditoría operativa sigue pendiente.

La entrega 109 incorpora tarifas USD explícitas por zona con almacenamiento
decimal, revisión, bloqueo de fila y auditoría atómica. La migración aditiva
conserva los Float originales sin conversión o backfill. La creación ya no
presupone 4000; la configuración ausente no se presenta como USD cero.
La interfaz separa tarifas y edición operativa, permite leer al Operador y
reservar el guardado a Gerente/Superadmin. No conecta automáticamente estas
tarifas al cálculo de precios ni cambia bonos. Esa regla deberá definirse
expresamente antes de activar un cálculo por zona o distancia.

La entrega 110 incorpora factor decimal explícito por zona, revisión y auditoría
atómica. Los cinco cierres aplican la fórmula completa cuando el factor está
confirmado; las zonas sin confirmar conservan sus reglas anteriores. Se captura
el factor completo y su procedencia sin alterar los snapshots previos de dos
decimales. La migración es aditiva y protege las capturas nuevas de modificaciones
y backfill. Queda revisar los parámetros base JSON de los escritores y mantener
separadas las liquidaciones del pago bancario y de la configuración actual.

La entrega 111 completa la lectura textual decimal de los bonos base JSON en los cinco cierres. Coordina las filas existentes con guardados de configuración mediante bloqueos compartidos, mantiene fallbacks por vía y evita la caché ORM para el insumo. No reescribe settings/historia ni amplía el alias de desglose de base a una captura completa. Continúa la revisión de lectores monetarios de compatibilidad y requisitos externos.

La entrega 112 incorpora respaldo offline y restauración mantenidos del laboratorio, con arranque HTTP de la API en copia y comprobación de documentos, permisos e historial. CI añade el ensayo con la imagen candidata. No cierra recuperación productiva: faltan objetivos RPO/RTO, staging, carga y procedimientos/alertas operativas. Ver RECUPERACION_LOCAL.md.

La entrega 113 añade aceptación de navegador sobre la restauración con API/web candidatas: login real, órdenes/zonas, sesión y escritorio/móvil. Verifica que el historial se conserva después de navegar y bloquea destinos/mutaciones ajenos al ensayo. No acredita todos los roles/recorridos ni despliegue real en staging, RPO/RTO o capacidad productiva.

La entrega 114 corrige el recorte de «Nueva Orden» y la compresión de filtros en pantallas estrechas. Conserva los contratos operativos y añade comprobaciones de geometría y obstrucción por control en cinco anchos, tanto en la imagen web con datos sintéticos como sobre la restauración real. Reproduce además el recorte por un ancestro sin overflow global, para evitar el falso positivo de la comprobación anterior. Integra en su rama de revisión los cambios de 113 que se habían fusionado únicamente en la rama de 112 después de integrar esta en main. Siguen pendientes los demás recorridos/roles, staging, RPO/RTO, capacidad y las integraciones externas indicadas arriba.

La entrega 115 incluye además la migración aditiva de notificationtype: incorpora las etiquetas que el modelo ya declaraba, sin reescribir filas. El downgrade conserva esas etiquetas para evitar pérdida de datos. Aplicar el upgrade antes de habilitar las nuevas escrituras; revisar también las plantillas antiguas que presentan amount_cents como dólares. No se migró la base original ni producción.

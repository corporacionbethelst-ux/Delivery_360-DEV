# Contratos de ejecución y adaptadores internos — entrega 60

Fecha: 30 de octubre de 2026, America/Caracas. Base: main
179728f8a7c00c49bece9bc80525e2bfd36a96d8, que incorpora el PR #300.

## Asignación y avisos locales

La asignación manual confirma Order, Delivery y AuditLog en una misma transacción.
ASSIGN/REASSIGN conserva el rider anterior y el nuevo. Si no se puede guardar la
auditoría, tampoco se confirma la asignación. Una vez confirmada, el aviso legacy
usa `record_legacy_notice` y una sesión nueva del mismo AsyncEngine.

El servicio de notificaciones puede hacer rollback al encontrar un destinatario
inactivo o un fallo de persistencia. Compartir la sesión HTTP expiraba los objetos
ya cargados, podía producir MissingGreenlet/HTTP 500 después de guardar la
asignación y dejarla sin auditoría. La sesión independiente evita ese efecto.
El helper devuelve False ante fallo; no confirma ni revierte una transacción del
llamador. Si recibe una sesión con transacción activa o ligada directamente a una
conexión, omite el aviso. El éxito significa registro en la bandeja local, nunca
entrega por un proveedor externo. No hay outbox ni reintentos durables nuevos.

La asignación automática acepta latitud/longitud cero, valida que el origen sea
finito y esté dentro de rango y filtra posiciones inválidas de candidatos antes
de calcular distancias. Su aviso guarda ambos identificadores: User y Rider,
con canal in_app. No declara un envío externo. El resto de la política de
elegibilidad permanece vigente: unificar también la actividad del User asociado
en todas las vías de asignación sigue pendiente.

## Usuarios y sesiones

Los adaptadores internos AuthService y UserService emplean el emisor/decoder JWT,
la búsqueda y reserva de email y la política de sesión canónicos. Un access token
no sirve como refresh; una época revocada o una cuenta no habilitada se rechaza.
El rol se consulta en la cuenta, no se toma como autoridad de un claim antiguo.
Un hash de contraseña malformado devuelve una verificación fallida.

UserService usa first_name/last_name y los campos físicos existentes. Cambiar
contraseña, rol o actividad revoca sesiones en la misma transacción. Si falla la
revocación, el cambio se revierte. La reserva de email precede al bloqueo del
usuario, siguiendo el orden canónico. La desactivación es reversible: delete_user
desactiva la cuenta, conserva su email y no inventa is_deleted ni un borrado de
datos. Reactivar no resucita JWT anteriores.

Estos son adaptadores internos para código de confianza. La autorización de las
rutas públicas sigue en sus dependencias y sus controles de revisión; el servicio
no reemplaza esos controles ni crea un endpoint administrativo genérico.

## Perfiles de repartidor

RiderService y su CRUD dejan de escribir columnas y estados inexistentes. La
creación exige un User REPARTIDOR existente, identidad de propietario coincidente
y ausencia de otro Rider; usa bloqueo del propietario. Se crea PENDIENTE,
BRONCE y offline, sin autoasignarse privilegios, puntos, badges, nivel o vehículo
de empresa. `commit=False` permite que la unidad del llamador posea el commit;
el adaptador CRUD de creación confirma explícitamente.

La actualización genérica interna admite operating_zone. Cambios de documentos,
perfil regulado, flota, estado, tier o conexión deben pasar por sus flujos
canónicos y responden 409 en ese adaptador genérico. La restricción evita que un
consumidor interno eluda aprobación documental o revisiones concurrentes.

Aprobar/rechazar requiere un actor activo SUPERADMIN o GERENTE, bloqueo del
Rider y una segunda comprobación del actor después de las esperas. La aprobación
exige documentos válidos, aprobados y respaldados por archivos existentes. Las
decisiones escriben ACTIVO/SUSPENDIDO, dejan offline y guardan AuditLog con su
motivo atómicamente. La aprobación no activa la cuenta User. update_status solo
permite los estados restrictivos PENDIENTE, INACTIVO y SUSPENDIDO; activar debe
usar el flujo de aprobación o conexión correspondiente.

`is_approved` en el listado interno significa presencia histórica de approved_at;
no certifica elegibilidad actual. Los documentos se consultan expresamente, sin
depender de cargas lazy en AsyncSession. Las métricas operativas existentes
siguen derivándose de Delivery. increment_delivery_count y update_rating
responden 501 antes de hacer IO porque no existe una columna ni un historial
verificado que permita persistirlos. La valoración verificable sigue pendiente.

## API, tipado y utilidades

Las consultas compuestas de entregas comprueban la ausencia de filas antes de
desestructurar; las respuestas toleran el apellido ausente. Telemetría, ajustes,
radios y auditoría manejan la nulabilidad declarada. El body obligatorio de
vehículos se declara con Body(...) conservando su contrato público.

El CRUD genérico descubre la clave primaria simple real; no presupone `.id`.
Admite UUID o cadenas y devuelve None cuando no existe la fila a eliminar. No
admite silenciosamente una clave compuesta. Las colecciones devuelven listas
cuando su contrato declara listas.

PlatformSetting, Zone y la geometría de Rider usan anotaciones Mapped sin DDL
nuevo. La geometría admite WKBElement y expresiones SQL de escritura. El fixture
runtime_models_contract.json se capturó antes de estos cambios desde main y
compara columnas, nulabilidad, defaults, índices, claves y enums de las tres
tablas. Los fixtures anteriores no se regeneran. PlatformSetting.value conserva
el JSON heterogéneo existente; no se pretende que sus valores estén todos tipados.

Los cálculos informativos de costes devuelven las formas reales de resultados;
los escenarios respetan tarifas y overrides sin duplicar argumentos. Los
resúmenes requieren pagos/costes explícitos y rechazan booleanos y números no
finitos. Siguen siendo cálculos float con el redondeo existente: no sustituyen
el libro contable, la política monetaria o los bonos.

El helper de cumplimiento SLA valida fechas estimadas/reales y normaliza UTC;
una fecha desconocida se rechaza. Conserva sus convenciones anteriores: lista
vacía devuelve 100 y una entrega aún dentro de plazo cuenta provisionalmente
como conforme. No debe presentarse como KPI operativo verificado. Exportaciones,
validación de fechas, rutas, logs y agrupaciones LGPD ajustan sus contratos sin
añadir infraestructura externa.

## Verificación y límites

Se añaden 35 casos de contrato/utilidades y 29 PostgreSQL/HTTP. Cubren rollback,
auditoría atómica, fallo de avisos, coordenadas cero e inválidas, revocación JWT,
email, desactivación, documentos y permisos. Un control negativo reintroduce
solo el aviso con sesión compartida y reproduce HTTP 500; la implementación
corregida pasa ese mismo escenario. Sus resultados completos se registran en
Implementacion_de_mejoras_V1.md.

Mypy pasa de 99 errores en 25 archivos a cero en 192 archivos con las mismas
opciones de CI. No se añaden ignores ni se reduce la cobertura. Quedan las notas
previas de cuerpos de función sin anotaciones: cero errores no significa que
todo el programa esté tipado ni demuestra ausencia de errores de ejecución.

Se conservan 202 rutas, 194 contratos de dependencia y el hash OpenAPI
84bef605f22c31d4e8b3d9279e812d05c3cc8d3d303f73c441248f307dba0172.
No se cambia el frontend, las dependencias, la configuración CI o las migraciones.
La cobertura frontend observada en el CI del PR #300 es 30,28 % de líneas frente
al umbral 50 %; sus 771 tests pasaron, pero ese gate continúa pendiente. No se
presenta esa ejecución anterior como una prueba nueva de esta entrega.

Siguen abiertos el outbox y los proveedores homologados, reparación histórica,
ciclo completo de alertas y bandejas, elegibilidad unificada, ratings verificados,
observabilidad de workers, conciliación y libros/monedas, cobertura y validación
operativa del roadmap. Esta entrega no declara producción completa ni ejecuta
despliegues, migraciones o pagos/mensajes/facturas reales.

## Actualización de la entrega 61

La elegibilidad de cuentas y documentos ahora se comprueba en las cuatro
entradas HTTP de asignación y en los adaptadores OrderService correspondientes.
Se capturan épocas JWT antes de esperar y se conservan permisos/cuentas bajo
bloqueo hasta el commit. Una entrega/ruta con avance no se reinicia. El motivo
completo de aprobación/rechazo se conserva en new_values.reason y su resumen
se acota al VARCHAR(500) existente. Estas correcciones cierran esos pendientes
de la entrega 60; detalles y límites restantes: [ASSIGNMENT_GUARDS.md](ASSIGNMENT_GUARDS.md).

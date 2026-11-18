# Delivery360 — entrega 106

El siguiente bloque migra a decimales los consumidores activos de configuración,
simulación y desglose de bonos. Los importes se transportan como texto y el
navegador conserva centavos con BigInt. La presentación mantiene los paneles
coloridos de operaciones y añade las unidades y el alcance de cada lectura.

## Configuración y revisión

GET/PATCH `/settings/exact/v2` conserva importes USD de hasta dos decimales y
porcentajes de hasta 18. La lectura usa el JSON original, sin reconstruirlo desde
Float. Un valor inválido queda visible como dato por revisar; un vacío no
equivale a cero. El formulario revisa los cambios y comprueba su respuesta antes
de anunciar un guardado. Gerente consulta y simula; Superadmin puede guardar.

La revisión s2 incluye el texto almacenado y evita colisiones de valores que
Float interpretaría iguales. If-Match y los bloqueos compartidos con el escritor
antiguo impiden sobrescribir cambios concurrentes. Una respuesta 412 conserva el
borrador y exige nueva lectura. La auditoría exacta conserva JSON anterior,
revisión y textos enviados, incluso al reparar una configuración inválida.
El contrato anterior de configuración y simulación se conserva con revisión s1.

## Simulación y bonos conservados

Una sentencia SQL captura configuración, reloj y candidatos del escenario USD.
Su fórmula sustituye el bono de las mismas entregas completadas elegibles y
conserva los intentos fallidos USD. Los importes y porcentajes se devuelven como
cadenas decimales. Se separan cero, ausencia, registros sin moneda, otra moneda,
snapshot inválido y cierres sin fecha; estos últimos se señalan como alcance
global. La muestra admite hasta 10000 candidatos y rechaza excedentes. No aplica
zonas/niveles, no es una proyección mensual y no representa saldo ni pago bancario.

La nueva lectura de bonos reúne hasta diez órdenes en un corte PostgreSQL y
comprueba propietario e identidad. Productividad y el detalle de órdenes del
repartidor muestran solamente el importe, moneda, base y factores guardados. Se
retiran COP, las estimaciones desde configuración actual y la reconstrucción de
importes parciales con Float. Un bono cero sigue visible; un importe ausente o
una lectura fallida no se convierten en cero. El reintento solo vuelve a leer.

Las órdenes sin entrega permanecen sin bono sintético. Las unidades históricas
no se deducen de órdenes, asientos o configuración. Los componentes se muestran
como información conservada y no como confirmación de un crédito. Los libros de
ganancias, cobros, devoluciones y retiros permanecen separados.

El script antiguo que recalculaba snapshots históricos está retirado y termina
antes de abrir la base. Los cierres y la inmutabilidad de la entrega 105 siguen
vigentes. No hay una migración nueva ni un backfill.

Los registros de acceso de Uvicorn ocultan credenciales en URLs y cabeceras
Bearer, conservando el formato del registro. Se verifica también con conexiones
WebSocket reales del laboratorio.

## Validación y prueba local

Las pruebas incluyen JSON con precisión que Float oculta, CAS entre versiones,
auditoría atómica, exclusiones monetarias, límites, lectura de propietario,
componentes, cero, ausencia y cambio de sesión. Los contratos anteriores siguen
verificándose. La DDL de UUID de PostgreSQL se representa como CHAR(32) solo en
SQLite de pruebas: evita que identificadores numéricos o con forma de exponente
se conviertan en enteros o infinito. Dos casos reproducen esta corrupción sin
depender del UUID aleatorio; la representación PostgreSQL permanece igual. El frontend aprobó 3406 pruebas en 153 suites con cobertura y
caché fría. Los resultados finales de PostgreSQL, Chromium y CI y los archivos
de recuperación se conservan en `work/entrega106`.

Para probar esta rama, conservar cambios propios y respaldar la base local:

```sh
docker compose up -d --build --no-deps backend frontend
```

No volver a sembrar ni borrar volúmenes. Recargar con Ctrl+F5. Como Superadmin o
Gerente abrir `/manager/admin/settings`, revisar USD y simular un importe como
`0,10`. El guardado es exclusivo de Superadmin y siempre exige confirmación.
Como repartidor, abrir Productividad y una orden completada: su bono debe mostrar
la moneda conservada y sus componentes. Una orden sin importe no debe mostrar un
cero inventado. Los registros históricos siguen sin moneda cuando no la tienen.

El laboratorio conserva sus datos y 52 documentos anteriores, con respaldo
privado antes de las pruebas. No se fusiona main, despliega ni migra producción.
Las integraciones bancarias, BCV automático fiable, staging, aceptación y los
demás consumidores monetarios pendientes siguen en PRODUCCION_PENDIENTES.md.

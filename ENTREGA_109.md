# Delivery360 — entrega 109

Las zonas disponen de configuración USD explícita para tarifa base y tarifa por kilómetro. Se guardan como Numeric(10,2), se transportan como textos decimales y se presentan sin Number ni reconstrucción desde Float. La creación operativa ya no propone 4000 ni asigna moneda automáticamente: una zona nueva queda sin tarifas USD hasta que un responsable las introduce. Un cero debe ser explícito.

La migración aditiva 20261121_zone_tariffs incorpora cinco campos y una restricción de coherencia. Conserva todos los valores antiguos de delivery_fee_base, cost_per_km y bonus_multiplier; no los convierte ni les atribuye USD. Una revisión cero significa configuración ausente, con importes, moneda y procedencia nulos. Las nuevas tarifas no recalculan órdenes ni precios registrados y no modifican bonos. La conexión a reglas automáticas de cálculo queda fuera de esta entrega.

Gerente y Superadmin guardan por PUT /api/v1/zones/{zone_id}/tariff/exact con revisión esperada. Los escritores bloquean la misma fila y una revisión obsoleta recibe 409. La auditoría conserva actor, revisión anterior y nueva, importes y fecha en la misma transacción; si falla, el guardado se revierte. Operador puede leer las tarifas sin control de guardado ni permiso de escritura. Los demás roles no acceden a las rutas nuevas. Las rutas antiguas conservan sus contratos; una zona con USD explícito rechaza actualizaciones de sus tarifas Float mediante la ruta antigua. La edición operativa actual omite esos campos.

La lectura individual valida zona, revisión, importes y procedencia. El catálogo usa una consulta por lote de hasta 100 identidades distintas; una ausencia o respuesta contradictoria se muestra como lectura no confirmada, sin inventar ceros ni esconder los datos operativos. Una configuración vacía aparece como «Tarifas USD sin configurar». No hay una solicitud por cada tarjeta.

La ficha mantiene su estructura y añade tarjetas verdes/azules, avisos ámbar y un guardado de tarifas separado del formulario operativo. Cambiar de cuenta, credenciales, rol o zona descarta continuaciones anteriores. Se bloquean envíos duplicados. Una respuesta de guardado ambigua obliga a consultar antes de repetir una escritura; consultar descarta el borrador y carga la revisión vigente. Los importes introducidos aceptan coma o punto, hasta dos decimales, sin separadores de miles, negativos o exponentes.

## Prueba local

Conservar cambios propios, respaldar base y documentos y utilizar el código de esta rama o el ZIP de entrega 109. Reconstruir backend y frontend con docker compose up -d --build --no-deps backend frontend. El compose de desarrollo ejecuta alembic upgrade head antes del API. No borrar ni resembrar volúmenes. La interfaz nueva necesita la migración; no omitir errores de actualización de esquema.

Recargar con Ctrl+F5. Como Gerente o Superadmin, abrir /manager/fleet/zones, crear una zona operativa y entrar en Configurar. Confirmar que no hay importes USD por defecto; introducir 0,31 y 0,10 en las tarifas y guardar. Deben verse centavos, revisión y fecha de Caracas, y persistir al recargar. La edición de nombre, ubicación o duración usa su guardado operativo. Como Operador, verificar la lectura sin botón de guardar tarifas. Probar escritorio y móvil.

Las pruebas PostgreSQL comprueban migración real, preservación de filas antiguas, precisión, permisos, guardado concurrente, revisión obsoleta, restricciones y reversión por fallo de auditoría. Los contratos frontend verifican identidad, ausencia/cero, sesión, importes, confirmaciones, bloqueos y recuperación. Chromium configura únicamente una zona sintética, comprueba los tres roles y compara las huellas de las tablas originales. Los resultados finales de cobertura, compilación, CI, preservación y recuperación se registran en work/entrega109.

Sin merge de main, despliegue ni migración de producción. El siguiente bloque revisa multiplicadores de zonas y sus consumidores de bonos, todavía de compatibilidad. Bancos, BCV automático, staging, restauración, carga y aceptación siguen en PRODUCCION_PENDIENTES.md.

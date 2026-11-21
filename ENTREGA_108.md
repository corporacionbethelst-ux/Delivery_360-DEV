# Delivery360 — entrega 108

El perfil del repartidor muestra saldo del libro USD, reservas de retiro y disponible contable mediante una lectura canónica independiente del perfil. Sustituye la presentación de wallet_balance y pending_balance de compatibilidad. Conserva centavos como textos decimales, con validación BigInt, y distingue un cero confirmado de una consulta fallida.

GET /api/v1/payouts/riders/{rider_id}/balance/exact permite consultar a Gerente y Superadmin. Los demás roles reciben 403; Operador conserva el acceso operativo al perfil sin consultar las finanzas. Un perfil inexistente recibe 404. El cálculo compartido con el saldo del propietario conserva su contrato, bloquea la fila del repartidor y consulta libro y reservas en la misma transacción. No actualiza cachés ni saldos históricos.

El navegador comprueba repartidor, propietario cuando está disponible, actor y rol. Cambios de cuenta, credenciales o perfil retiran las respuestas pendientes. Un 401/403 retira los importes anteriores; un fallo temporal identifica expresamente la última lectura confirmada y permite reintentar. El error financiero no oculta documentos ni acciones operativas.

La interfaz conserva su estructura, tarjetas verdes, advertencias ámbar y adaptación móvil. Presenta fecha de corte de Caracas, integridad del libro y exclusiones por moneda no verificada. El disponible contable no confirma una transferencia bancaria.

## Verificación

Se añaden 17 pruebas backend, incluidas consultas PostgreSQL y una espera real de bloqueo entre transacciones, y 13 contratos frontend. La suite frontend local completa pasa 3.464 pruebas en 156 suites; TypeScript, lint y compilación completados. Los 39 casos focalizados backend pasan, incluidos 22 contratos anteriores del propietario. El nuevo recorrido Chromium comprueba tres roles, recuperación de errores, escritorio/móvil y huellas de tablas sin escrituras de negocio. CI incorpora este recorrido a los controles existentes; los resultados completos se registran en work/entrega108.

No hay migración ni reetiquetado de moneda. Se conservan la base manual y sus documentos. No se fusiona main ni se despliega producción.

Para probar, respaldar la instalación y conservar cambios propios; reconstruir backend y frontend con docker compose up -d --build --no-deps backend frontend. Recargar con Ctrl+F5 y abrir /manager/fleet/riders/{id} como Gerente o Superadmin. Comparar libro, reservas y disponible con los movimientos del repartidor. Como Operador, verificar el perfil operativo sin acceso financiero. No borrar ni resembrar volúmenes.

El siguiente bloque revisa tarifas de zonas y consumidores monetarios restantes. BCV automático, conciliación bancaria, staging y aceptación siguen pendientes en PRODUCCION_PENDIENTES.md.

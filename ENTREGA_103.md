# Delivery360 — entrega 103

El historial de retiros del repartidor y la administración del gerente consultan
importes decimales exactos, conservando la moneda registrada y los saldos ausentes.
El detalle obtiene la solicitud y todos sus eventos en una sola sentencia SQL:
una aprobación concurrente no produce una solicitud y un historial de cortes
diferentes. Un historial mayor de 1000 eventos devuelve un conflicto explícito,
sin publicar una lista incompleta como si fuera completa.

## Comportamiento y compatibilidad

- `/payouts/exact/page` conserva el cursor HMAC, su ámbito por actor, rol, rider,
  estado y límite, y su posición por fecha/ID. Un cursor no congela el historial.
- `/payouts/exact/{id}` aplica los mismos permisos. Repartidores consultan solo
  sus registros; los gerentes y superadministradores usan la vista administrativa.
  El parámetro `audience` bloquea una vista cuyo rol cambió durante la sesión.
- Las monedas desconocidas o inválidas no se convierten en USD. Los importes
  inválidos y destinos bancarios defectuosos se marcan para revisión; una fila
  defectuosa no oculta las demás. No se expone un número bancario sin enmascarar.
- El subtotal COMPLETADO usa centavos BigInt y solo solicitudes de la página con
  USD e importe válido. Indica exclusiones; no acredita pagos bancarios ni saldo
  disponible. Las órdenes y períodos ausentes permanecen sin informar.
- El CSV exporta únicamente las coincidencias de la página confirmada, con texto
  decimal, revisión, moneda original, corte, huella, actor, filtros y cursor.
  Una carga pendiente o fallida bloquea CSV e impresión.
- Los contratos numéricos de solicitud, aprobación, rechazo y recuperación por
  clave permanecen compatibles. Una confirmación se comprueba contra los centavos
  exactos del retiro, sin reemplazar el modelo de lectura. Si falla la lectura
  posterior, se conserva el corte anterior y se identifica la confirmación aparte;
  otra decisión requiere una nueva consulta válida y una acción deliberada.

Las tres pantallas conservan su estructura y controles con cabeceras de color,
tarjetas, avisos claros y presentación adaptable. No hay migración nueva,
reescritura de registros históricos, integración bancaria ni cambio de BCV.

## Validación y pruebas locales

3322 pruebas frontend en 149 suites. 34 casos PostgreSQL específicos de lectura
exacta y 96 contratos históricos de bootstrap. TypeScript, Black, flake8 crítico,
mypy de 215 fuentes y build de producción forman parte de la verificación.
El recorrido Chromium local pasó 15 comprobaciones con sesiones reales de
Superadmin, Gerente y Repartidor, y se incorpora a la CI: CSV decimal, propiedad, detalle de una sola petición, rechazo de
historial incompleto, recuperación explícita y vista móvil, sin escrituras.
Los resultados finales y la publicación se conservan fuera del código en
`work/entrega103` junto con respaldos privados y archivos de recuperación.

Para probar con Docker Compose, usar esta rama o incorporar su PR conservando los
cambios propios y reconstruir los servicios de aplicación:

```sh
docker compose up -d --build --no-deps backend frontend
```

Recargar con Ctrl+F5 y visitar `/manager/financial/payouts`, abrir un detalle y
probar filtros/CSV; como repartidor, `/rider/earnings/payouts`. Las lecturas nuevas
no necesitan volver a sembrar la base. No ejecutar decisiones sobre registros
reales para probar: usar datos de laboratorio según `PRUEBAS_LOCALES.md`.

Siguiente bloque: tablas de movimientos, órdenes y entregas del detalle de auditoría
del repartidor, y después los consumidores monetarios restantes. Los accesos
bancarios, automatización fiable de BCV, aceptación en staging y operación de
producción siguen pendientes en `PRODUCCION_PENDIENTES.md`.

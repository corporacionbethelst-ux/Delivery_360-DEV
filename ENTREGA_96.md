# Entrega 96 — libro exacto de cobros y devoluciones

La pantalla `/manager/financial/customer-cashbook` reúne cobros y devoluciones
verificados manualmente. Conserva USD contable y los importes originales USD/VES,
con BCV del cobro original. Ofrece filtros, neto del período, desglose diario y por
medio, trazabilidad de responsables y CSV completo del mismo conjunto consultado.
SUPERADMIN, GERENTE y AUDITOR pueden consultar; no hay acciones de escritura.

## Continuidad de ramas

La comparación con GitHub detectó que el PR 337 de devoluciones se había fusionado
en `feat/customer-collection-review-v1`, no en `main`. La entrega 96 parte de
`main` `6f64d6e6dbee09cd8024db9ded976def47f079c0` e incorpora esa integración
mediante el merge local `5ebc775de75e6d0abc07afd4e6d4e921514877e1`.
El PR dirigido a main incluye tanto las devoluciones de la entrega 95 como este
reporte. No cambia main ni fusiona el PR. Se conservó respaldo de los cambios en
curso antes de integrar las ramas y se reaplicaron sin perderlos.

## Criterios comprobados

- Una sola sentencia PostgreSQL da visibilidad consistente a filas y totales;
  una verificación concurrente se reconoce en la consulta siguiente.
- Se excluyen cobros pendientes y devoluciones sin verificación de salida.
  Un período puede tener neto negativo si devuelve cobros de otra fecha.
- Los cálculos usan Decimal/BigInt y cadenas monetarias. La tasa de hoy no
  modifica cobros ni devoluciones anteriores; el redondeo parcial es acumulado.
- Fechas inclusivas de Caracas, rango de hasta 31 días y 5.000 movimientos.
  Superar el límite devuelve 409; nunca se exporta un detalle truncado.
- El navegador valida fuentes, fechas, filtros, importes y todos los agregados.
  Cambiar filtros o sesión invalida resultados privados anteriores.
- El CSV contiene todas las filas, fechas, conteo y huella SHA256 del contenido.
  La huella identifica el snapshot y no acredita confirmación bancaria.
- La migración `20261115_cashbook_indexes` añade solo índices. El laboratorio
  preservó los hashes de todas las tablas anteriores, incluidas devoluciones.
- Chromium real comprobó carga, exportaciones USD/VES, filtros, vacío, errores,
  escritorio y móvil: ocho comprobaciones, cero errores JavaScript y escrituras.
  Las pruebas de contrato/pantalla frontend del bloque son 39.

La validación completa, CI del commit final y recuperación de fuente se registran
en los artefactos de entrega. Las pruebas nuevas también se ejecutan en CI junto
con los recorridos reales anteriores. No se ejecutan migraciones en producción.

## Bancos y próximos pendientes

Bancos indicados: Banco de Venezuela, Banesco, Provincial, Mercantil y BOD.
Se requieren canales oficiales, acceso técnico y homologación; se comprobará
la entidad operativa actual de BOD. No se infiere un banco desde los alias
históricos de cajas/cuentas. La conciliación automática sigue pendiente.

El libro de clientes no representa utilidad, saldo bancario ni ganancias de
riders. Aún faltan el cierre decimal de reportes heredados, revisión explícita
de monedas históricas, liquidaciones VES de riders con tasa conservada, BCV
automático fiable y los demás puntos de `PRODUCCION_PENDIENTES.md`.

Para probar localmente, inicia el laboratorio con `python scripts/local_test.py up`,
ejecuta los recorridos de cobros/devoluciones y luego:

```bash
python frontend/e2e/local-customer-cashbook.browser.py \
  --wait-request-window --artifacts-dir browser-real/customer-cashbook
```

El ejecutor exige el marcador de la base dedicada, no borra registros y compara
los hashes de los libros monetarios antes y después de consultar/exportar.

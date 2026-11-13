# Simulación histórica de bono uniforme

`POST /api/v1/settings/simulate-bonus` compara los bonos congelados de una muestra
histórica con un **escenario de importe uniforme por entrega completada**.
Está disponible para SUPERADMIN y GERENTE. No cambia configuración, entregas,
bonos congelados, saldos, asientos ni pagos; tampoco inicializa claves ausentes.

## Qué compara

Para la misma muestra histórica:

```
histórico = suma de bonos SUCCESS + suma de bonos FAILED_ATTEMPT
escenario = entregas completadas × bono uniforme redondeado + bonos FAILED_ATTEMPT registrados
diferencia = escenario − histórico
variación = diferencia / histórico × 100, si el histórico es mayor que cero
```

La fórmula anterior restaba el bono base actual a la propuesta y multiplicaba la
diferencia por el número de entregas. Si los bonos históricos eran menores que
el bono base actual, una reducción podía generar un costo negativo. Por ejemplo,
tres bonos de 1 y un intento fallido de 2 suman 5. Con base actual 10 y propuesta
0, la fórmula anterior daba −25. El escenario uniforme conserva los 2 registrados
por el intento fallido y da una diferencia de −3.

Los bonos históricos pueden incluir multiplicadores de zona y nivel, además de
bases anteriores. No se conserva toda la información necesaria para reconstruir
esa fórmula histórica por entrega. Este escenario **no aplica multiplicadores**
ni pretende medir exactamente el cambio de la fórmula real al editar la base.
La interfaz muestra esta hipótesis y no presenta una previsión de actividad
futura, un costo mensual garantizado ni una confirmación de pagos.

## Ventana y cobertura

`days_projection` conserva su nombre HTTP heredado, pero representa entre 1 y 90
días transcurridos de histórico. El servidor captura el instante final UTC y usa
el intervalo `[period_start, period_end)`: incluye el inicio, excluye el instante
final y las fechas futuras. La interfaz convierte sus extremos a America/Caracas.
Son días de 24 horas transcurridas, no días de calendario completos.

La fecha de ubicación es `completed_at` o, si falta, `bonus_snapshot_date`. Esto
permite incluir los intentos fallidos que congelaron su bono sin guardar una
fecha de cierre. Si faltan ambas, la entrega no puede asignarse a la ventana:
`undated_bonus_deliveries` informa el número de esos registros en el histórico
global, aparte de las cantidades del período. No se inventa una fecha usando
`created_at`, `updated_at` o la fecha de consulta.

Se incluyen COMPLETADA/SUCCESS y FALLIDA/FAILED_ATTEMPT. Se excluyen entregas no
terminales, canceladas e intentos fallidos sin bono. Un snapshot incompleto,
negativo, no finito o incompatible con el estado dentro de la ventana produce
409 y no se convierte en cero. Una muestra vacía válida devuelve cantidades y
totales cero, con variación porcentual null y un aviso explícito en la interfaz.

Una única sentencia agregada calcula todas las cantidades, sumas y controles de
integridad de la muestra bajo la misma lectura PostgreSQL. No se combinan dos
consultas históricas de instantes distintos. La moneda no está en estos registros
de bono: `currency` es null y se muestra como no informada. No se asume USD o COP
ni se realizan conversiones. La identificación de la moneda y las pruebas de
carga del agregado permanecen pendientes para producción.

## Contrato y revisión

Entrada: `new_base_bonus` es la propuesta uniforme; se admite cero y un máximo de
99 999 999,99, acorde con el campo Numeric(10,2). Se conserva la precisión de la
propuesta en la respuesta. `applied_bonus` informa el importe realmente usado,
redondeado a dos decimales **por entrega** mediante Decimal y ROUND_HALF_UP, igual
que la persistencia monetaria existente. Por ejemplo, 2,675 se aplica como 2,68;
para tres entregas, el componente del escenario es 8,04.

`expected_settings_revision` vincula la petición con la lectura de configuración.
Si cambió entre la lectura del frontend y el inicio del cálculo, responde 412.
El servidor devuelve la revisión capturada, el bono guardado y la propuesta.
Si la configuración cambia después de capturarla, el resultado sigue identificado
con esa revisión; no afirma que continúe vigente al terminar la consulta.

El cliente exige que la respuesta corresponda a sus parámetros, período y revisión,
y valida las cantidades, totales, identidades de cálculo, modelo y porcentaje.
Conserva el último resultado con sus parámetros reales ante un error y retira
respuestas de sesiones anteriores. Los duplicados e inputs pendientes se bloquean.

Para compatibilidad, la API acepta peticiones anteriores sin revisión y mantiene
sus valores iniciales de 30 días y propuesta igual al bono guardado. No inventa
un bono cero si falta configuración: devuelve 409. El frontend actualizado envía
siempre propuesta, ventana y revisión. Campos desconocidos, días no enteros y
propuestas no finitas o fuera de rango son rechazados con 422.

La respuesta conserva `current_monthly_cost`, `projected_monthly_cost` y
`percentage_increase` como alias heredados del período observado; no representan
meses. Los consumidores nuevos utilizan `historical_cost`, `scenario_cost` y
`percentage_change` (null cuando no hay denominador). El alias porcentual heredado
sigue devolviendo cero en ese caso únicamente por compatibilidad. Se identifica
el modelo como `flat_bonus_same_deliveries`.

**Revisar consumidores existentes:** la fórmula se corrige y cambia la
interpretación del escenario. Los clientes deben mostrar la hipótesis uniforme;
el frontend nuevo requiere estos metadatos de la API nueva. Coordinar ambos al
desplegar. No se ejecutaron despliegues ni migraciones en esta entrega.

## Verificación

`tests/test_bonus_simulation.py` cubre el contrato HTTP, roles, revisiones,
ventanas, fechas faltantes, redondeo, datos inválidos, compatibilidad y ausencia de
escrituras. `tests/test_bonus_simulation_postgresql.py` verifica sumas Numeric,
límites temporales, NaN y consulta única con PostgreSQL real en un esquema privado
de una base `test_*` seleccionada explícitamente. No se utiliza una base de datos
de la aplicación como sustituto de TEST_DATABASE_URL.

Los controles históricos de OpenAPI aplican únicamente el delta revisado de los
dos schemas de simulación y la descripción del endpoint; el resto de rutas,
permisos y esquemas permanece fijado por los snapshots previos. La evidencia y
los límites completos están registrados en la entrega 87.

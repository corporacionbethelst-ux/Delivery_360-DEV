# Entrega 87 — Simulación histórica trazable de bonos

Base main `a007518b1bcaf0f203f4fee5f9f24fe7881847c8`, árbol
`350a64acb2d6f0192eb8adc7d2a74685293ba595`. La entrega 86 fue integrada por el
propietario mediante PR #328; su CI completo terminó aprobado. La rama de esta
entrega es `fix/bonus-simulation-historical-basis-v1`.

## Cálculo y trazabilidad

El simulador adopta un modelo explícito de bono uniforme sobre las mismas
entregas históricas. El escenario multiplica las entregas completadas por el
bono uniforme redondeado y conserva los bonos registrados por intentos fallidos.
Se retira la fórmula que podía generar costos negativos al restar una base
actual superior a los bonos realmente observados.

La interfaz distingue el escenario de una previsión de actividad futura o una
confirmación de pagos. Los multiplicadores de zona y nivel no se reconstruyen:
se informa expresamente que no forman parte de este escenario. La moneda del
registro sigue sin identificar; no se introduce una divisa asumida.

El servidor devuelve extremos UTC del período, días transcurridos, cantidades,
sumas por tipo, propuesta, importe aplicado, base y revisión de configuración.
La muestra tiene inicio incluido y fin excluido, y no incluye fechas futuras.
Se usa la fecha del bono congelado cuando falta completed_at. Los registros sin
ambas fechas se cuentan aparte con alcance global, sin asignarlos al período.

Las métricas provienen de una única consulta agregada. Decimal y ROUND_HALF_UP
aplican el redondeo por entrega, sin alterar los snapshots. Un histórico inválido
produce 409; una revisión cambiada, 412. No se sustituyen datos desconocidos por
ceros. Una muestra vacía se identifica y no genera un porcentaje útil ficticio.
Simular tampoco inicializa registros de configuración ausentes.

## Presentación y recuperación

Se conservan las secciones serias y coloridas: muestra y período azules,
escenario violeta, avisos ámbar y diferencia identificada por etiqueta. Las seis
tarjetas y la fórmula visible se adaptan a móvil. La ayuda del importe se asocia
mediante aria-describedby sin cambiar el nombre accesible del campo.

El frontend envía la revisión fresca y rechaza respuestas de otra propuesta,
ventana, revisión o modelo. Verifica cantidades, sumas, escenario y porcentaje.
Un recálculo fallido mantiene el resultado anterior con sus parámetros reales.
Se mantienen el bloqueo de duplicados y la retirada de sesiones anteriores.
Las confirmaciones de guardado de configuración de la entrega 86 se conservan.

## Validación

- 45 pruebas backend nuevas aprobadas, incluidas tres de PostgreSQL nativo.
- Suite backend completa con PostgreSQL/PostGIS y Redis temporales: 2671 aprobadas, 2 omitidas; 738,87 s. Los SDK opcionales Firebase y Twilio no están instalados; las pruebas PostgreSQL nuevas se ejecutaron sin omisiones.
- 28 pruebas frontend nuevas; suite completa de 2818 pruebas / 124 suites aprobadas.
- Cobertura frontend: 65,21 % sentencias; 61,67 % ramas; 62,43 % funciones; 64,93 % líneas. Mínimos intactos.
- TypeScript y build de 48 páginas aprobados, con las 16 advertencias preexistentes.
- Configuración en Chromium: 18 comprobaciones; cero escrituras reales y excepciones JavaScript. PATCH y cálculo son sintéticos.
- Navegador completo exigido por CI: 155 comprobaciones / 13 smokes aprobados, sin escrituras reales ni excepciones JavaScript.
- Flake8, Black y mypy aprobados; mypy revisa 196 archivos.

Los logs y la verificación por SHA se conservan en
`/workspace/work/entrega87/verification.json` y en el PR. El navegador verifica
la compilación de producción local con API sintética; no certifica E2E de staging.

## Compatibilidad y alcance

El endpoint y sus alias de costo heredados se conservan. Su fórmula cambia y su
modelo queda identificado como `flat_bonus_same_deliveries`; los consumidores
deben mostrar sus hipótesis. Los nombres monthly heredados no significan un mes.
El frontend nuevo requiere los metadatos de la API nueva: coordinar ambos al
desplegar. El contrato está en
[backend/BONUS_SIMULATION.md](../backend/BONUS_SIMULATION.md).

No hay dependencias, migraciones, cambios a la fórmula de liquidación real,
snapshots históricos ni formulario original de órdenes. Continúan pendientes
moneda operativa explícita, staging, infraestructura, carga, restauración,
proveedores y protección de main. Se conservan evidencia, capturas, ZIP sin
archivos de entorno, patch, bundle y hashes. Publicación por rama y PR autorizada;
sin merge, deploy ni operaciones productivas del agente.

# Referencia local de latencia — lecturas concurrentes

Este ensayo usa exclusivamente el laboratorio marcado de `compose.testing.yml`.
No admite URL, contraseña, token ni rutas arbitrarias como argumentos. No levanta,
detiene, vacía ni reinicia servicios; requiere el laboratorio ya iniciado mediante
`scripts/local_test.py`. No lo ejecutes mientras otras pruebas o usuarios cambian
los datos de ese laboratorio.

Desde la raíz del repositorio:

```bash
python scripts/local_read_benchmark.py --wait-request-window --output .delivery360-testing/read-baseline-129.json
```

Conserva el informe existente: para otra ejecución elige otro nombre. El archivo
se crea con permisos privados y nunca incluye respuestas, contraseñas, tokens,
correos o textos de excepción. Se usa la cuenta SUPERADMIN del laboratorio desde
su archivo privado existente; no se piden ni se guardan credenciales nuevas.

## Alcance y límites

Antes de cualquier HTTP comprueba el proyecto y servicio del contenedor API,
su ejecución, la publicación exclusiva `127.0.0.1:puerto → 8000` y el marcador
de la base. Registra el identificador de imagen. Omite proxies y rechaza todas
las redirecciones, incluso hacia el mismo host.

Tras comprobar salud, login e identidad, ejecuta dos etapas: un lector y cuatro
lectores como máximo. Por defecto son 12 solicitudes por etapa, repartidas entre
órdenes (página de 20), zonas y configuración monetaria exacta. Solo mide GET.
El login inicial modifica metadatos de autenticación y queda fuera de las
latencias. Los registros de acceso/auditoría pueden crecer normalmente.

`--samples` admite 3..24 solicitudes por etapa, múltiplo de 3; `--workers` admite
2..4 lectores para la segunda etapa. Cada solicitud tiene timeout de 5 segundos
y límite de respuesta de 2 MiB. No hay reintentos, cambios del rate limiter,
vaciado de Redis ni generadores de escrituras. Un 429 queda como fallo explícito.
`--wait-request-window` espera 61 segundos antes del login para respetar el
presupuesto utilizado por los recorridos anteriores. Evita otras consultas
simultáneas: no garantiza disponibilidad si otra sesión consume el mismo límite.

El informe separa solicitudes exitosas/fallidas, estados, latencia por muestra y
percentiles p50/p95/p99 de éxitos mediante rango más próximo. El throughput usa
el tiempo real de toda la etapa, incluida la coordinación del pool; por endpoint
representa su contribución durante esa misma etapa. No excluye fallos del total
de solicitudes completadas. Los hashes de las tablas operativas/monetarias
protegidas se comparan antes y después; el informe enumera las tablas cubiertas.
Conserva sus recuentos y huellas, sin filas ni valores originales, junto con la
fecha UTC de la medición.
Un cambio en ellas o cualquier fallo HTTP/transporte/formato hace fallar el ensayo.
Se conserva el informe de las etapas aunque falle esa aceptación final.

## Interpretación

Es una referencia breve de lectura, con pocas muestras, cachés sin normalizar y
la etapa secuencial primero. p95/p99 con muestras pequeñas pueden coincidir con
el máximo. No aplica objetivos arbitrarios de latencia ni calcula un número de
usuarios soportados. Tampoco mide frontend, escrituras, workers, proveedores,
duración prolongada, aislamiento entre clientes o carga de producción.

CI lo ejecuta después del recorrido funcional y antes del respaldo/restauración,
con un límite de cinco minutos. El informe se conserva en el artefacto
`local-functional-browser-checks`, ruta `performance/read-baseline.json`.
Antes de afirmar capacidad productiva hay que acordar concurrencia, volumen,
mezcla de operaciones, duración, infraestructura y objetivos de latencia/errores,
y repetir con datos representativos en un entorno autorizado.

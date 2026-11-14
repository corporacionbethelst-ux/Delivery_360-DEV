# Cómo probar Delivery360 localmente

El laboratorio iniciado en la entrega 88 utiliza la API y la interfaz reales, PostgreSQL
con PostGIS y Redis propios. No utiliza las respuestas sintéticas de los smokes
visuales anteriores. Los datos de este laboratorio son de prueba.

## Preparación

Necesitas Git, Python 3.11 o superior y Docker con Compose v2. En Windows, inicia
Docker Desktop con contenedores Linux. No necesitas instalar Node o PostgreSQL
en tu equipo para esta opción. Reserva espacio para imágenes y compilación;
se recomiendan al menos 10 GB libres en el disco de Docker.

Utiliza la rama de esta entrega mientras el PR no esté integrado a main:

```bash
git fetch origin
git switch feat/explicit-usd-ledger-v1
```

Si solo existe la rama remota, utiliza
`git switch --track origin/feat/explicit-usd-ledger-v1`.
Conserva tus cambios locales antes de cambiar de rama. Después de integrar el
PR, puedes usar main actualizado con `git pull --ff-only`.

Desde la raíz del repositorio:

```bash
python scripts/local_test.py init
python scripts/local_test.py up
```

La primera ejecución compila las imágenes, crea una base independiente, aplica
la cadena real de Alembic, prepara cuentas de prueba y espera las comprobaciones
de salud. **Puedes comenzar cuando el comando termine correctamente y confirme
la interfaz, API, PostgreSQL, Redis y acceso SUPERADMIN.**

El inicializador termina y se retira antes de levantar la API. Al volver a ejecutar
`up`, los contenedores web/API de esta instancia se recrean después de las
migraciones; los volúmenes de datos permanecen intactos.

En Windows puedes sustituir `python` por `py -3` si tu instalación lo requiere.
Si necesitas otros puertos, elige antes de la primera inicialización:
`python scripts/local_test.py init --web-port 3090 --api-port 8090`.

## Acceso

Valores iniciales de puertos:

- Aplicación: <http://localhost:3088/login>.
- Documentación de API: <http://localhost:8088/docs>.
- Verificación de salud: <http://localhost:8088/health/ready>.

Para consultar las credenciales generadas únicamente para tu laboratorio:

```bash
python scripts/local_test.py credentials
```

Los usuarios son `admin.local-test@example.com`, `gerente.local-test@example.com`,
`operador.local-test@example.com`, `repartidor.local-test@example.com`,
`auditor.local-test@example.com` y `cliente.local-test@example.com`. La contraseña
aleatoria está en `.delivery360-testing/credentials.json`, junto con cada cuenta.
No hay una contraseña universal publicada en el repositorio. La carpeta está
excluida de Git. Conservarla permite recuperar la instancia y sus accesos.

Superadministración, gerencia, operador y repartidor son los recorridos iniciales
de la interfaz. Auditor y cliente también permiten comprobar autenticación y
permisos de API; su presencia no garantiza una interfaz completa para esos roles.

La comprobación de arranque realiza un solo login para conservar intentos para
tus pruebas. El límite normal de cinco intentos por minuto sigue activo; si lo
alcanzas al cambiar rápidamente de cuenta, espera el tiempo indicado por la API.

## Primer recorrido recomendado

1. Entra como superadministrador. Revisa usuarios, roles, auditoría y configuración.
2. Revisa la zona de prueba, el perfil del repartidor y las tres órdenes pendientes.
   El repartidor comienza desconectado para evitar asignaciones inesperadas.
3. Crea una orden nueva y comprueba que sigue visible al recargar. Puedes cancelar
   una orden de prueba pendiente y verificar su estado y motivo.
4. En configuración, modifica un campo, revisa la confirmación y cancélala. Luego
   guarda un cambio pequeño y verifica que persiste. Solo SUPERADMIN guarda.
5. Abre configuración en dos pestañas y prueba un conflicto de edición. Una lectura
   anterior no debe sobrescribir silenciosamente un cambio confirmado.
6. Prueba el simulador con bono cero y con otro importe. Al principio no hay entregas
   cerradas de prueba: una muestra vacía y «Sin base porcentual» son resultados
   esperados. El simulador no cambia bonos ni genera pagos.
7. Entra como gerente y comprueba consulta y simulación sin guardado administrativo.
   Revisa también el acceso del operador y el perfil propio del repartidor.

Los valores iniciales de tarifas y bonos son fixtures explícitos del laboratorio,
no recomendaciones comerciales. No hay saldos ni pagos de ejemplo fabricados.
Para probar asignación y cierre, completa los requisitos reales de disponibilidad,
perfil y permisos; no se omiten los controles del sistema.

## Volver a comprobar, detener y reiniciar

```bash
python scripts/local_test.py check
python scripts/local_test.py status
python scripts/local_test.py down
python scripts/local_test.py up --no-build
```

`down` conserva los volúmenes de PostgreSQL y archivos subidos. Reiniciar conserva
cuentas, contraseñas, borradores guardados y cambios de datos; el seed no restaura
valores iniciales ni sobrescribe ediciones. Redis es caché temporal.
Si cambias una contraseña durante las pruebas, actualiza tus accesos; el seed no
la revierte. Para recompilar cambios de código utiliza `up` sin `--no-build`.

Si el arranque falla, no se declara que el laboratorio esté listo. Comprueba que
Docker esté iniciado, los puertos libres y el disco de Docker tenga espacio. Los
mensajes de `status` indican qué servicio requiere atención. No borres volúmenes
ni la carpeta de credenciales como primer paso: contienen tus pruebas y accesos.

En redes corporativas que requieren una CA propia para compilar, existe
`up --build-ca /ruta/al/certificado.pem`. Se mantiene la verificación TLS y el
certificado se monta solo durante la compilación.

## Alcance

### Recorrido automático del ciclo operativo

Con el laboratorio iniciado, Playwright y Chromium disponibles:

```bash
python frontend/e2e/local-lifecycle.browser.py --artifacts-dir /tmp/delivery360-lifecycle
```

El ejecutor admite `--chromium /ruta/al/navegador`. Comprueba el marcador de la
base y su identidad de API; requiere los bonos iniciales del laboratorio (2,50
por entrega y 1 por fallo bonificable) y se detiene si se personalizaron. No los
sobrescribe. Crea su propio repartidor, documentos sintéticos y siete órdenes.
Registra una reserva rechazada y otra aprobada contablemente, sin pagos bancarios.
Los datos quedan identificados en `progress.json` y `results.json` de los
artefactos. Son datos de prueba conservados para revisión, sin validez documental.

### Referencias BCV y cotizaciones de la entrega 90

Abre **USD / Bolívares** como superadministrador o gerente. En el laboratorio,
usa una referencia claramente identificada como sintética: revisa y cancela una
vez; después confírmala, guarda un importe pequeño y recarga su enlace. Corrige
la tasa y comprueba que el comprobante anterior conserva el equivalente original.
El operador cotiza, pero no puede registrar referencias ni recuperar las ajenas.

```bash
python frontend/e2e/local-currency.browser.py --artifacts-dir /tmp/delivery360-currency
```

El ejecutor comprueba identidad y marcador antes de escribir, conserva sus datos
sintéticos y verifica que órdenes, contabilidad y configuración no cambien.
Si acabas de ejecutar otros recorridos con varios usuarios, añade
`--wait-auth-window` para respetar el límite de inicio de sesión.

La tasa se registra manualmente tras verificar BCV; no existe consulta automática
habilitada. Es una herramienta de cotización independiente, sin pagos bancarios
ni migración de saldos históricos. El [contrato de moneda](MONEDA_VENEZUELA.md)
describe vigencia, precisión, permisos, comprobantes y pendientes.

### Libro USD de la entrega 91

Si actualizas un laboratorio anterior, los importes sin moneda verificable se
conservan como historial y no se convierten automáticamente a USD. El saldo USD
puede comenzar en cero aunque existan movimientos anteriores. La pantalla indica
cuántos movimientos y retiros requieren revisión; las páginas de transacciones y
pagos conservan su consulta. Las nuevas operaciones de esta versión declaran USD.

El recorrido automático del ciclo operativo comprueba también esa separación:
tras ganar 11 USD y registrar un retiro contable de 10 USD, añade dos fixtures
claramente sintéticas sin moneda. Comprueba que queda 1 USD, que no se pueden usar
los fondos desconocidos para retirar y que la UI impide aprobar ese retiro antiguo.
Las fixtures quedan identificadas en `results.json`; sus inserciones SQL ocurren
solo tras comprobar el marcador y la identidad del laboratorio. No son conversiones.

Las órdenes sin moneda no permiten modificar sus importes como si fueran USD.
Las nuevas órdenes mantienen el formulario colorido y los precios indicados en USD.
Los reportes suman operaciones con unidad identificada; las cotizaciones BCV siguen
sin confirmar pagos. La migración se niega a revertirse si perdería evidencia de
moneda nueva. Conservar un saldo anterior requiere revisión, no cambiar etiquetas.

### Límites del laboratorio

Este entorno escucha únicamente en la máquina local. No reutiliza el Compose
anterior, bases existentes, archivos `.env` del backend ni credenciales reales.
El inicializador comprueba entorno, host, nombre de base, conexión de migración
e identificador antes de escribir. Rechaza destinos ajenos al laboratorio.

Correo, notificaciones externas, emisión fiscal y tareas automáticas de tracking
están deshabilitados. No certifica proveedores reales, pagos bancarios, rendimiento,
restauración, staging o producción. Esas pruebas requieren una etapa posterior.

La revisión `20261113_runtime_schema` completa las tablas mapped de productividad,
SLA y eventos webhook, y añade AUDITOR al enum PostgreSQL. El laboratorio la aplica
solo a su propia base. En instalaciones existentes debe revisarse y aplicarse por
el procedimiento de migraciones correspondiente; esta entrega no migra producción.
El downgrade se niega si esas tablas contienen historial y conserva AUDITOR.

La suite automática debe usar otra base PostgreSQL `test_*` vacía y sus esquemas
privados. No ejecutes la suite completa contra los datos del laboratorio manual.

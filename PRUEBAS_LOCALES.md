# Cómo probar Delivery360 localmente

El laboratorio de la entrega 88 utiliza la API y la interfaz reales, PostgreSQL
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
git switch feat/local-functional-test-environment-v1
```

Si solo existe la rama remota, utiliza
`git switch --track origin/feat/local-functional-test-environment-v1`.
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

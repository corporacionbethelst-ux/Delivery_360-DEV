# JWT, parser y límites HTTP — entrega 73

Este documento describe el backend actualizado. La entrega 72 conserva la
evidencia histórica de los avisos que motivaron el trabajo.

## Dependencias y compatibilidad

Se sustituye python-jose 3.3.0 por **PyJWT 2.15.1** y se actualiza multipart a
**0.0.33**. El inventario de paquetes realmente instalados reveló otros tres
avisos altos en Starlette 0.37.2: CVE-2024-47874, CVE-2026-48818 y CVE-2026-54283.
Se actualizan **FastAPI 0.162.2, Starlette 1.10.0 y Pydantic 2.9.2**, sin forzar
dependencias ni ignorar hallazgos. Cryptography 50.0.2 queda declarado directamente
para las firmas fiscales/TLS; ya no depende accidentalmente del extra de jose.

Los dos inventarios escaneados con Trivy 0.76.2 —requirements declarados y freeze
del entorno limpio instalado— terminan con **cero hallazgos HIGH/CRITICAL**.
Ese resultado no acredita ausencia de avisos moderados/bajos, vulnerabilidades
del sistema operativo de las imágenes o integraciones homologadas.

El informe SARIF remoto reveló además tres avisos moderados: CVE-2026-53533 y
CVE-2026-55558 de aiosmtplib, y CVE-2026-77387 de geopy. Se corrigen con
**aiosmtplib 5.1.3 y geopy 2.5.0**, manteniendo TLS/certificados activos y verificando
SMTP/recuperación/notificaciones con servidores locales. El escaneo final del
requirements runtime ya no tiene hallazgos en ninguna severidad. El freeze del
entorno dev conserva un moderado en pytest 8.3.2 (CVE-2025-71176, corrección indicada
9.0.3); pytest está fuera de la imagen de producción y su migración queda pendiente.

Pytest, Faker, herramientas de carga y perfiladores pasan a requirements-dev.txt.
Producción instala solamente requirements.txt. CI comprueba consistencia con
`pip check`, registra las versiones resueltas y escanea dependencias transitivas.

## Contrato de autenticación

- Se firma y verifica exclusivamente con el algoritmo HMAC configurado:
  HS256, HS384 o HS512. Un header JWT no elige el algoritmo del verificador.
- Se exigen sub, exp, iat, jti y type. IDs no vacíos, fechas enteras válidas,
  expiración vigente y tipo access/refresh. Se rechazan fechas coercibles,
  booleanos, valores no finitos y tokens mayores de 8192 caracteres.
- Los JWT propios anteriores, con esos claims y firma vigente, siguen siendo
  compatibles. La prueba de formato legacy usa firma independiente HMAC/JSON,
  sin depender del nuevo encoder. No se aceptan tokens incompletos por mantener
  compatibilidad con emisores ajenos.
- El epoch ver conserva su comprobación estricta; su ausencia corresponde solo
  al epoch cero. Login, refresh, revocación, cuenta activa y rol siguen consultando
  la política vigente mediante las dependencias canónicas existentes.
- Los adaptadores de middleware de compatibilidad ahora rechazan bearer inválido
  con 401 en vez de devolver None desde una dependencia obligatoria. Un refresh
  no sirve como access. Las rutas reales conservan su autorización en DB.
- Producción requiere un SECRET_KEY no predeterminado y sin espacios extremos,
  con al menos 32/48/64 caracteres para HS256/384/512. La longitud no demuestra
  aleatoriedad: el operador debe generar y custodiar el secreto adecuadamente.
  Duraciones deben ser positivas. Los errores de configuración ocultan inputs.

No se rota el secreto ni se alteran credenciales o datos existentes. Antes del
despliegue, validar la configuración real; configuraciones inseguras que antes
arrancaban ahora fallan al cargar settings.

## Política de cuerpos HTTP

| Petición | Límite de bytes antes de parsear |
| --- | --- |
| POST/PUT/PATCH/DELETE generales | 1 MiB |
| POST /api/v1/auth/login | 64 KiB |
| Upload de un documento | 11 MiB de petición; 10 MiB por archivo sigue vigente |
| Registro multipart con cuatro documentos | 41 MiB de petición; 10 MiB por archivo sigue vigente |

Se cuenta el cuerpo recibido incluso con transferencia chunked o Content-Length
falso. Framing ambiguo, longitudes duplicadas/malformadas o inconsistentes dan
400; exceso de bytes da 413; recepción que no termina en **30 segundos** da 408.
Ese plazo cubre la recepción, no el procesamiento del handler. Debe comprobarse
con conexiones móviles reales antes de producción.

Un spool privado conserva hasta 1 MiB en memoria y pasa a temporal cuando lo
necesita. Se reproduce exactamente el cuerpo autorizado; uploads no se duplican
en dos spools. Archivo cerrado ante éxito, rechazo, desconexión, cancelación o
error del handler. CORS sigue envolviendo los rechazos. GET, preflight y WebSocket
conservan su manejo actual; esto no limita mensajes individuales WebSocket.

Los límites de aplicación no sustituyen límites/concurrencia/timeouts del ingress
ni pruebas de carga. Tampoco impiden que el servidor ASGI reciba un chunk antes
de contarlo. El almacenamiento temporal debe tener cuota y permisos adecuados.

## Superficie API y cambio del framework

Las **203 rutas, su orden y los grafos de dependencias/permisos permanecen
idénticos** a la entrega 72. FastAPI ahora representa routers incluidos mediante
contextos efectivos; el inventario usa iter_route_contexts para conservar prefijos,
métodos, tipos originales de rutas y scopes heredados.

OpenAPI cambia en 24 campos concretos de schemas: referencias enum simplificadas,
metadatos de archivos/passwords/errores, límites decimales ya validados y patrón
OAuth grant_type anclado a password. No cambian paths u operaciones.
`tests/fixtures/openapi_framework_delta.json` enumera cada diferencia antes/después;
las pruebas revierten exclusivamente ese delta y exigen el hash histórico íntegro.
Los fixtures previos de readiness, payouts y reconciliation permanecen intactos.
Los formularios OAuth válidos y uploads siguen probándose con el parser real.

## Controles de CI adicionales

- `backend-security` instala runtime, comprueba dependencias y escanea su freeze.
- `backend-container` construye el Dockerfile real sin publicar, exige UID 10001,
  ausencia de jose/pytest y raíz de solo lectura, con capacidades retiradas.
  Usa PostGIS/Redis aislados, comprueba readiness, 401 sin credenciales, límites
  antes de handlers y que el arranque no cree la tabla users. Al detener Redis,
  exige readiness 503 y liveness 200. Sus uploads temporales son solo de prueba;
  producción conserva el PVC persistente de la entrega 72.
- `release-readiness` exige ambos jobs además de los seis anteriores. Se ejecuta
  CI en PR a cualquier rama, incluidas revisiones dependientes; la publicación
  continúa limitada a push y los checks aprobados. No hay deploy automático.

El script smoke_backend.py rechaza URLs remotas y solo admite una API local de
prueba. No se invoca contra staging/producción ni ejecuta pagos, mensajes,
facturas o migraciones productivas.

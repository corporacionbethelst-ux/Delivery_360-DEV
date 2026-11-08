# Publicación y despliegue verificable

Esta configuración prepara un despliegue; no acredita que exista un entorno
productivo. No crea credenciales, base de datos, TLS, almacenamiento ni ingress.
Tampoco ejecuta migraciones, pagos, mensajes o facturas.

## Qué cambia

El frontend usa Node 24 y Next 15.5.29 en modo standalone, con servidor de
producción y usuario no root. La API pública se compila como `/api/v1`; el ingress
encamina `/api` al backend y el resto al frontend. El mismo digest puede pasar por
staging y producción sin reconstruir URLs. Los Dockerfile conservan validación
TLS; una CA de proxy puede entregarse opcionalmente como secreto BuildKit
`proxy_ca`, nunca como archivo incluido en la imagen.

El backend usa UID 10001, sin reload ni migraciones automáticas. Su readiness
consulta PostgreSQL y Redis con plazo de dos segundos y devuelve **503** si falla
cualquiera. Liveness no consulta dependencias. Los probes incluyen el Host público
para respetar TrustedHostMiddleware. La política actual exige un subdominio de
`delivery360.com` en producción; usar otro dominio requiere cambiar y validar esa
política, no desactivar la comprobación.

Los dos Deployments tienen raíz de solo lectura, capacidades retiradas,
seccomp RuntimeDefault, recursos limitados y sin token de ServiceAccount.
Los uploads usan un PVC persistente; solamente caché y temporales son efímeros.
Son cinco recursos: dos Deployments, dos Services y un Ingress NGINX con TLS.

## Publicación de imágenes

`CI/CD Pipeline` ejecuta backend, frontend con el umbral de cobertura existente,
auditoría npm de producción, contrato de release, construcción/pruebas de
navegador de la imagen frontend y Trivy con fallo en HIGH/CRITICAL. El job
`release-readiness` exige que todos terminen correctamente. Las imágenes solamente
se publican en eventos push después de ese gate; los PR construyen y prueban el
frontend sin publicar imágenes.

Los tags son `ghcr.io/<repositorio-en-minúsculas>/<componente>:sha-<SHA completo>`.
El artefacto `release-images` registra **ambos digests publicados**, el repositorio,
el SHA completo y `/api/v1`. Los planes consumen referencias `@sha256`, no tags
mutables. Sus ejemplos de CI usan digests sintéticos y no son releases aplicables.
Una auditoría npm limpia no sustituye el escaneo de la imagen final ni el del
backend. La publicación multiarch y los paquetes Python siguen requiriendo su
validación efectiva en CI.

## Preparación del entorno

Un administrador debe preparar y verificar, antes de cualquier apply:

- Namespace `delivery360-staging` o `delivery360` y un contexto Kubernetes
  inequívoco. Configurar `KUBE_CONTEXT` en las variables del environment de GitHub.
- Secret del environment `KUBECONFIG`, codificado en base64, con permisos mínimos
  para esos recursos y namespace. Nunca incluirlo en el repositorio o los logs.
- Secret `delivery360-runtime` con `DATABASE_URL`, `REDIS_URL` y `SECRET_KEY` reales;
  agregar por canal seguro las demás opciones de proveedores necesarias.
- Secret TLS `delivery360-tls`, DNS y controlador ingressClass `nginx` funcionales.
- PVC `delivery360-uploads` en estado Bound y escribible por UID/grupo 10001.
  Producción exige `ReadWriteMany` para las dos réplicas; staging usa una réplica,
  pero su rolling update también puede necesitar almacenamiento compartido o
  ajustar la estrategia al proveedor antes de operar.
- Acceso de los nodos a las imágenes GHCR. Si son privadas, configurar pull
  credentials en el namespace/ServiceAccount; estos manifiestos no crean tokens.
- Backups de DB/uploads, restauración ensayada, esquema compatible con ambas
  versiones durante el rolling update y procedimiento de migración/rollback.
- Protección real de los environments con revisores y restricciones de ramas,
  y protección de main descrita en [rulesets](../../.github/rulesets/README.md).

Los chequeos de preflight verifican presencia de claves, TLS, volumen y contexto;
no prueban calidad de secretos, conectividad de proveedores, permisos de escritura,
recuperación de backups o compatibilidad de migraciones.

## Plan manual

Usar `Manual verified deployment`, proporcionando environment, SHA completo y
hostname. Mantener **`apply: false`**, su valor predeterminado, para generar solo
el artefacto `reviewed-release-plan`. No se contacta el clúster en esta modalidad.

El plan exige la corrida push más reciente del mismo SHA y repositorio en
`.github/workflows/ci-cd.yml`: completada con éxito, en main para producción o
main/develop para staging. Un éxito anterior no oculta un reintento fallido.
Descarga sus digests, valida su identidad y comprueba el schema Kubernetes 1.34.
Revisar imágenes, namespaces, host, recursos y almacenamiento del JSON resultante.

Un apply es una operación separada y explícita: `apply: true`, `migrations_ready:
true` y la confirmación exacta `APPLY delivery360-staging` o `APPLY delivery360`.
`migrations_ready` es una declaración del operador de que preparó backup, esquema
y rollback; **no ejecuta ni demuestra migraciones**. El workflow verifica contexto
y prerrequisitos, hace dry-run contra el servidor, aplica el plan y espera ambos
rollouts. Comprueba login público y rechazo 401 de la API sin autenticación.
Una falla posterior al apply no hace rollback automáticamente: inspeccionar el
estado y aplicar el procedimiento revisado. Nunca retroceder un esquema destructivo
solo mediante `kubectl rollout undo`.

El preflight y dry-run no son transaccionales. Las protecciones de GitHub solo
están activas si un administrador las configura en el servicio.

## Validación local sin clúster

Desde la raíz, con Python 3.11 y dependencias de
`scripts/requirements-release.txt` en un entorno virtual:

```bash
python -m unittest discover -s scripts/tests -v
python scripts/release.py --help
python scripts/validate_manifest.py staging-plan.json production-plan.json
```

Los planes deben generarse previamente con `release.py manifest` y `render`; sus
argumentos exigen SHA completo y dos digests. Usar valores sintéticos únicamente
para pruebas offline. El JSON de `manifests/workloads.json` es una plantilla y
debe renderizarse antes de validar o aplicar.

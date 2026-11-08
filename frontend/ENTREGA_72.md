# Entrega 72 — Seguridad de dependencias y gates de publicación

Fecha de continuidad: 7 de noviembre de 2026, America/Caracas.
Base verificada: `2cd9226162b623495f6a604483bf2e671ce09ef2` (PR #312 fusionado).
Árbol base: `5a549212c40481eaba63ce8a223e0db84b342e57`.
Rama: `fix/security-dependencies-and-release-gates-v1`.

La auditoría posterior a la entrega 71 encontró ocho entradas vulnerables en el
árbol npm de producción, main sin protección, imágenes con tags inconsistentes,
rutas Kubernetes inexistentes y un Dockerfile frontend que ejecutaba desarrollo
con Node 18. Esta entrega aborda esos bloqueos antes de ampliar pantallas.

## Cambios implementados

- Next 14.2.5 pasa a **15.5.29**, con eslint-config-next alineado; Node 24/npm 11,
  axios actualizado, Zod 4/resolver 5 y dependencias transitivas corregidas.
  React 18.3.1 se conserva conforme a los peers admitidos y se prueba en navegador.
  PostCSS se mantiene en la versión 8 corregida mediante override compartido;
  no se usa `--force`, `--legacy-peer-deps` ni se desactiva SSL.
- Formulario de rider y FormField distinguen entrada/salida del schema Zod,
  manteniendo defaults y validación real. Next genera su configuración de tipos
  y target ES2017. Se conserva strictMode y los controles de lint/tipos de build.
- Frontend standalone multietapa, usuario node y servidor de producción; backend
  con UID 10001, sin reload/migraciones automáticas. Dockerignore evita incluir
  entornos, cachés, uploads y dependencias locales.
- Readiness asíncrono con consultas reales de PostgreSQL/Redis, timeout y cierre
  de conexiones: HTTP 503 ante falla, sin detalles sensibles. Liveness independiente.
  Se agrega solamente la respuesta 503 al contrato OpenAPI, preservando fixtures
  históricos y comprobando explícitamente ese delta; rutas y auth no cambian.
- CI agrega auditoría npm de producción, Trivy que falla en HIGH/CRITICAL, contrato
  de release y build/smoke/navegador del contenedor frontend. `release-readiness`
  agrega todos los resultados y bloquea publicación si alguno no aprueba.
- Tags coherentes con SHA completo, registro de los dos digests publicados y
  planes Kubernetes por digest. Cinco recursos por entorno, TLS, permisos
  restringidos, probes y uploads persistentes; validación estricta del schema.
- Se sustituyen deploys automáticos por un workflow exclusivamente manual, con
  `apply: false` inicial. Exige CI push exitoso para el SHA exacto, contexto esperado,
  confirmación del namespace, secretos/TLS/PVC, declaración de preparación de
  migraciones y dry-run. Ruleset main preparado, **sin activarlo remotamente**.

Operación y límites: [guía Kubernetes](../infrastructure/kubernetes/README.md).

## Evidencia local

| Comprobación | Resultado de esta entrega |
| --- | --- |
| `npm audit --omit=dev --json` | **0 vulnerabilidades**, frente a 8 en la base |
| Auditoría completa, incluyendo herramientas dev | 12 avisos: 6 bajos y 6 moderados; 0 altos/críticos |
| Frontend completo | **1700 pruebas / 92 suites aprobadas** |
| Cobertura statements / ramas / funciones / líneas | 43,56 % / 41,69 % / 40,10 % / **41,78 %** |
| Umbral global de cobertura 50 % | Sigue fallando; no se modifica ni excluye código |
| Tipos, lint y build frontend | Aprobados; 22 advertencias lint existentes, 48 páginas, Inter real |
| Formularios específicos | 29 pruebas aprobadas |
| Readiness + bootstrap API | 98 pruebas aprobadas, 12 nuevas de readiness y delta OpenAPI explícito |
| Backend completo | Validación final en curso; se registra al finalizar |
| Black / flake8 crítico / mypy backend | Aprobados, 194 archivos de aplicación |
| Contratos de release | 8 pruebas unittest, con subcasos de identidad, seguridad y prerrequisitos |
| Kubernetes offline | 5 recursos staging + 5 producción, schema 1.34 estricto; digests sintéticos |
| Workflows | actionlint 1.7.12 aprobado |
| Chromium standalone de producción | 3 comprobaciones: formulario Zod 4, sesión/API relativa/CSV real y móvil |
| Regresiones Chromium de catálogo y detalle | 7 + 7 comprobaciones, 14 + 54 lecturas |
| Escrituras HTTP / excepciones pageerror de navegador | **0 / 0**, datos sintéticos y WebSocket interceptado |

El primer backend completo terminó con 2445 aprobadas, 2 omitidas y un error
`DiskFullError` al crear tablas. Liberado el caché Docker generado, las 65 pruebas
de cancelación aprobaron. Se repite el completo con espacio disponible para dejar
evidencia limpia. No se cambia la lógica de negocio por ese incidente.

La construcción Docker frontend local encontró la cuota de disco del driver vfs;
no se atribuye un build Docker completo local exitoso. Sí se construyó y ejecutó
el bundle standalone real y se validó en Chromium. CI tiene un job independiente
que construye el Dockerfile completo y ejecuta las mismas pruebas sobre su imagen;
su resultado remoto se registra por separado. Arrancar el standalone manualmente
requiere copiar public y `.next/static` antes de iniciar server.js; el Dockerfile
incluye ambas copias.

## Estado hacia producción

**Todavía no apto para producción.** La mejora elimina los avisos npm de producción
observados y prepara controles verificables; no representa una certificación de
seguridad del sistema ni un despliegue realizado.

Siguen pendientes cobertura frontend >=50 % en las cuatro métricas; revisión de
los hallazgos de seguridad backend/imágenes que informe el nuevo gate; activación
administrativa de main/environments; infraestructura real, E2E integrado, carga y
restauración ensayada. Los 12 avisos dev requieren seguimiento separado.
La aprobación contable de payout no demuestra liquidación bancaria; el worker
continúa bloqueando settlement no verificado. Faltan homologación sandbox de
pagos y transporte fiscal real. Esta entrega no envía pagos, mensajes ni facturas,
no migra producción, no fusiona PR y no despliega.

La siguiente prioridad es resolver hallazgos reales del CI y ampliar cobertura
con escenarios de negocio útiles; luego retomar los contratos del listado de
entregas de gerencia descritos en la entrega 71.

Publicación y resultados remotos se registran al verificar la rama y el PR.

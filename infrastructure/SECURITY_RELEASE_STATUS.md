# Bloqueos de seguridad observados — entrega 72

**Actualización de entrega 73:** los seis avisos siguientes y tres avisos altos
transitivos de Starlette se corrigen en la rama de continuidad. Los inventarios
declarado e instalado ya escaneados no tienen HIGH/CRITICAL. Véanse el alcance y
las limitaciones en [seguridad backend](../backend/SECURITY_AND_REQUEST_LIMITS.md).
También se corrigen tres moderados SMTP/geopy encontrados en el SARIF remoto.
El requirements runtime termina sin hallazgos de ninguna severidad; queda un
moderado en pytest del entorno dev, fuera del contenedor de producción.
La cobertura frontend y los demás requisitos de producción siguen pendientes.
El inventario que sigue se conserva como evidencia histórica de la base 72.

Continuidad: 7 de noviembre de 2026, America/Caracas. Escaneo ejecutado el
8 de noviembre UTC, con Trivy **0.76.2**, binario oficial cuyo SHA256 se verificó,
base de vulnerabilidades descargada en esa ejecución y severidades HIGH/CRITICAL.
El job remoto `security-scan` también falla en backend y aprueba frontend.

## Resultado frontend

La auditoría npm de producción pasa de ocho entradas vulnerables a **cero**.
La auditoría completa conserva 12 avisos dev: seis bajos y seis moderados.
Eso no certifica el sistema completo, las imágenes base o proveedores.

## Resultado backend: seis hallazgos bloqueantes

| Paquete fijado actualmente | Aviso | Severidad | Versión corregida informada por el escáner |
| --- | --- | --- | --- |
| python-jose 3.3.0 | [CVE-2024-33663](https://avd.aquasec.com/nvd/cve-2024-33663) | CRITICAL | 3.4.0 |
| python-jose 3.3.0 | [CVE-2026-85394](https://avd.aquasec.com/nvd/cve-2026-85394) | CRITICAL | No informada; el aviso incluye hasta 3.5.0 |
| python-multipart 0.0.9 | [CVE-2024-53981](https://avd.aquasec.com/nvd/cve-2024-53981) | HIGH | 0.0.18 |
| python-multipart 0.0.9 | [CVE-2026-24486](https://avd.aquasec.com/nvd/cve-2026-24486) | HIGH | 0.0.22 |
| python-multipart 0.0.9 | [CVE-2026-42561](https://avd.aquasec.com/nvd/cve-2026-42561) | HIGH | 0.0.27 |
| python-multipart 0.0.9 | [CVE-2026-53539](https://avd.aquasec.com/nvd/cve-2026-53539) | HIGH | 0.0.30 |

No hubo hallazgos de secretos en este escaneo local. La detección corresponde al
archivo `backend/requirements.txt`; no resuelve todas las dependencias transitivas
instaladas ni evalúa explotabilidad de cada ruta. Es un inventario mínimo de
bloqueos, no una afirmación de exposición demostrada para cada CVE.

Actualizar solamente python-jose a 3.4/3.5 **no elimina ambos avisos** según esta
base. La siguiente entrega debe evaluar una versión corregida o sustitución de
la biblioteca JWT, conservando algoritmo permitido, claims, expiración, refresh,
revocación y aislamiento de sesiones. Debe actualizar multipart y comprobar su
compatibilidad con FastAPI/Starlette, formularios de login y uploads con sus
límites. Repetir suite backend completa y escaneo; no añadir exclusiones para
ocultar estos hallazgos ni declarar un parche sin esa evidencia.

## Otros controles que siguen pendientes

- El CI frontend aprueba 1700 pruebas, pero falla el umbral global del 50 % en las
  cuatro métricas de cobertura. Sus umbrales/exclusiones no se reducen.
- El ruleset en `.github/rulesets/main.json` requiere activación administrativa;
  no protege main por estar versionado. Igual ocurre con revisores/environments.
- Faltan evidencia de infraestructura real, E2E integrado, carga, restore y
  homologación de pagos/transporte fiscal. El readiness no sustituye esas pruebas.

El gate agregado conserva el fallo y las imágenes de release no se publican
cuando alguno de sus controles no aprueba. No se ejecutó apply, migración
productiva, merge, pago, mensaje o factura durante esta entrega.

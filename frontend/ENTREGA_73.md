# Entrega 73 — Cerrar avisos backend y endurecer la frontera HTTP

Fecha: 7 de noviembre de 2026, America/Caracas.
Base limpia: `c02e625a4cd6eb0d074b3b41b5a628dbaa93280c`, árbol
`72e054695ff0aa8c676e66402185ad9ff912f825` (entrega 72, PR #313 todavía abierto).
Rama inicial: `fix/jwt-parser-and-request-boundaries-v1`.
Rama final: `fix/backend-security-finalization-v1`.

El trabajo comenzó como revisión dependiente de la entrega 72. Durante la
validación, GitHub registró #313 fusionado por el propietario en main y #314
fusionado en la rama anterior de entrega 72. Por ello se prepara una revisión
final contra main, que todavía solo contiene la entrega 72 en
`bfb5b299cb12d6b014723cc4d3d56a581cf4f2c7`. No se ejecutaron merges desde el agente.
CI contempla PR a cualquier rama, incluidas revisiones dependientes.

## Mejoras del bloque

1. Sustitución de python-jose por PyJWT 2.15.1, conservando firma wire compatible,
   epoch de credenciales, refresh y revocación. Claims obligatorios y estrictos,
   IDs no vacíos, fechas enteras acotadas, tipo access/refresh y límite de token.
   Los adaptadores de autenticación rechazan refresh/invalid con 401.
2. Multipart 0.0.33. Auditoría del entorno realmente instalado descubre y corrige
   además tres avisos altos transitivos de Starlette mediante FastAPI 0.162.2,
   Starlette 1.10.0 y Pydantic 2.9.2. Cryptography 50.0.2 queda explícito para fiscal
   y TLS en vez de depender incidentalmente de jose.
   El SARIF remoto expone tres moderados adicionales corregidos con aiosmtplib
   5.1.3 y geopy 2.5.0. No se desactivan severidades o validación TLS.
3. Límite previo a parsing para escrituras generales y login, conteo real de
   chunked bodies, rechazo de framing ambiguo, plazo de recepción y cleanup ante
   cancelación/desconexión. Uploads conservan su política y usan un solo spool.
4. Configuración de producción rechaza secreto predeterminado, longitud insuficiente,
   espacios extremos, algoritmos no soportados y duraciones no positivas. Los
   errores no imprimen inputs. No se rotan secretos ni credenciales existentes.
5. Herramientas pytest/Faker/carga/perfilado salen de dependencias de producción.
   Instalación nueva aislada con pip check, sin paquete jose residual.
6. `backend-security` escanea el freeze del runtime instalado, incluyendo transitivas,
   y conserva el informe. Es requisito del gate de release.
7. `backend-container` construye la imagen real sin publicar y comprueba UID,
   readonly, capacidades, ausencia de jose/pytest, dependencias reales, rechazo
   anónimo, límites previos a handlers y que no se cree la tabla users al arrancar.
   Al detener Redis exige readiness 503 y liveness 200. Es requisito del gate.
8. Inventario de API adaptado a contextos efectivos del framework: **203 rutas,
   orden y permisos idénticos**. Delta exacto de 24 campos OpenAPI revisado y
   comprobado contra hashes anteriores, conservando todos los fixtures históricos.

Contrato y operación: [SECURITY_AND_REQUEST_LIMITS.md](../backend/SECURITY_AND_REQUEST_LIMITS.md).

## Validación nueva y alcance

**94 pruebas netas nuevas**: 63 de JWT/configuración/adaptadores, 30 de frontera
HTTP y una que comprueba el delta del framework contra la superficie anterior.
Se conservan las pruebas de revocación, SMTP TLS, uploads, WebSocket, fiscal,
finanzas y transacciones PostgreSQL; no se sustituyen por mocks para hacerlas pasar.

| Control | Evidencia local nueva |
| --- | --- |
| Trivy requirements backend, HIGH/CRITICAL | **0** frente a 6 en la base |
| Trivy freeze instalado, HIGH/CRITICAL | **0**; el inventario previo a actualizar framework tenía 3 altos Starlette |
| Escaneo final runtime declarado, todas las severidades | **0** tras corregir también los 3 moderados SMTP/geopy |
| Escaneo final entorno dev, todas las severidades | 1 moderado pytest 8.3.2, fuera del runtime; pendiente migración de herramientas |
| Instalación aislada y pip check | Aprobados; crypto/fiscal explícito, jose ausente |
| Comparación de rutas/grafos de permisos | 203 rutas, orden y dependencias idénticos |
| OpenAPI | Solo 24 diferencias permitidas; hashes históricos preservados al revertirlas |
| Suite completa backend | **2540 aprobadas, 2 omitidas**, 640,57 s; cobertura 72 % |
| Verificación posterior a los últimos parches SMTP/geopy | **115 pruebas aprobadas**, 2,78 s, y smoke de distancia local sin red |
| Black aplicación, flake8 crítico, mypy | Aprobados, 195 archivos de aplicación |
| Contratos de release y workflows | 8 unittest y actionlint aprobados |
| Frontend | Código/dependencias intactos en este delta; no se atribuye una corrida local frontend nueva |

La corrida completa corresponde a JWT/framework/límites. Después se actualizaron
solo SMTP/geopy y se ejecutaron las 115 pruebas específicas con esas versiones
finales. El CI del head final vuelve a ejecutar el conjunto completo. Las 31
advertencias del completo incluyen deprecaciones del framework y una opción
pytest-asyncio existente; no se suprimen advertencias para forzar el resultado.

El primer foco aprobó 250 pruebas y expuso seis fallos del inventario antiguo,
que asumía rutas aplanadas. Se corrigió el inventario y se revisó el delta real;
no se reemplazó el golden sin comparar. El entorno limpio reveló crypto faltante
al retirar jose, resuelto con dependencia directa. La suite integral final usa
PostgreSQL/PostGIS y Redis exclusivos de prueba con base `test_delivery73`.

No se declara un build Docker local exitoso: el disco del driver vfs es acotado y
se reserva para las transacciones de prueba. El nuevo job remoto construye y
verifica el Dockerfile; ya aprobó para la implementación `47cae55620b9b59168f1090659faea6b3c04244a`,
incluyendo 200/503 real, liveness, 401, límites y ausencia de creación de users.
Su ejecución con los parches finales SMTP/geopy se distingue en el PR. Trivy no certifica
la imagen del sistema operativo ni ausencia de todas las severidades.

## Bloqueos que permanecen

Cobertura frontend global >=50 % (última evidencia base: 41,78 % local de líneas),
avisos npm dev, escaneo final de imágenes, activación administrativa de main y
environments, infraestructura/E2E/carga/restauración reales y homologación de
proveedores. Un payout aprobado sigue sin equivaler a liquidación bancaria.

Antes de desplegar deben revisarse los secretos reales, algoritmos configurados,
generadores cliente OpenAPI y los límites de recepción en móviles. No se envían
pagos, mensajes ni facturas, no se migra producción y no se fusiona o despliega.

## Publicación y estado remoto

- Primera revisión: https://github.com/corporacionbethelst-ux/Delivery_360-DEV/pull/314,
  fusionada por el propietario en la rama anterior, no en main. La revisión final
  contra main se identifica en el PR y el manifest verificable del workspace.
- Implementación acumulada final: `066ef2227f06281120b4e2acc2256bf77872dbce`, árbol
  `f9606d0591e2df77983b4ff7051b16f6b2d5943c`.
- [CI inicial](https://github.com/corporacionbethelst-ux/Delivery_360-DEV/actions/runs/42432924353)
  aprobó auditoría instalada, contratos, auditoría npm y contenedor backend.
  Su SARIF detectó los tres moderados ya corregidos posteriormente. Frontend
  mantiene el fallo de cobertura; no se atribuye éxito global al pipeline.
- El CI de la revisión final se informa por separado; no hereda el éxito de otro
  SHA. No se activa publicación ni deploy cuando un requisito falla.

Se conservan bundle incremental, patch, ZIP de fuentes sin archivos de entorno,
hashes SHA256 y observación del CI en `/workspace/work/entrega73`. El código y los
árboles publicados se cotejan con GitHub antes de cerrar el trabajo.

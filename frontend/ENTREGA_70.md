# Entrega 70 — Detalle de auditoría con consultas confirmadas

Fecha: 7 de noviembre de 2026, America/Caracas.
Base: `8a46bfb26f3a3c9a7724c5aa9511f96c287065a8` (PR #310 fusionado).
Rama: `fix/rider-audit-confirmed-reads-v1`.

Checkout limpio al iniciar, sin AGENTS.md aplicable. Se conserva el historial.
El CI final de la entrega 69 aprobó backend y seguridad. Frontend aprobó 1475
pruebas, tipos/lint/build y falló solo el gate global de cobertura del 50 %.
Esos resultados remotos de la base no se atribuyen a esta implementación.

## Problemas confirmados y cambios

El detalle de auditoría publicaba bloques de distintas lecturas, convertía fallos
en listas vacías, carecía de retiro por cuenta/ruta y leía solo el primer lote del
resumen. Interpretaba campos camelCase que el HTTP no entrega e inventaba
moneda/cero o un bono pendiente. El total del resumen solo cuenta filas de la
página y no permite inferir el tamaño global. Las órdenes
sin registro de entrega se mezclaban con entregas reales.

- Servicio específico con contratos reales y consultas acotadas por rider. Tres
  páginas de hasta 50 filas con lookahead; navegación independiente y sin total
  global inventado. Búsqueda del resumen de hasta cinco páginas/500 registros,
  con identidad y duplicados comprobados y ausencia dentro del límite explícita.
- Resumen y tablas se confirman como un conjunto. Un fallo mantiene el conjunto
  anterior; un error frío ofrece reintento. Reintentar conserva los offsets del
  intento, refrescar conserva los confirmados y reiniciar permite recuperar páginas.
- Se separan hasta 50 órdenes de apoyo de la primera página de entregas, con
  estado derivado y enlace de orden; no se cuentan como entregas completadas ni
  como indicio de otra página. Se validan los envelopes legacy y sus totales.
- Identidades/aliases, estados, conteos, proporción SLA, dinero y fechas se validan.
  Ceros/coordenadas 0,0/Offline se conservan; ausencias siguen desconocidas. Se
  contemplan el empate de redondeo SLA de Python y su resta float legacy.
- Servicio/controlador/frontera retiran respuestas anteriores o de otra cuenta,
  rol o ruta; solo se monta el detalle privado para GERENTE/SUPERADMIN autenticados.
  Los IDs son completos y los enlaces codificados. Los agregados del servidor
  se distinguen de las páginas y no se presentan como prueba bancaria.

Contrato y ejecución: [RIDER_AUDIT_DETAIL.md](RIDER_AUDIT_DETAIL.md).
El catálogo de auditoría y los servicios genéricos permanecen fuera de este bloque.

## Validación nueva

**125 pruebas netas nuevas**, en cinco suites de contrato, servicio, controlador,
UI e integración con Axios/API real y adaptador en memoria. Se mantienen las
pruebas y verificaciones anteriores, sin reducir umbrales ni excluir fuentes.

| Control | Resultado local de esta entrega |
| --- | --- |
| Frontend completo con cobertura | **1600 aprobadas / 87 suites**, 35,728 s |
| Statements / ramas / funciones / líneas | 42,70 % / 40,66 % / 38,90 % / **41,15 %** |
| Gate global del 50 % | Sigue fallando en las cuatro métricas; sin cambios de umbral/exclusiones |
| Contrato, servicio y controlador nuevos | 100 % de líneas |
| TypeScript y lint | Aprobados; 22 advertencias existentes fuera del bloque |
| Build con Inter real | Aprobado, 48 páginas; tipos/lint activos |
| Chromium sobre build final | **7 comprobaciones**, 53 lecturas, cero escrituras y cero excepciones pageerror |
| git diff --check / Black del script | Aprobados |
| Backend | Sin cambios ni atribución de una corrida backend local nueva |

Chromium verifica búsqueda del resumen en segunda página, navegación independiente
de las tres tablas, lookahead oculto, apoyo separado de entregas reales, fallo de
un bloque con conservación conjunta y reintento exacto, rechazo de otro rider,
reinicio, móvil, cambio de ruta y logout con resumen pendiente. Se interceptan
HTTP/WebSocket con datos sintéticos y se revisan capturas de escritorio y móvil.
Esta evidencia local no sustituye una integración contra datos o proveedores reales.

## Límites y siguiente prioridad

La confirmación conjunta en la UI no aporta snapshot entre endpoints. Los offsets
y órdenes sin desempate estable pueden omitir filas concurrentes; los solapes
observables se rechazan sin prometer detectar todas las omisiones. El resumen no
admite rider_id y su búsqueda se limita a 500; el bloque de apoyo se limita a 50.
El backend no informa moneda y reemplaza algunas ausencias antes del HTTP. El
cliente no puede auditar con estas páginas todo el ledger ni certificar pagos.

La siguiente prioridad concreta es el catálogo de auditoría por repartidor:
consultas/filtros confirmados, sesión, paginación y alcance de métricas/CSV. Siguen
pendientes filtro exacto/cursor estable en backend, cobertura global del 50 %, E2E
con backend real y homologación sandbox de la fase 7. No se envían pagos, mensajes
o facturas, no se ejecutan migraciones productivas, merge o deploy. La publicación
y el estado observado del CI se registran por separado.

## Publicación verificada

- PR sin borrador: https://github.com/corporacionbethelst-ux/Delivery_360-DEV/pull/311
- Implementación: `63c5d16dc420e5fc9959d1ca183da107553abf89`.
- Árbol de implementación cotejado local/GitHub: `75ba6d7ae2e869f2d8633a829adfa94e7184cc51`.
- Se publican 15 archivos de implementación/pruebas/documentación. Un segundo
  commit exclusivamente documental registra estos identificadores.
- El PR informa el CI observado del head final por separado de las validaciones
  locales. La publicación no fusiona ni despliega la rama.

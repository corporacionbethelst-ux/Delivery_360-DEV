# Entrega 65 — Historial navegable y consulta de decisiones inciertas

Fecha: 6 de noviembre de 2026, America/Caracas.
Base verificada: `0b9b257ab626da784fc8191f8272f15cb60bdca8` (PR #305 fusionado).
Rama: `fix/payout-history-pagination-and-decision-recovery-v1`.

El repositorio recibido estaba limpio y no tenía AGENTS.md aplicable. Se conservan
las ramas previas. El CI final de la entrega 64 aprobó backend, seguridad y el
build frontend; su fallo fue el gate de cobertura. Esos resultados anteriores
no se atribuyen a esta implementación.

## Problemas confirmados y cambios

Los listados de gerencia y repartidor solo consultaban los primeros 50 retiros.
Aunque ya indicaban ese límite, no permitían llegar a los anteriores. El filtro
de estado de gerencia operaba únicamente sobre ese lote. Además, después de una
decisión incierta o de fallar la recarga del detalle, no había una consulta de
recuperación accesible en la misma pantalla.

- Ambos listados navegan en páginas de 50. Cada petición lee como máximo 51 filas:
  la adicional permite decidir si hay una página siguiente y no se muestra antes.
  No se inventan totales globales ni un número total de páginas.
- El estado se consulta en servidor y vuelve al inicio. La búsqueda por ID/nombre/
  email de gerencia se declara local a la página; sigue permitiendo navegar cuando
  no encuentra coincidencias. Las métricas resumen la página cargada, no el
  conjunto completo ni solo las filas que coinciden con la búsqueda local.
- Un fallo de página/filtro conserva los datos y las etiquetas de la última
  consulta válida. Reintentar repite la consulta fallida. Refrescar conserva el
  offset actual y volver al inicio permite comenzar una lectura nueva.
- Las respuestas antiguas y sus errores no sustituyen una consulta posterior.
  Cuenta/rol nuevos limpian navegación, filtros y búsqueda. La sesión se comprueba
  antes y después del HTTP, incluido el intervalo posterior al interceptor Axios.
- Una repetición de IDs visibles entre páginas contiguas indica que el historial
  cambió: se conserva la página anterior y se pide volver al inicio, sin ocultar
  el problema mediante deduplicación o avanzando posiciones ficticias.
- Gerencia consulta nombres solo para los riders únicos de las 50 filas visibles,
  verifica que la identidad recibida coincida y muestra una indicación cuando no
  puede completar los datos. Una respuesta de nombres de una página retirada no
  se publica en la nueva. La fila de anticipación no dispara esa lectura adicional.
- El servicio copia los filtros del caller antes de esperar, para validar la misma
  consulta enviada aun si el objeto original se modifica mientras llega el HTTP.
- El detalle ofrece Consultar estado del retiro, tanto ante un fallo inicial como
  después de una decisión incierta. Solo lee detalle e historial: no reenvía PATCH.
  Mientras no pueda comprobarse el estado, se conservan los datos previos y se
  bloquean otras decisiones. Un estado pendiente leído permite otro clic deliberado.
- La confirmación administrativa comprueba también método y sufijo de cuenta
  contra el retiro revisado. Un resultado contradictorio se mantiene incierto.
  El diálogo de rechazo ya no afirma que cancela una transferencia bancaria.

Se actualiza [PAYOUT_CONFIRMATIONS.md](PAYOUT_CONFIRMATIONS.md). El historial de
entregas anterior se conserva; esta ampliación se registra en este archivo propio.

## Validación nueva

Se añaden **52 casos netos** sobre los 1052 de la base. Hay pruebas de navegación,
anticipación, fin real, filtros, errores posteriores, reintento, datos fuera de
orden, solapamientos, cuenta nueva, nombres incorrectos, búsqueda local y consulta
de decisiones sin repetirlas. Se incluyen seis integraciones con Axios y servicio
reales, usando un adaptador HTTP en memoria.

| Control | Resultado local |
| --- | --- |
| Suite completa con cobertura | **1104 aprobados / 67 suites**, 27,138 s; cero tests fallidos |
| Statements / ramas / funciones / líneas | 37,14 % / 33,65 % / 33,20 % / **36,81 %** |
| Gate global 50 % | Falla en las cuatro métricas; no se cambian umbrales ni exclusiones |
| TypeScript | Aprobado, sin errores |
| Lint | Aprobado; advertencias anteriores en otras pantallas; se retiran las de estas pantallas modificadas |
| Build estándar sin reutilizar caché de fuentes | Bloqueado al descargar Inter desde Google Fonts, conexión EPERM al proxy |
| Build adicional con recurso de fuente local | Aprobado: compilación, tipos/lint y **48 páginas** |
| git diff --check | Aprobado |
| Backend local | Sin modificaciones; no se atribuyen pruebas locales nuevas |

La caché anterior se preservó fuera del repositorio antes del build estándar.
La comprobación adicional usa el mecanismo de pruebas de next/font con bytes
locales de Open Sans y CIRCLE_NODE_TOTAL=3. No modifica layout, next.config,
dependencias, workflows o verificaciones. No valida la descarga/apariencia de
Inter ni sustituye el build estándar del CI, que se informa por separado.

Los primeros ensayos detectaron un fragmento de efecto pendiente de retirar en
la refactorización del listado y una aserción que aún nombraba el lote antiguo.
Se corrigieron el código y el texto esperado; la corrida completa indicada arriba
corresponde a la fuente final. No se relajaron validadores para aceptar datos falsos.

## Límites y continuidad

GET /payouts conserva limit/offset y su orden por requested_at: no ofrece un cursor
ni snapshot estable. La detección de solapamientos entre páginas vecinas no puede
detectar todas las omisiones, cambios lejanos o empates de ordenación. Cada página
refleja la lectura que respondió el servidor; no se certifica un historial global
consistente. La consulta de riders puede hacer hasta 50 lecturas adicionales.

Consultar un PENDIENTE no demuestra que un request previo haya sido cancelado.
La autorización, los bloqueos, las reservas y el débito único siguen dependiendo
del servidor. La consulta de recuperación no es un reintento automático financiero.
No se añade pasarela ni confirmación bancaria, ni se ejecutan pagos, mensajes,
facturas, migraciones productivas, fusiones o despliegues.

Quedan pendientes el gate del 50 %, E2E completos y paginación estable de backend.
El siguiente bloque de homologación financiera necesita el contrato de proveedor
sandbox, recibos durables, envío idempotente, verificación de webhooks y conciliación,
manteniendo separada la aprobación contable de la ejecución bancaria.

## Publicación verificada

- PR listo para revisión: https://github.com/corporacionbethelst-ux/Delivery_360-DEV/pull/306
- Commit de implementación: `ef60bbf6b71e8eb715b45751aca64263746da8f3`.
- Árbol validado local/remoto: `78281e61be2923723297917d9f5bbf0b89577b61`.
- Se cotejaron los 13 blobs de implementación. Un commit posterior únicamente
  documental añade estos identificadores, sin alterar la fuente probada.
- La descripción del PR informa el estado observado del CI de su head final.
  La publicación no equivale a aprobar el gate de cobertura ni a desplegar.

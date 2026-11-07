# Entrega 66 — Continuación del historial de retiros por cursor

Fecha: 6 de noviembre de 2026, America/Caracas.
Base verificada: `0f172f736529fe32905cbd0992eb152bf6431c27` (PR #306 fusionado).
Rama: `fix/payout-cursor-pagination-v1`.

El checkout estaba limpio y no se encontraron instrucciones AGENTS.md aplicables.
El PR #306 se fusionó durante la inspección inicial; se volvió a consultar GitHub
y se creó esta rama desde su merge, conservando las ramas anteriores.

## Problema confirmado

La entrega 65 permitió navegar, pero GET /payouts ordenaba solo por requested_at
y utilizaba offset. Los empates no tenían desempate y PostgreSQL situaba las fechas
vacías al principio. Una inserción/borrado anterior al desplazamiento podía repetir
u omitir retiros. La detección de IDs repetidos solo identificaba algunos cambios.

## Implementación

- GET /payouts/page acepta rider_id, status, limit (1–200, 50 por defecto) y cursor
  opcional. Devuelve `{items, next_cursor}`. Lee hasta limit+1 registros, devuelve
  como máximo limit y usa null explícito cuando no observa otra página.
- La clave de ordenación es requested_at DESC NULLS LAST, id DESC. La continuación
  usa comparaciones estrictas de fecha/UUID, incluyendo la transición hacia fechas
  nulas y el recorrido entre ellas. No necesita que siga existiendo la fila límite.
- La firma HMAC-SHA256, con prefijo de dominio y SECRET_KEY existente, liga posición
  a usuario, rol, rider efectivo, estado y tamaño. La autorización vuelve a aplicarse
  en cada lectura. El cursor no es una credencial ni un recibo de pago. Cambiar su
  contenido/firma, consulta, cuenta, rol o clave de firma produce 400 recuperable.
  Forma/tamaño de parámetros inválidos producen 422. Los roles no admitidos siguen
  devolviendo 403; sin autenticación se obtiene 401.
- GET /payouts conserva el array/limit/offset anterior y comparte la autorización,
  ahora con orden determinista y fechas nulas al final.
- Ambos listados utilizan getPage. Siguiente usa la continuación del servidor;
  Anterior guarda límites en memoria; Actualizar repite la página actual; Volver
  al inicio y cambiar estado eliminan la continuación. Un fallo conserva datos,
  filtro y recorrido confirmados. Reintentar repite el intento fallido. Nunca se
  cambia automáticamente a offset cuando el cursor falla.
- El servicio valida envelope, continuación explícita, tamaño, duplicados, filtro,
  identidad y contrato financiero. Rechaza una continuación circular o asociada a
  una página parcial. Copia parámetros y comprueba sesión después del HTTP.
- Se conservan retiro de respuestas antiguas, limpieza por cuenta/rol y detección
  de solapamientos. La UI indica cantidad de filas en la página y que el historial
  puede cambiar; deja de mostrar posiciones absolutas sobre un conjunto mutable.

Contrato ampliado: [PAYOUT_CONFIRMATIONS.md](PAYOUT_CONFIRMATIONS.md).
Se añade este registro al historial raíz sin reescribir entregas anteriores.

## Pruebas y resultados nuevos

Se añaden **29 casos frontend netos** sobre los 1104 de la base y **28 casos backend**
(26 HTTP/SQLite y dos con PostgreSQL real). Se adaptan las pruebas anteriores al
contrato de cursor; no se retiran los controles de sesión, errores o solapamientos.

| Control | Resultado local de esta fuente |
| --- | --- |
| Suite completa frontend con cobertura | **1133 aprobados / 68 suites**, 18,603 s; ningún test fallido |
| Statements / ramas / funciones / líneas | **37,24 % / 33,81 % / 33,33 % / 36,89 %** |
| Gate global 50 % | Sigue fallando en las cuatro métricas; comando termina con exit 1 |
| TypeScript | Aprobado, también después del build |
| Lint frontend | Aprobado; advertencias anteriores en otras pantallas/componentes |
| Build Next con Inter real | Aprobado: compilación, tipos/lint y **48 páginas** |
| Bloque financiero backend | **107 aprobados**, incluye paginación, reservas, recuperación, ledger y concurrencia PostgreSQL |
| Mypy | Aprobado, 194 fuentes; notas anteriores sobre cuerpos sin anotaciones |
| Flake8 / Black de app | Aprobados; 194 archivos conformes a Black |
| git diff --check | Aprobado |

El backend usa Python 3.11 y dependencias existentes instaladas en un entorno
aislado fuera del repositorio. PostgreSQL 16 se ejecutó en un contenedor local
dedicado y una base test_delivery66; las pruebas PostgreSQL crean y retiran esquemas
privados. No se conecta a datos productivos. La advertencia existente de pytest
por asyncio_default_fixture_loop_scope permanece sin cambiar dependencias.

La primera corrida de fixtures detectó UUID puramente numéricos convertidos por
la afinidad SQLite, una función espacial ausente del stub y el intento de recrear
un enum PostgreSQL existente. Se corrigieron exclusivamente los fixtures (UUID
con prefijo hexadecimal, stub de lectura espacial y checkfirst); la corrida final
usa validadores y SQL reales, sin relajar la implementación.

La conectividad de shell funciona al solicitar el acceso de red del entorno.
Se preservó .next anterior fuera del checkout y se compiló desde caché nueva,
sin sustitución de fuentes ni NEXT_FONT_GOOGLE_MOCKED_RESPONSES. Se limitó el número
de workers con CIRCLE_NODE_TOTAL=3, conservando las verificaciones del build.

## Límites y continuidad

El cursor evita desplazamientos por inserciones más recientes/borrados anteriores,
pero no mantiene un snapshot de base de datos entre peticiones. Los cambios de
estado, borrados no vistos, inserciones con fechas antiguas o correcciones de fecha
pueden modificar lo observado. Volver al inicio lee novedades; Anterior vuelve a
consultar límites guardados, sin prometer la misma foto histórica. El número de
página es local al recorrido. No se publican totales globales ni posiciones fijas.

Las continuaciones no caducan por tiempo, no conceden acceso y solo se mantienen
en memoria en estas pantallas. Rotar SECRET_KEY las invalida. Backend y frontend
requieren disponibilidad conjunta del nuevo endpoint; si falta, se conserva el
error visible. No se añaden índices o migraciones sin una medición del volumen y
plan SQL: la lectura es acotada, pero no se certifica latencia con datos masivos.

La aprobación/rechazo, reservas, saldos y transacciones financieras no cambian.
No se envían pagos, mensajes o facturas reales, ni se despliega, fusiona o ejecutan
migraciones productivas. No se modifican dependencias, umbrales, exclusiones o CI.

La siguiente prioridad verificable es aumentar cobertura con recorridos de sesión
y operación completos. La fase 7 del roadmap sigue requiriendo homologar proveedor
sandbox, recibos durables, envío idempotente, webhooks verificados y conciliación;
no se presenta esta mejora de lectura como una integración bancaria homologada.

## Publicación

Los identificadores de commit/PR y el estado observado del CI se registran al
publicar y se cotejan con el árbol local validado. El gate pendiente impide declarar
todo el CI aprobado o el sistema al 100 % para producción.

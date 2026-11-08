# Entrega 77 — Fichas de flota claras y edición fiable

Fecha: 8 de noviembre de 2026, America/Caracas.
Base limpia: `5d6b63c3e7c5d8e376743180a2e2a189427f6f79`, árbol
`b1157a63480aee591d6def161b0f037689ddb5a4` (entrega 76, PR #318 fusionado por el propietario).
Rama: `feat/fleet-editor-reliability-v1`, revisión contra main.

## Presentación

Las fichas de edición de vehículo y zona siguen la referencia del formulario de
orden y los listados renovados: encabezados azul/cian o violeta, identificación
del registro cargado, controles uniformes y tarjetas con color por sección.
Seguro ámbar, observaciones violetas, tarifas ámbar y estado/prioridad verde.
Se conservan campos, acciones de guardado, recarga y confirmación de eliminación.

Los selectores y switches tienen etiquetas asociadas. Los controles se bloquean
durante una operación pendiente y la zona mantiene una única barra de acciones,
fija en móvil y dentro del flujo en escritorio, con espacio para alcanzar todos
los campos. Se revisan capturas de las dos fichas y del diálogo móvil.

## Correcciones

- **Lecturas:** una respuesta fallida o de otro ID no expone un formulario armado
  con valores iniciales. Se ofrece recarga explícita. El ID de la respuesta debe
  corresponder al solicitado; las respuestas antiguas se retiran al cambiar de ruta.
- **Operaciones:** guardado y eliminación usan la ficha efectivamente cargada.
  Un resultado tardío no modifica otra ficha ni redirige desde ella. Se cancelan
  los temporizadores de éxito al desmontar o sustituir la ficha. Los errores de
  guardado conservan el borrador para corregirlo.
- **Coordenadas:** null/ausente se conserva como null, sin inventar un centro en
  cero. Se muestran campos reales de latitud y longitud, que admiten vacío, cero
  y rangos válidos. Sustituyen un botón de ajuste en mapa que no tenía acción.
- **Validación:** nombres y códigos vacíos tras trim, tarifas no finitas/negativas,
  minutos fraccionarios o fuera de 1–240, multiplicadores fuera de 0.1–5 y
  coordenadas fuera de rango se rechazan antes del servicio. El año del vehículo
  se valida como entero en lugar de redondearlo con parseInt.
- **Asignación:** `rider_id` es un ID de usuario y no sustituye al ID de perfil de
  repartidor. Ver Rider usa exclusivamente `rider_profile_id`; si no se informa,
  no se inventa un enlace. Una asignación sin nombre no se muestra como Sin asignar.
- **Seguro:** la fecha se compara por día calendario local. Vence hoy no se trata
  como vencida desde medianoche UTC; las etiquetas describen la fecha, sin inferir
  cobertura de una póliza.
- **Zonas:** contadores desconocidos no se convierten en cero y no se inventa
  moneda para las tarifas. El ejemplo de bono usa unidades ilustrativas, conserva
  el multiplicador completo y marca como aproximado el resultado redondeado.
  La confirmación de eliminación identifica la zona cargada, aunque el borrador
  contenga otro nombre sin guardar.

Las revisiones de edición y conflictos de vehículos mantienen su contrato.
La protección de zonas vincula operaciones a la ficha/ruta del cliente; no añade
control de concurrencia entre operadores ni una revisión nueva al backend.

## Evidencia de esta entrega

| Control | Resultado local nuevo |
| --- | --- |
| Casos de edición adicionales | **37 aprobados**, identidades, rutas, pendientes, validaciones, coordenadas y fechas |
| Suite frontend final | **2257 pruebas / 111 suites aprobadas**, 41,306 s |
| Cobertura global | **56,79 % sentencias; 52,45 % ramas; 52,45 % funciones; 55,74 % líneas** |
| Mínimos y fuentes incluidas | Sin cambios; los cuatro mínimos de 50 % pasan |
| TypeScript, lint y build | Aprobados; **48 páginas**, 20 advertencias anteriores, sin desactivar reglas |
| Chromium sobre build final | **40 comprobaciones**: flota 15, entregas 8, catálogo auditoría 7, detalle 7, producción 3 |
| Tráfico de negocio en navegador | Datos sintéticos interceptados, **0 escrituras y 0 excepciones JavaScript** |
| Formato | Prettier de las fichas y pruebas, Black del smoke ampliado |
| Backend, servicios, dependencias y formulario original de orden | Sin cambios; no se atribuye una nueva corrida backend local |

Jest simula servicios para comprobar guardados y eliminaciones válidos, conflictos
y respuestas tardías. El navegador prueba lecturas, reintentos, validación local
y cancelación; bloquea los métodos de escritura. Los cinco smokes anteriores se
conservan y el de flota incorpora las fichas, dentro del mismo contenedor requerido
por CI. No se declara una certificación integral de accesibilidad.

El CI completo de la entrega 76 terminó aprobado. Esta revisión se publica sin
draft y se observa por su propio SHA. El estado remoto queda en el PR y en
`/workspace/work/entrega77/ci-observation.json`, separado de las pruebas locales.

Se conservan bundle incremental, patch, ZIP de fuentes sin archivos de entorno,
hashes, registros y capturas en `/workspace/work/entrega77`. Sin merge, deploy,
migraciones ni operaciones productivas desde el agente. Continúan pendientes las
verificaciones de infraestructura, staging y proveedores de entregas anteriores.

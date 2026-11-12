# Entrega 85 — Configuración y simulador de bonos

Fecha de registro: **11 de noviembre de 2026, America/Caracas**.
Rama: `feat/platform-settings-reliability-v1`.
Base main: `0c8e409fd01d0c96c0a3ed2b339bd4c7ccd3d2e3`, árbol
`7806903e6c3933629229d985fed0123f5a455d81`. El propietario integró la entrega
84 mediante PR #326; su CI completo terminó aprobado. Los logs conservan UTC.

## Configuración real y presentación

Configuración adopta encabezado azul/cian, tarifas azules, bonos violeta y estado
del sistema ámbar. Conserva operación, soporte, mantenimiento y simulación, con
campos etiquetados, avisos de resultado y presentación adaptable.

- El servicio deja de fabricar cero, bonos 2,50/1,00, email de soporte o estado
  booleano a partir de campos inválidos. Conserva null como **Sin configurar**,
  cero como valor real, false y la precisión informada por el servidor.
- Una lectura fallida no habilita un formulario con valores predeterminados.
  Si hay una lectura anterior, se conserva con su hora y se bloquea la edición
  hasta una nueva consulta confirmada. Las fechas UTC heredadas se muestran en
  America/Caracas, distinguiendo fecha de consulta y actualización informada.
- Gerencia consulta y simula; solo superadministración ve y utiliza el guardado,
  conforme a los permisos existentes de la API. Los demás roles no consultan
  esta página. La frontera de acceso retira resultados y borradores al cambiar
  cuenta, rol o credenciales.
- Los importes admiten punto o coma decimal, cero y precisión sin redondear el
  payload. Un vacío no se convierte en cero. Comisión, email y zonas se validan
  antes de enviar. Las zonas se editan una por línea: una coma dentro de un nombre
  no crea otra zona. Los campos sin editar permanecen fuera de la actualización.
- Mantenimiento distingue el estado guardado del borrador; no se afirma que su
  bandera por sí sola aplique restricciones que esta pantalla no comprueba.

## Revisión y guardado

Revisar cambios muestra una confirmación con los valores guardados y propuestos
de los campos editados. Cancelar conserva el borrador. Recargar un formulario
modificado permite conservarlo o descartarlo explícitamente.

Antes de PATCH se consulta de nuevo la configuración y se comparan únicamente
los campos que se actualizarán con la lectura capturada. Si alguno cambió, no se
envía PATCH y se exige recargar. Los cambios concurrentes a otros campos se
conservan porque el payload es parcial. Campos, recargas y cierre de la
confirmación quedan bloqueados durante la operación, con guardia síncrona contra
duplicados. El acuse debe confirmar los valores enviados; una respuesta incierta
no presenta éxito y requiere otra lectura antes de repetir.

**Límite de concurrencia:** la consulta previa es una protección del cliente, no
una precondición atómica del servidor. Otro escritor puede actuar entre GET y
PATCH. Esta entrega no añade revisiones, bloqueo transaccional ni garantías contra
esa carrera. Debe resolverse en la API antes de considerar completo el control
concurrente de configuración. La autorización del backend sigue siendo obligatoria.

## Simulador

El bono propuesto parte del bono realmente guardado, incluyendo cero. Si el bono
es null, la simulación permanece bloqueada. Se retiran la propuesta fija 2500 y
la moneda COP asumida. El período histórico es explícito, entero de 1 a 90 días;
30 es su selección inicial, no un importe predeterminado.

Antes del cálculo se consulta el bono guardado y se detiene si cambió. Los inputs
y duplicados quedan bloqueados mientras se calcula; deshabilitar, recargar o
retirar la página impide continuar etapas pendientes. Cada resultado identifica
bono propuesto, período e instante de consulta. Un recálculo fallido conserva el
resultado anterior con sus parámetros reales. Un costo histórico cero se muestra
como **Sin base porcentual**, sin convertir la falta de denominador en 0 % útil.

Los costos y la diferencia se presentan como importes del cálculo, sin conversión
de moneda ni anualización. La API conserva sus nombres heredados monthly_cost,
pero utiliza el total histórico del período solicitado; el frontend no lo etiqueta
como una proyección mensual garantizada. No se usa su texto interpretativo mensual
para afirmar un período o efecto diferente. La fórmula y los contratos backend
no cambian; siguen pendientes una moneda explícita y una revisión del modelo de
proyección. Simular no cambia los valores de los bonos.

## Contratos y evidencia

El servicio comprueba campos financieros finitos o null explícito en lecturas,
banderas booleanas, zonas, metadatos y shape de respuestas. Las escrituras validan
campos permitidos, límites, email y listas; los cálculos exigen importes finitos,
períodos válidos y coherencia entre costo actual, propuesto y diferencia. Todas
las respuestas se vinculan a la generación original de credenciales.

| Control | Resultado local |
| --- | --- |
| Casos nuevos | **86 aprobados**: 53 de servicio/datos, 33 de página y simulación |
| Suite frontend completa | **2780 pruebas / 124 suites aprobadas**, 49,668 s |
| Cobertura global | **65,18 % sentencias; 61,44 % ramas; 62,37 % funciones; 64,90 % líneas** |
| Mínimos y selección | Sin cambios; pasan los cuatro mínimos de 50 % |
| TypeScript y build con lint | Aprobados; **48 páginas**, 16 advertencias existentes |
| Chromium | **150 comprobaciones**: configuración 13 y los doce smokes anteriores 137 |
| Navegador | Lecturas y cálculos sintéticos; **cero escrituras persistentes y cero excepciones JavaScript** |
| Formato y workflow | Prettier, Black y actionlint aprobados |

Jest simula los servicios para verificar PATCH mínimos, permisos, acuses,
conflictos detectados, resultados inciertos, retiros de sesión y cálculos.
Chromium usa el build standalone real, bloquea escrituras persistentes e
intercepta únicamente los POST del cálculo con respuestas sintéticas. Comprueba
formularios, revisión/cancelación, detección de cambios y controles pendientes;
no envía un guardado real ni certifica E2E de staging o accesibilidad integral.
El nuevo smoke se añade al frontend-container requerido, conservando los doce
anteriores. Se corrige además la asociación accesible de la ayuda de la matriz
de roles mediante aria-describedby.

Backend, dependencias y formulario original de orden sin cambios. No se atribuye
una nueva corrida backend local. El CI remoto se observa por SHA en el PR y en
`/workspace/work/entrega85`, junto a logs, capturas y archivos de verificación.
Se conservan ZIP sin archivos de entorno, bundle incremental, patch y hashes.
Publicación por rama y PR previamente autorizada; sin merge, deploy, migraciones
ni operaciones productivas del agente. Continúan pendientes infraestructura,
staging, carga, restauración, proveedores, protección de main y los límites de
concurrencia y simulación descritos arriba.

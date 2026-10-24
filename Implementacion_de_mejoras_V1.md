# Implementación de mejoras — Delivery360 — V1

**Fecha:** 24 de octubre de 2026, America/Caracas.  
**Estado:** propuesta de implementación pendiente; ninguna mejora de código se ejecuta con este documento.  
**Código revisado:** commit `d6ce659e9afe039fbe6d74ec3a8a7e6d9f0df488`.  
**Alcance de esta actualización:** guardar el diagnóstico, las fases, sus dependencias y los criterios de preparación para producción. Crear este documento no autoriza por sí mismo pagos, migraciones, despliegues ni cambios de datos.

Para llevar Delivery360 a producción y después competir con el alcance de Yummy, hay que completar tres trabajos distintos: corregir la base existente, terminar las fases 7–10 y desarrollar los productos que hoy no existen, especialmente comercios, clientes y transporte de pasajeros.

El roadmap actual cubre principalmente la operación de repartidores. Completarlo literalmente no produciría todavía una plataforma equivalente a todo el ecosistema de Yummy.

## Fuentes y alcance de la revisión

Se contrastaron los siguientes documentos con endpoints, servicios, modelos, migraciones, frontend, workers y configuración de CI/CD:

- [ROADMAP_PROXIMAS_FASES_7-10.md](ROADMAP_PROXIMAS_FASES_7-10.md).
- [4-informe_comparativo_delivery360_vs_yummy.md](4-informe_comparativo_delivery360_vs_yummy.md).
- [Informe_Sistema_V1.md](Informe_Sistema_V1.md), como referencia del análisis anterior.

También se revisaron páginas públicas de Yummy para actualizar el alcance de comparación. La información comercial publicada no constituye una auditoría del funcionamiento interno de Yummy ni acredita su arquitectura, proveedores, rendimiento o algoritmos.

La revisión que fundamenta esta propuesta fue informativa: no modificó código ni datos. Los cálculos puros indicados se reprodujeron de forma aislada; los demás hallazgos se sustentan en lectura del código y evidencia previa identificada. No se ejecutaron pagos, migraciones ni cierres de entregas. No se relanzaron las suites históricas de pruebas ni se inspeccionó producción.

## 1. Qué hay que corregir en la interpretación del roadmap

| Afirmación documental | Lo que respalda el código revisado | Consecuencia |
|---|---|---|
| Bonos completados al 100 % | Existe la fórmula y el desglose, pero hay cierres inconsistentes y modificación del tier desde el perfil propio | Requieren consolidación y controles antes de considerarse terminados |
| Sistema financiero 96/100 | Conviven libros, unidades y caminos de escritura diferentes | Esa puntuación no acredita integridad financiera |
| Fase 7: pagos reales | Existen modelos y gestión de retiros; no se encontró un circuito completo de desembolso real con proveedor | Falta la integración financiera efectiva |
| Fase 8: mapas avanzados | Hay tracking, mapas y optimización heurística | Falta cerrar autorización, WebSocket, sincronización y restricciones operativas |
| Fase 9: app móvil | El código utiliza “fase 9” para notificaciones | La app móvil del roadmap sigue siendo un trabajo separado |
| Fase 10: consolidación financiera | Hay fiscalidad, FX y snapshots de reparto | No equivale a facturación validada ni liquidación real a comercios |
| 2FA completado | No se encontró un flujo completo de enrolamiento, verificación y recuperación en los módulos revisados | Debe permanecer pendiente de implementación o demostración |
| Listo para producción | Persisten bloqueantes de seguridad, dinero, compilación y operación | Esa conclusión documental no sirve como criterio de lanzamiento |

Las cifras de calificación, presupuestos y plazos de los documentos antiguos son estimaciones históricas, no mediciones verificadas de preparación actual. También hay afirmaciones sobre arquitectura interna, proveedores y algoritmos de Yummy que esos documentos no demuestran; no deben utilizarse como base cierta para decidir tecnología o presupuesto.

## 2. Qué significa hacer todas las funciones de Yummy

La oferta pública consultada incluye delivery de varias categorías, movilidad, marketplace y servicios adicionales para comercios. Esto amplía considerablemente el alcance original de Delivery360. Fuente: [oferta pública de Yummy](https://www.yummysuperapp.com/).

Yummy presenta además soluciones corporativas para administrar usuarios, presupuestos, viajes y envíos, y una plataforma de publicidad autogestionada. Fuentes: [Yummy Corporate](https://corporate.yummysuperapp.com/) y [Yummy Ads Manager](https://marcas.yummysuperapp.com/).

| Objetivo | Qué debe poder hacer Delivery360 |
|---|---|
| Producción logística | Administrar pedidos, repartidores, entregas y dinero con seguridad y trazabilidad |
| Competencia en delivery | Permitir que clientes compren a comercios, paguen, reciban y resuelvan incidencias |
| Competencia en movilidad | Solicitar y ejecutar viajes de pasajeros |
| Competencia como ecosistema | Incorporar empresas, marketplace, fidelización y servicios adicionales |
| Superación competitiva | Demostrar mejores resultados en entregas, soporte, transparencia o rentabilidad |

“Superior a Yummy” debe convertirse en objetivos medibles. No puede deducirse de tener más módulos, usar microservicios o incorporar IA.

## 3. Bloqueantes antes de ampliar el producto

Estos problemas pertenecen a una fase de estabilización obligatoria. P0 indica bloqueo prioritario del alcance afectado; P1 indica alta prioridad. Los defectos estáticos no implican que se haya realizado una explotación ni que se haya observado su impacto en producción.

| Prioridad | Problema verificado o sustentado en el código | Riesgo |
|---|---|---|
| P0 | Cierre de entrega sin comprobación uniforme de propietario | Alteración de operaciones ajenas |
| P0 | Actualización del propio tier por el repartidor | Modificación de un factor de remuneración |
| P0 | Distintas rutas generan cierres y movimientos financieros diferentes | Compensaciones inconsistentes |
| P0 | Estado de entrega y compensación no forman una operación atómica uniforme | Entregas cerradas sin movimiento correspondiente |
| P0 | Reservas y escrituras de saldo sin un bloqueo común obligatorio | Riesgo de retiros concurrentes incompatibles |
| P0 | Documentos personales publicados mediante montaje estático | Acceso por URL sin autorización del propietario |
| P0 | Caché sin identidad en la clave | Diseño incompatible con respuestas privadas |
| P0 financiero | Cálculo incorrecto del total con IVA incluido | Facturación por importe incorrecto |
| P1 | Wallet usa UserRole.RIDER, inexistente | Fallo directo al utilizar ese circuito |
| P1 | Servicio síncrono de wallet recibe sesión asíncrona | Incompatibilidad de ejecución |
| P1 | Tracking WebSocket mal anotado y autorización de canales incompleta | Handshake defectuoso o acceso indebido |
| P1 | Estados terminales y OTP no están protegidos uniformemente | Reapertura y evidencia insuficiente |
| P1 | Workers con imports y atributos incompatibles | Automatizaciones no operativas |
| P1 | Contratos de frontend, API y modelos desalineados | Pantallas y operaciones fallidas |
| P1 | Simulaciones devuelven estados aparentemente exitosos | Indicadores que no acreditan ejecución externa |

Referencias de código:

- Cierre de entregas: [backend/app/api/v1/deliveries.py](backend/app/api/v1/deliveries.py#L508).
- Modificación del tier: [backend/app/api/v1/riders.py](backend/app/api/v1/riders.py#L831).
- WebSocket y archivos estáticos: [backend/app/main.py](backend/app/main.py#L148).
- IVA incluido: [backend/app/services/tax_engine.py](backend/app/services/tax_engine.py#L201).
- Conversión monetaria: [backend/app/services/fx_service.py](backend/app/services/fx_service.py#L78).

### Cálculos comprobados nuevamente

Se ejecutaron únicamente funciones de cálculo extraídas, sin importar la aplicación, conectar la base ni iniciar tareas.

| Caso | Resultado |
|---|---|
| Precio de 11.600 centavos con IVA incluido al 16 % | El cálculo devuelve total de 10.000; debería conservar 11.600 bajo esa regla |
| Conversión cuyo resultado es 1,50 unidades menores | Devuelve 1, aunque el comentario promete redondeo HALF_UP, que daría 2 |

En FX también se admite una tasa implícita de 1 para monedas desconocidas. Ese comportamiento puede servir como simulación de desarrollo, pero no debe autorizar una conversión monetaria real.

**Matiz de caché:** además de no aislar por identidad, existen problemas de inicialización y doble deserialización en la combinación revisada. El efecto inmediato al activar esa combinación puede ser un error en hits. No se afirma una fuga observada; corregir solo la deserialización dejaría el defecto de aislamiento.

## 4. Esquema general de fases pendientes

Se mantiene la referencia histórica 7–10 y se añaden subdivisiones para evitar confundir lo desarrollado con lo pendiente.

| Fase propuesta | Objetivo | Naturaleza |
|---|---|---|
| 0 | Estabilización, seguridad y contratos | Corregir |
| 7A | Consolidación contable y saldos | Corregir y completar |
| 7B | Cobros, retiros y conciliación reales | Desarrollar e integrar |
| 8 | Despacho, tracking y rutas operativas | Corregir y completar |
| 9A | Notificaciones confiables | Completar lo existente |
| 9B | App móvil de repartidores | Desarrollar |
| 10 | Fiscalidad, FX y liquidación comercial | Corregir y completar |
| 11 | Comercios, sucursales, catálogo e inventario | Desarrollar |
| 12 | Experiencia completa del cliente | Desarrollar |
| 13 | Soporte, devoluciones, reputación y seguridad operativa | Desarrollar |
| 14 | Supermercado, farmacia, paquetería y otras verticales | Desarrollar |
| 15 | Transporte de pasajeros | Desarrollar |
| 16 | Plataforma corporativa y API para empresas | Ampliar |
| 17 | Promociones, fidelización, suscripciones y publicidad | Desarrollar |
| 18 | Servicios adicionales del ecosistema | Desarrollar o integrar |
| 19 | Optimización y diferenciación demostrable | Evolucionar |
| P | Operación de producción y recuperación | Transversal a todas |

Las primeras fases permiten explotar una operación logística confiable. Las posteriores convierten esa operación en una plataforma comercial y de movilidad.

## 5. Fase 0 — Estabilización y seguridad

**Objetivo:** que el negocio existente tenga un comportamiento consistente y seguro.

### Trabajo pendiente

1. Centralizar la autorización por recurso:
   - Qué usuario puede leer o modificar cada pedido.
   - Qué repartidor puede operar cada entrega.
   - Qué roles pueden revisar documentos, modificar niveles o aprobar dinero.
   - Qué suscripciones WebSocket puede abrir cada identidad.
2. Separar campos de perfil y campos administrativos:
   - El repartidor solo modifica datos permitidos.
   - Tier, aprobación y asignaciones sensibles requieren permisos específicos.
   - Registrar actor, motivo y cambio.
3. Proteger documentos:
   - Almacenamiento privado y descarga autorizada.
   - Validación de archivos.
   - Retención y acceso auditado.
4. Consolidar contratos:
   - Unificar estados entre frontend, schemas, ORM y BD.
   - Resolver prefijos duplicados.
   - Corregir imports y tipos.
   - Definir una política única para users.id y riders.id.
5. Consolidar la máquina de estados:
   - Transiciones explícitas.
   - Rechazo de reapertura accidental.
   - Reintentos idempotentes.
   - Prueba de entrega según política del servicio.
6. Completar sesiones:
   - MFA para administración y operaciones financieras.
   - Gestión de sesiones y revocación.
   - Recuperación segura.
   - Suspensión operativa aplicada uniformemente.
7. Corregir o retirar temporalmente el caché de respuestas privadas hasta disponer de aislamiento e invalidación adecuados.

**Criterio de cierre:** las pruebas de permisos demuestran que un usuario no puede leer ni modificar recursos ajenos y que ninguna ruta alternativa evita las reglas del flujo principal.

**Dependencia:** precede al uso de pagos reales y a cualquier lanzamiento público.

## 6. Fase 7A — Unificación contable

**Objetivo:** disponer de una fuente coherente de verdad para el dinero.

Actualmente existen financials, financial_transactions, wallets alternativas y saldos auxiliares. No basta con corregir cada endpoint por separado.

### Trabajo pendiente

- Elegir el modelo contable canónico y definir cómo se conserva o migra el legado.
- Identificar moneda y unidad de cada importe.
- Usar reglas monetarias exactas; evitar flotantes para saldos y liquidaciones.
- Separar disponible, pendiente, reservado, en retiro y retenido por disputa.
- Registrar movimientos compensatorios en lugar de alterar historial financiero.
- Hacer obligatoria la idempotencia por evento de negocio.
- Establecer control de concurrencia compartido.
- Vincular entrega, compensación y evento contable de forma consistente.
- Corregir el auxiliar de conciliación que puede producir una nueva diferencia.

Para una plataforma que administrará fondos de comercios, clientes y repartidores, se recomienda diseñar partida doble con cuentas y asientos balanceados. El ledger actual no acredita por sí mismo ese modelo.

**Criterio de cierre:** repetir o ejecutar concurrentemente una operación no duplica dinero; el saldo se explica íntegramente mediante movimientos y reservas.

**Dependencia:** fase 0; base para 7B y 10.

## 7. Fase 7B — Pagos y retiros reales

**Objetivo:** convertir estados administrativos en operaciones verificables con proveedores.

### Trabajo pendiente

- Cobro al cliente: autorización, captura, cancelación y devolución.
- Desembolso al repartidor.
- Alta y verificación de beneficiarios.
- Métodos de pago tokenizados.
- Webhooks autenticados y resistentes a duplicación.
- Procesamiento de eventos fuera de orden.
- Reintentos y consulta posterior al proveedor.
- Conciliación entre proveedor y contabilidad.
- Comisiones, plazos y límites.
- Gestión de contracargos y disputas.
- Tratamiento de efectivo y rendición de cobros cuando corresponda.
- Resolución de operaciones cuyo resultado quedó desconocido tras un timeout.

**Decisión pendiente del roadmap:** Stripe y Mercado Pago son candidatos, no una garantía de disponibilidad. Deben seleccionarse proveedores según país, entidad operadora, moneda y producto que realmente permitan contratar. El fee de 1,5 % y los tiempos de retiro del documento requieren validación comercial; no se consideran vigentes por estar escritos allí.

**Criterio de cierre:** un cobro, retiro o devolución puede rastrearse desde la solicitud hasta el identificador y resultado del proveedor, incluso tras reinicios o webhooks repetidos.

**Dependencia:** 7A y controles de seguridad de fase 0.

## 8. Fase 8 — Despacho, tracking y rutas

**Objetivo:** asignar correctamente y seguir la operación en condiciones reales.

### Trabajo pendiente

- Corregir firma y autorización del WebSocket.
- Unificar geometría y coordenadas planas.
- Identificar antigüedad y precisión de posiciones.
- Reconexión y recuperación del último estado.
- Distribución de eventos entre varias instancias.
- Medición de frescura GPS.
- Geocodificación y direcciones utilizables.
- ETA basada en red vial y tiempos de preparación.
- Reasignación cuando un rider no acepta o pierde disponibilidad.
- Oferta de pedidos con vencimiento y aceptación atómica.

La asignación debe considerar más que cercanía:

| Factor | Razón |
|---|---|
| Disponibilidad real | Evitar asignar a alguien desconectado |
| Carga activa | No sobrecargar al mismo rider |
| Capacidad y vehículo | Compatibilidad con el envío |
| Zona | Restricciones de cobertura |
| Recogida y entrega | Precedencia correcta |
| Ventanas horarias | Cumplir compromisos |
| Tiempo de preparación | Evitar esperas innecesarias |
| Jornada y pausas | Respetar la operación del repartidor |

La optimización actual es heurística. Puede conservarse como alternativa inicial si cumple objetivos, pero debe incorporar restricciones y medirse contra una referencia justa.

No es obligatorio sustituir Leaflet para estar en producción. La visualización del mapa y el motor de rutas son decisiones diferentes.

**Criterio de cierre:** las asignaciones respetan restricciones; el tracking funciona entre instancias y el error de ETA se mide por zona y franja horaria.

**Dependencia:** fase 0; relación con infraestructura de eventos de fase P.

## 9. Fase 9A — Notificaciones confiables

Esta fase reconoce el trabajo de notificaciones que el código ya denomina “fase 9”.

### Trabajo pendiente

- Corregir deduplicación por destinatario, canal y evento.
- Separar estados de simulación, aceptación por proveedor y entrega.
- Configurar push, correo y SMS reales.
- Registrar respuestas y errores.
- Procesar confirmaciones cuando existan.
- Persistir eventos antes de intentar enviarlos.
- Disponer de reintentos y bandeja de fallos.
- Gestionar preferencias, dispositivos y tokens caducados.
- Evitar que un evento financiero crítico dependa exclusivamente de una tarea en memoria.

**Criterio de cierre:** un evento llega a todos sus destinatarios previstos y su estado refleja lo sucedido, sin marcar como enviado lo que solo fue simulado.

**Dependencia:** fase 0 e infraestructura de eventos de fase P.

## 10. Fase 9B — App móvil para repartidores

**Estado:** la web de rider no satisface por sí sola la app móvil propuesta en el roadmap.

### Trabajo pendiente

- Registro y revisión documental.
- Inicio y cierre de disponibilidad.
- Recepción, aceptación y rechazo de ofertas.
- Navegación.
- Tracking en segundo plano con permisos adecuados.
- Foto, firma, OTP o QR según política.
- Incidencias y soporte.
- Ganancias, reservas y retiros.
- Almacenamiento seguro de credenciales.
- Actualización y compatibilidad de versiones.

### Funcionamiento sin conexión

- Guardar entregas activas.
- Encolar acciones con identificadores idempotentes.
- Sincronizar sin duplicar cierres ni compensaciones.
- Resolver conflictos.
- Conservar evidencia con fecha de captura y de recepción.
- Informar qué acciones todavía no han sido confirmadas.

La biometría local de un teléfono no equivale a identidad verificada ni reemplaza automáticamente el MFA del servidor.

**Criterio de cierre:** los recorridos funcionan con pantalla apagada, conectividad intermitente, cierre de la app y reintentos, sin duplicar operaciones.

**Dependencia:** API estable, fases 8 y 9A; wallet sobre 7A/7B.

## 11. Fase 10 — Fiscalidad, moneda y liquidación comercial

**Objetivo:** transformar los componentes fiscales existentes en un circuito confiable para los países habilitados.

### Trabajo pendiente

- Corregir IVA incluido y redondeo.
- Manejar moneda y unidades menores correctamente.
- Rechazar o retener operaciones sin tasa válida.
- Registrar fuente, vigencia y tasa utilizada.
- Evitar tasas de desarrollo en operaciones reales.
- Corregir numeración, rangos y concurrencia.
- Integrar y validar proveedores fiscales por país.
- Diferenciar aceptación simulada de aceptación externa.
- Implementar notas, anulaciones y recuperación de errores.
- Definir quién factura a quién: comercio a cliente; plataforma por su servicio; repartidor cuando corresponda.
- Separar precio de mercancía, envío, comisión, impuesto, propina y descuento.
- Crear liquidación real al comercio.

El servicio actual declara expresamente que no hay modelo Vendor y fija restaurant_share_cents=0. El split actual no completa el reparto a restaurantes previsto por el roadmap.

**Criterio de cierre:** cada país habilitado tiene casos validados de emisión, rechazo, repetición y cancelación; la contabilidad concuerda con los documentos y liquidaciones.

**Dependencia:** 7A/7B y fase 11 para liquidar comercios.

## 12. Fase 11 — Comercios, sucursales y catálogo

**Objetivo:** convertir una plataforma de gestión de entregas en un marketplace de compra.

### Desarrollo pendiente

- Comercios y propietarios.
- Sucursales y personal.
- Verificación y contratos.
- Catálogo, categorías y productos.
- Variantes, modificadores y adicionales.
- Precios y disponibilidad.
- Horarios y cierres excepcionales.
- Inventario y reservas.
- Tiempos de preparación.
- Aceptación y rechazo de pedidos.
- Comisiones por contrato.
- Portal comercial.
- Reportes y liquidaciones.
- Integraciones POS concretas.

El POSConnector existente es una base genérica con URL de ejemplo; no demuestra integración productiva con un POS específico.

**Entidades previsibles:** comercio, sucursal, membresía, producto, variante, inventario, movimiento de stock, contrato y liquidación. Son propuestas de diseño, no tablas ya implementadas.

**Criterio de cierre:** un comercio administra su oferta, recibe una compra, prepara el pedido y comprende cuánto se le debe liquidar.

**Dependencia:** seguridad y aislamiento desde fase 0; dinero desde 7A/7B.

## 13. Fase 12 — Producto completo para clientes

**Objetivo:** que el cliente pueda realizar todo el recorrido sin intervención de un operador.

### Desarrollo pendiente

- Registro y recuperación.
- Direcciones y cobertura.
- Descubrimiento de comercios.
- Búsqueda y filtros.
- Detalle de productos.
- Carrito.
- Cotización y desglose.
- Checkout y pago.
- Entrega inmediata o programada.
- Seguimiento.
- Cancelación y devolución.
- Historial y repetición.
- Favoritos.
- Propinas y valoración.
- Accesibilidad y experiencia móvil.

Debe decidirse expresamente si el carrito admite varios comercios. Si los admite, debe generar subpedidos, cobros, asignaciones y cancelaciones coherentes.

**Criterio de cierre:** un cliente puede comprar, recibir, reclamar y obtener resolución sin que el equipo técnico intervenga.

**Dependencia:** 11, 7B, 8 y 9A; soporte y fiscalidad del alcance publicado antes del lanzamiento.

## 14. Fase 13 — Soporte, devoluciones y confianza

**Objetivo:** resolver las excepciones que aparecen diariamente en producción.

### Desarrollo pendiente

- Tickets vinculados a pedido, pago y entrega.
- Chat o mensajería con acceso controlado.
- Priorización, asignación y tiempos de atención.
- Productos faltantes, equivocados o dañados.
- Cliente ausente y dirección incorrecta.
- Cancelaciones según etapa.
- Devoluciones totales y parciales.
- Logística inversa.
- Evidencias y apelaciones.
- Valoraciones verificadas y moderación.
- Incidentes de seguridad.
- Procedimientos de escalamiento.

La reputación necesita registros verificables; un campo de rating o un componente visual no constituye un sistema completo de calificaciones.

**Criterio de cierre:** cada incidencia tiene responsable, evidencia, resolución y efecto contable trazable.

**Dependencia:** puede comenzar junto a 11 y 12; es requisito para su lanzamiento público.

## 15. Fase 14 — Verticales adicionales

**Objetivo:** soportar supermercado, farmacia, paquetería y otras categorías sin tratar todos los pedidos como una entrega de comida.

| Vertical | Capacidades específicas |
|---|---|
| Supermercado | Peso variable, sustituciones, faltantes y aprobación de diferencias |
| Farmacia | Restricciones y documentación según producto y jurisdicción |
| Bebidas y productos restringidos | Elegibilidad y verificación de recepción |
| Paquetería | Dimensiones, valor declarado, custodia y devolución |
| Retail | Variantes, stock, cambios y logística inversa |
| Mandados | Instrucciones, límites de gasto y comprobantes |

**Trabajo común:** capacidades del vehículo, manejo especial, reglas de precio, cobertura y prueba de entrega por servicio.

**Criterio de cierre:** cada vertical dispone de estados, excepciones, cobro y responsabilidades definidos.

**Dependencia:** marketplace, soporte y pagos.

## 16. Fase 15 — Transporte de pasajeros

**Objetivo:** cubrir el ámbito de movilidad representado por Yummy Rides.

Es un producto nuevo. Reutiliza identidad, mapas y pagos, pero no debe reducirse a renombrar una entrega.

### Desarrollo pendiente

- Perfil de pasajero.
- Habilitación de conductores.
- Categorías y requisitos de vehículos.
- Cotización.
- Solicitud y oferta de viaje.
- Aceptación y llegada al punto.
- Espera.
- Inicio y finalización.
- Cancelación y no presentación.
- Tarifa final, peajes y propina.
- Viajes programados.
- Valoración.
- Compartir recorrido.
- Soporte y SOS.
- Gestión de incidentes y requisitos operativos del mercado.

**Entidades previsibles:** solicitud de viaje, viaje, cotización, oferta, habilitación de conductor, tarifa y evento de seguridad.

**Criterio de cierre:** el ciclo completo del viaje y sus excepciones funciona en un piloto controlado, con soporte operativo disponible.

**Dependencia:** 7A/7B, 8, 9A/9B y 13.

## 17. Fase 16 — Empresas y API de última milla

**Objetivo:** permitir a empresas administrar usuarios, gastos y envíos con aislamiento.

### Desarrollo pendiente

- Organizaciones y membresías.
- Sucursales empresariales.
- Centros de costo.
- Presupuestos.
- Políticas de aprobación.
- Límites por usuario.
- Pedidos masivos.
- Viajes o envíos para terceros.
- Facturación consolidada.
- Contratos y SLA.
- API versionada.
- Credenciales con permisos.
- Webhooks documentados.
- Cuotas y entorno de pruebas.

**Criterio de cierre:** una empresa opera sin acceder a información ajena y concilia su consumo por usuario, centro de costo y período.

**Dependencia:** aislamiento, pagos y el producto logístico o de movilidad correspondiente.

## 18. Fase 17 — Crecimiento, fidelización y publicidad

**Objetivo:** competir en adquisición, recurrencia y monetización comercial.

### Desarrollo pendiente

- Cupones y promociones.
- Referidos.
- Créditos promocionales separados del dinero retirable.
- Programa de puntos.
- Suscripciones.
- Renovaciones, cancelaciones y beneficios.
- Campañas por ciudad y segmento.
- Espacios patrocinados.
- Presupuesto publicitario.
- Impresiones, clics y atribución.
- Prevención de abuso.

El coste de cada promoción debe asignarse a plataforma, comercio o ambos. Una promoción que funciona visualmente pero no se refleja en liquidación genera otra discrepancia financiera.

**Criterio de cierre:** se conocen coste, uso, contribución y efecto de cada campaña; los beneficios no crean dinero retirable indebidamente.

**Dependencia:** compras, contabilidad y analítica confiable.

## 19. Fase 18 — Extensión al ecosistema completo

Si “todas las funciones de Yummy” incluye su oferta pública ampliada, deben contemplarse estas líneas. Su sitio presenta marketplace, eventos, viajes y herramientas para comercios. Fuente: [ecosistema publicado por Yummy](https://www.yummysuperapp.com/).

| Línea | Desarrollo o integración necesaria |
|---|---|
| Marketplace entre vendedores y compradores | Publicaciones, identidad, moderación, mensajería y disputas |
| Eventos | Inventario, reserva, pago, emisión y validación de entradas |
| Viajes | Búsqueda, reserva, emisión, cambios y soporte mediante proveedores |
| POS | Caja, inventario, compras, devoluciones y sincronización |
| Comercio conversacional | Catálogo, cotización, confirmación y despacho desde mensajería |

Estas capacidades pueden construirse o contratarse mediante integración. No es necesario crear desde cero un sistema de reservas aéreas para ofrecer ese servicio.

**Criterio de cierre:** cada integración tiene responsabilidades, conciliación, soporte y tratamiento de fallos definidos.

**Dependencia:** identidad, pagos y APIs estables.

## 20. Fase 19 — Mejoras para superar a la competencia

Aquí comienza la diferenciación demostrable.

| Mejora propuesta | Qué debería demostrar |
|---|---|
| Bonos explicables y versionados | Menos disputas y comprensión del ingreso |
| Simulador de tarifas y capacidad | Mejor margen sin deteriorar el servicio |
| ETA con intervalo de confianza | Menor error y mejor comunicación |
| Reasignación preventiva | Menos pedidos vencidos |
| Planificación de demanda | Menos espera y cobertura más equilibrada |
| Liquidación transparente | Comercio y rider pueden explicar cada diferencia |
| Soporte con contexto completo | Menor tiempo de resolución |
| Operación con mala conectividad | Menos entregas interrumpidas |
| Detección de anomalías | Menor fraude con revisión humana |
| Medición de eficiencia | Menos kilómetros por entrega comparable |

Para usar ML primero deben existir eventos consistentes, datos suficientes y una referencia de comparación. De lo contrario, solo se añade complejidad.

**Criterio de cierre:** mejora medida en piloto y después en operación, sin degradar seguridad, equidad o rentabilidad.

## 21. Fase P — Preparación real para producción

Comienza con la estabilización y acompaña todas las fases.

### Infraestructura y despliegue

- Separar desarrollo, staging y producción.
- Eliminar dependencias operativas de --reload y montajes de desarrollo.
- Proteger BD y Redis.
- Configurar secretos fuera del repositorio.
- Desplegar workers y scheduler efectivamente utilizados.
- Evitar ejecuciones duplicadas entre instancias.
- Crear los artefactos de infraestructura que CI referencia.
- Usar imágenes y versiones identificables.

### Confiabilidad

- Persistir eventos antes de entregarlos a procesos externos.
- Reintentos idempotentes.
- Bandeja de fallos.
- Recuperación de operaciones interrumpidas.
- Health checks correctos.
- Respaldo y restauración ensayada.
- Migraciones compatibles con despliegues.
- Procedimiento de rollback.

### Observabilidad

- Métricas reales.
- Logs sin tokens ni documentación personal.
- Trazabilidad entre pedido, entrega, pago y notificación.
- Alertas sobre operaciones atascadas.
- Detección de diferencias financieras.
- Visibilidad de colas y proveedores.

### Calidad

- Compilación y tipos aprobados.
- Pruebas de integración.
- Recorridos completos por rol.
- Pruebas negativas de permisos.
- Concurrencia financiera.
- Duplicación y desorden de webhooks.
- Reinicio durante operaciones.
- Carga representativa.
- Pruebas de conectividad móvil.

**Criterio de cierre:** el equipo puede desplegar, detectar una falla, recuperarse y explicar el estado del negocio sin depender de reparaciones manuales improvisadas.

Kubernetes, microservicios y sharding deben responder a una necesidad medida. No son requisitos automáticos para el primer lanzamiento.

## 22. Orden recomendado de ejecución

```mermaid
flowchart TD
    A[Fase 0: seguridad y contratos] --> B[7A: contabilidad]
    B --> C[7B: pagos reales]
    A --> D[8: despacho y tracking]
    A --> E[9A: notificaciones]
    D --> F[9B: app rider]
    B --> G[10: fiscalidad y FX]
    A --> H[11: comercios y catálogo]
    H --> I[12: cliente y compras]
    C --> I
    D --> I
    E --> I
    H --> G
    I --> J[13: soporte y devoluciones]
    J --> K[14: verticales]
    C --> L[15: movilidad]
    D --> L
    F --> L
    J --> L
    I --> M[16: empresas y API]
    I --> N[17: fidelización y publicidad]
    M --> O[18: ecosistema]
    K --> P[19: diferenciación medible]
    L --> P
    N --> P
    Q[Fase P: producción y recuperación] -. transversal .-> A
    Q -. transversal .-> I
    Q -. transversal .-> L
```

El gráfico expresa dependencias principales, no una obligación de esperar al final para iniciar soporte. Soporte, fiscalidad e infraestructura deben trabajarse antes del lanzamiento de los productos que los requieren, aunque su integración se cierre después. La fase P aplica a todas las fases, no solo a los nodos dibujados.

### Liberaciones recomendadas

| Liberación | Alcance | Requisito |
|---|---|---|
| L1: piloto logístico | Pedidos y entregas administrados por operadores | Seguridad, dinero, tracking y operación estabilizados |
| L2: delivery comercial | Clientes compran a comercios | Catálogo, checkout, pagos, soporte y liquidación |
| L3: múltiples verticales y empresas | Retail, supermercado, paquetería y B2B | Reglas específicas y aislamiento |
| L4: movilidad | Transporte de pasajeros | Producto y operación de viajes completos |
| L5: ecosistema y diferenciación | Fidelización, publicidad y servicios adicionales | Datos y procesos consolidados |

## 23. Qué exigir para autorizar cada lanzamiento

No se utilizará una puntuación global como “92/100”. Se requiere evidencia por capacidad.

| Puerta de salida | Evidencia mínima |
|---|---|
| Seguridad | Sin defectos críticos abiertos en el alcance publicado; permisos negativos aprobados |
| Dinero | Conciliación explicable; idempotencia y concurrencia verificadas |
| Funcionalidad | Recorrido completo y excepciones aprobados |
| Integraciones | Confirmación real del proveedor; simulaciones claramente separadas |
| Calidad | CI, tipos, pruebas y build aprobados |
| Operación | Alertas, soporte y recuperación ensayados |
| Datos | Migraciones y restauración verificadas |
| Capacidad | Carga objetivo validada con margen acordado |
| Experiencia | Uso real validado con clientes, comercios y repartidores |
| País habilitado | Requisitos comerciales, fiscales y operativos del servicio revisados |

Como propuesta inicial, deben definirse objetivos de disponibilidad, frescura GPS, error de ETA, recuperación y conciliación. Sus valores se acuerdan según mercado y capacidad operativa; las cifras del roadmap no se consideran compromisos ya alcanzados.

La prioridad inmediata es la fase 0 y la consolidación contable 7A. Después conviene cerrar un primer circuito de producción logística y comercial antes de ampliar a movilidad y al resto del ecosistema.

## Estado de implementación de este documento

Todas las fases descritas son propuestas pendientes de ejecución o consolidación; el estado de cada módulo existente se detalla en sus secciones. No se marca ninguna mejora como completada por la mera creación de este archivo.

Esta entrega crea exclusivamente Implementacion_de_mejoras_V1.md. No actualiza el roadmap histórico, la comparación ni el código. No realiza commit, push, despliegue ni migración.


## Registro de avance — Fase 0, bloque 1 — 24 de octubre de 2026

**Estado:** implementación local del primer bloque; la fase 0 y el resto del plan siguen parciales. Esta sección actualiza el estado histórico de propuesta indicado al inicio del documento. La publicación se registra en el commit/PR correspondiente.

### Cambios de este bloque

- Política compartida para lectura y escritura de pedidos y entregas: personal operativo, auditor de solo lectura y repartidor asignado. CLIENTE no hereda acceso operativo sin relación de propiedad implementada.
- Comprobación de propietario antes de delegar el cierre legacy de una entrega. Se incluye delivery_id al construir ProofOfDeliveryCreate.
- Protección de tier, vehicle_ownership_type y assigned_vehicle_id en ambas rutas de actualización de rider; solo GERENTE y SUPERADMIN pueden modificarlos.
- Rechazo de reapertura de estados terminales mediante el endpoint de estado y rechazo de actualizaciones GPS fuera de entregas en curso.
- OTP obligatorio cuando existe un secreto o el tipo de prueba es OTP. Se aplica en el servicio de cierre, el endpoint unificado y el cierre alternativo desde pedidos. Las entregas sin OTP configurado conservan su flujo.
- Estadísticas de pedidos filtradas al rider autenticado cuando corresponde.
- El caché HTTP omite rutas /api/, peticiones con Authorization y peticiones con cookies; las respuestas API ejecutan siempre sus dependencias. Se corrige la doble deserialización del hit público.
- Corrección de siete errores de TypeScript, declaración de componente cliente para notificaciones, límites Suspense en login/restablecimiento y carga exclusivamente en navegador de páginas de mapas que importan Leaflet.
- Jest utiliza el preset JSX/TypeScript de Next. La prueba de teléfono usa el schema real del formulario, extraído sin cambiar sus reglas.
- Los archivos de registro creados por pruebas se aíslan en directorios temporales. La fixture de notificaciones no depende del caché Redis externo.

### Verificación

Comandos desde backend:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```

Comandos desde frontend:

```bash
npx tsc --noEmit --incremental false
npm test -- --runInBand --watchAll=false
NEXT_TELEMETRY_DISABLED=1 npm run build
```

Resultados locales del bloque: 186 pruebas backend, 21 pruebas frontend, comprobación TypeScript y build de producción. La suite backend conserva advertencias anteriores de configuración pytest y relaciones SQLAlchemy; no se presentan como resueltas. Los tests de seguridad usan handlers HTTP reales y persistencia simulada, y los tests de auth existentes usan SQLite de prueba. No prueban concurrencia PostgreSQL ni un recorrido completo de navegador.

### Cambios de contrato deliberados

- CLIENTE recibe 403 en los endpoints operativos revisados; su futuro acceso requiere relaciones y endpoints de la fase 12.
- AUDITOR tiene lectura operativa, no mutación. La deriva del enum SQL de AUDITOR sigue pendiente de migración específica.
- Enviar campos administrativos de rider sin permiso devuelve 403, incluso si se envía null; no se ignoran silenciosamente.
- El cierre de pedido admite otp_code opcional como query; se exige cuando la entrega tiene OTP configurado.
- Un estado terminal no se reabre mediante PATCH de estado. No se añade aquí un proceso administrativo de reversión.

### Pendientes que este bloque no resuelve

- Atomicidad integral de entrega, pedido y contabilidad; bloqueo concurrente e idempotencia de todos los circuitos de dinero.
- Unificación de los libros financieros, pagos reales, wallet alternativa y conciliación.
- Privacidad y migración de documentos actualmente servidos desde uploads; requiere coordinar acceso frontend y almacenamiento.
- Autorización de tracking/canales WebSocket, lifecycle y sesiones/MFA.
- IVA incluido, FX, facturación real, numeración fiscal y durabilidad de hooks.
- Workers, migraciones de deriva ORM/BD y despliegue/observabilidad completos.
- Cobertura funcional exhaustiva, pruebas de carga, restauración y validación productiva.

No se realizan migraciones, pagos reales ni despliegues con este bloque. La compilación y las pruebas aprobadas no equivalen a certificación de producción de todas las capacidades.


### Resultado del CI remoto del primer bloque

El [PR #243](https://github.com/corporacionbethelst-ux/Delivery_360-DEV/pull/243) publica este bloque en `fix/fase0-permisos-entregas`. La [ejecución 40103131774](https://github.com/corporacionbethelst-ux/Delivery_360-DEV/actions/runs/40103131774) detectó bloqueos en controles previos a las pruebas:

| Job | Bloqueo observado | Trabajo siguiente |
|---|---|---|
| backend-test | Flake8 F821: FastApiIntegration, SqlalchemyIntegration, RedisIntegration y CeleryIntegration sin definir en app/monitoring/sentry_config.py | Revisar y corregir imports y disponibilidad opcional del SDK; después ejecutar formato y tipos, que este job todavía no alcanzó |
| frontend-test | next lint solicita configurar ESLint y termina con código 1 | Declarar configuración y dependencias compatibles, ejecutar reglas y corregir los hallazgos antes de continuar los checks |
| security-scan | Los dos uploads SARIF de Trivy usan la misma categoría y el segundo es rechazado | Asignar categorías distintas a backend/frontend y actualizar la acción upload-sarif obsoleta |

Los archivos Sentry y workflow no se modificaron en este bloque; la configuración ESLint ya estaba ausente en la base revisada. Los fallos se identifican como deuda previa, no como una aprobación del pipeline. En esa ejecución las pruebas y el build remotos quedaron omitidos al fallar los pasos previos. Los 186 tests backend, 21 frontend, TypeScript y build indicados arriba son resultados locales.

**Integración a main pendiente:** no se fusiona este bloque mientras esos controles estén en rojo. La siguiente tarea de estabilización es corregir los bloqueos del pipeline y atender los resultados de formato/tipos que aparezcan, conservando los controles en lugar de deshabilitarlos. No se declara que el CI completo esté aprobado.

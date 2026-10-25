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


## Registro de avance — Fase 0 / CI, bloque 2 — 24 de octubre de 2026

**Base:** `c23cb90`, que ya incorpora el PR #243. Esta continuación se desarrolla en `fix/ci-quality-v1`; no modifica la historia del PR anterior.

### Correcciones implementadas

- Sentry: imports reales de FastAPI, SQLAlchemy, Redis y Celery; SDK declarado como dependencia de runtime y nivel de mensaje tipado según su contrato. Ocho pruebas nuevas verifican el caso sin DSN, la configuración y el envío delegado de niveles, sin transmitir eventos externos. No se activa Sentry en main.py como parte de este bloque.
- ESLint: configuración explícita `next/core-web-vitals`; se corrigen 15 comillas sin escapar en JSX preservando el texto mostrado y se mueve el hook condicional de NotificationBell antes del retorno. Tres pruebas nuevas cubren apertura, carga de inbox y acciones de lectura.
- Tipos de pruebas: `@types/jest` sustituye las declaraciones globales mínimas con any. El lockfile mantiene las versiones de las dependencias existentes; solo incorpora tipos de desarrollo necesarios.
- SARIF: categorías distintas `trivy-backend` / `trivy-frontend`, permisos explícitos y actualización de upload-sarif a v3.
- Pipeline: herramientas Python fijadas en requirements-dev.txt. Flake8, Black, mypy y pruebas permanecen activos. Se separan los pasos y las comprobaciones posteriores se ejecutan cuando las dependencias se instalaron, incluso si falló un control anterior; el job sigue fallando si cualquiera de ellos falla. Los builds/publicaciones conservan su dependencia de jobs aprobados.
- Formato: commit separado que aplica Black a 143 archivos restantes; equivalencia AST comprobada en los 154 archivos Python de app y suite repetida después. No se alteran reglas de negocio en ese commit.
- Los reportes coverage/ del frontend se excluyen de Git como artefactos generados.

### Resultados locales

| Control | Resultado |
|---|---|
| Flake8: E9,F63,F7,F82 sobre app | Aprobado, 0 hallazgos |
| Black sobre app | Aprobado, 154 archivos sin cambios pendientes |
| mypy de sentry_config.py, con imports seguidos en modo silent | Aprobado en el módulo corregido; no acredita el resto de app |
| pytest desde backend | 194 aprobadas; cuatro advertencias previas de pytest/ORM |
| ESLint | Aprobado con advertencias previas; reglas conservadas |
| TypeScript | Aprobado sin el stub de globals any |
| Jest sin cobertura | 24 pruebas aprobadas |
| Build Next.js | Aprobado |
| Workflow YAML | Parseado y verificadas categorías distintas y conservación de controles |
| pip check | Sin dependencias incompatibles |
| git diff --check | Aprobado |

### Bloqueos reales que continúan abiertos

**El CI completo todavía no se considera aprobado.** Al ejecutar todos los controles se confirmó deuda que antes quedaba oculta por pasos anteriores:

1. `mypy app --ignore-missing-imports`: 785 errores en 72 archivos con la herramienta fijada. El diagnóstico inicial era 788; se resolvieron cinco de Sentry y el cambio de líneas del formateador hace visibles dos diagnósticos adicionales de expresiones que ya existían. La comprobación de equivalencia AST confirma que el commit de formato no cambió su lógica. Incluye discrepancias ORM/SQLAlchemy, atributos y enums inexistentes y contratos sync/async. Requiere correcciones tipadas por módulo y pruebas; no se oculta con Any ni ignores generales.
2. Jest con cobertura: las 24 pruebas pasan, pero el mínimo global del 50 % no se cumple. Cobertura medida: statements 0,42 %, branches 0,44 %, functions 0,53 %, lines 0,46 %. El baseline anterior a las pruebas de campana era 0,01 % de líneas. Los umbrales permanecen intactos: el comando debe fallar mientras no se añada cobertura suficiente.

Los porcentajes bajos reflejan el alcance real de pruebas existentes sobre toda la aplicación, no una regresión causada por las correcciones. Los siguientes bloques deben ampliar pruebas funcionales de servicios, stores, hooks, componentes y recorridos, y corregir contratos de tipos priorizando las rutas activas y el dinero. No se declarará la preparación de producción ni se fusionará este bloque por el solo hecho de que compilen sus cambios.

No se ejecutan migraciones, pagos ni despliegues con esta continuación. Los cambios funcionales y de formato se mantienen en commits separados para facilitar revisión y reversión.


## Registro de avance — Fase 0 / Contratos ORM y wallet, bloque 3 — 24 de octubre de 2026

**Base:** `66e8ac2`, que ya incorpora el PR #244. Rama: `fix/orm-wallet-contracts-v1`.

### Problemas verificados y correcciones

1. **Wallet incompatible con la sesión real.** `get_db` entrega `AsyncSession`, pero WalletService utilizaba `query`, `commit` y `refresh` síncronos. Las operaciones se convierten a consultas y escrituras asíncronas. Saldo y movimiento/solicitud se confirman juntos; ante un error se revierte la transacción completa.
2. **Rol e identificación del repartidor incorrectos.** La API referenciaba `UserRole.RIDER`, inexistente, y podía utilizar users.id como riders.id. Ahora exige `REPARTIDOR`, consulta explícitamente el perfil por user_id y responde 404 si falta. Comparte las dependencias de autenticación y autorización de la API principal, sin acceder a relaciones ORM de carga diferida para resolver el perfil.
3. **Concurrencia y reintentos.** Se bloquea la fila de wallet antes de modificar saldo; la creación bloquea primero su repartidor padre. Las transiciones bloquean la solicitud y el rechazo bloquea además la wallet para reintegrar una sola vez. `populate_existing` refresca los valores tras adquirir el bloqueo, incluso si la sesión ya conservaba una instancia antigua. La clave de idempotencia verifica la identidad completa de la operación; una reutilización incompatible devuelve conflicto y no altera saldo. Los conflictos de la restricción única global se resuelven después de revertir la escritura perdedora.
4. **Validación monetaria.** Se rechazan montos no enteros, booleanos, cero, negativos, desbordamientos de INTEGER, sobregiros y operaciones nuevas sobre wallets inactivas. La solicitud HTTP admite una clave opcional de idempotencia; las llamadas anteriores sin clave siguen siendo válidas, pero no tienen protección frente a reintentos del cliente. La metadata de movimientos se serializa como JSON válido.
5. **Estados incompatibles en el frontend.** El backend de `/payouts` usa seis estados canónicos, pero el adaptador solo aceptaba cuatro estados anteriores. Ahora acepta `APROBADO`, `EN_PROCESO`, `COMPLETADO` y `FALLIDO`, y las pantallas los presentan explícitamente. Se conservan `PROCESADO` y `CANCELADO` para respuestas históricas. Aprobar conserva el estado `EN_PROCESO` devuelto por el backend; el indicador de completados cuenta `COMPLETADO`. No se interpreta una aprobación como confirmación de transferencia bancaria. Se rechazan importes no finitos en solicitudes y respuestas del adaptador.
6. **Contratos ORM tipados.** User y los cuatro modelos financieros de financial.py declaran `Mapped`/`mapped_column` con UUID, Decimal, enums y nulabilidad reales. Se preserva el DDL de PostgreSQL, incluidos índices, claves, defaults y valores de enums: una instantánea tomada antes del cambio se compara mediante prueba automatizada. No se modifica el esquema ni se añade una migración. Los CRUD materializan las listas declaradas y adaptan UUID al contrato textual del servicio contable existente.
7. **Autenticación.** Se retiran impresiones de fragmentos de token, payload y datos personales. Los subjects ausentes, no textuales o UUID inválidos se rechazan con 401; las cuentas heredadas sin rol no provocan errores 500 ni reciben tokens. Se reutilizan los esquemas de recuperación ya existentes y se eliminan alias iniciales nulos de dependencias que posteriormente tenían implementación real.

### Validación local

| Control | Resultado |
|---|---|
| pytest, suite completa | **225 aprobadas**, frente a 194 de la base; cuatro advertencias anteriores |
| Persistencia / HTTP | Pruebas de saldo e historial firmado, reintentos, conflictos, rollback, sobregiro, desbordamiento, wallet inactiva, reserva/reintegro, estados, permisos y separación user/rider |
| Concurrencia real PostgreSQL 16 | **7 aprobadas**: débitos simultáneos, clave repetida en la misma wallet y entre wallets, reservas/rechazos simultáneos, saldo obsoleto en sesión, creación simultánea y reintentos de solicitud |
| Aislamiento de pruebas PostgreSQL | Contenedor local desechable; esquema privado por prueba; solo TEST_DATABASE_URL explícita con nombre test_*; limpieza al terminar; sin fallback a DATABASE_URL |
| Contrato de tablas | Comparación exacta del DDL ORM PostgreSQL, índices, defaults y enums de las cinco tablas afectadas |
| Flake8 E9,F63,F7,F82 | 0 hallazgos |
| Black sobre app | 154 archivos aprobados |
| mypy global | **629 diagnósticos en 66 archivos**, frente a 785 en 72; el control todavía falla |
| Jest | **53 aprobadas**, frente a 24; 29 nuevas sobre el adaptador de retiros |
| Cobertura global Jest | Statements 1,19 %, branches 1,45 %, functions 0,97 %, lines 1,23 %; el mínimo del 50 % sigue incumplido |
| TypeScript / ESLint / build Next.js | Aprobados; ESLint conserva advertencias anteriores |
| git diff --check | Aprobado |

El workflow proporciona TEST_DATABASE_URL sobre su servicio PostgreSQL de pruebas para ejecutar las siete verificaciones de concurrencia. Sin esa variable, estas pruebas se omiten explícitamente: SQLite no demuestra bloqueos de filas. Se usa NullPool únicamente en esas pruebas para no compartir conexiones asyncpg entre bucles de pytest/TestClient; el pool de producción no cambia.

### Límites y trabajo que continúa pendiente

- **Este bloque no completa la fase financiera ni certifica producción.** El subsistema alternativo `rider_wallets/financial_transactions/payout_requests` sigue separado de `financials/payouts` y de `riders.wallet_balance`. No se consolidan ni se reconcilian saldos automáticamente. Sus reservas se representan por solicitudes; este bloque no añade asientos contables de reserva/reintegro a ese historial.
- Las acciones administrativas de aprobar/completar de la wallet mantienen su contrato manual: no envían dinero ni prueban que un banco lo haya transferido. Pendientes: proveedor real, webhooks verificados, conciliación, auditoría de actores y contabilidad unificada.
- Deben revisarse estados y callbacks del circuito principal `/payouts`, sus reglas de disponibilidad y la recuperación de fallos; corregir el adaptador visual no acredita todo ese flujo. Las estadísticas mensuales siguen dependiendo de las fechas que suministra ese contrato.
- La comparación DDL acredita equivalencia entre los modelos antes y después, **no** que una instalación tenga todas sus migraciones aplicadas ni que los enums físicos coincidan con el código actual. Las pruebas PostgreSQL crean únicamente las tablas necesarias; no sustituyen pruebas de migración y actualización desde una instalación histórica.
- El nuevo tipado también hace visibles defectos anteriores: roles/timestamps anulables que otros consumidores asumen completos y contratos UUID declarados como int o Column. No se ocultan con Any, casts ni ignores generales. Los 629 diagnósticos restantes requieren corrección por módulos y pruebas.
- La idempotencia de clientes debe conservar una misma clave cuando reintenta una misma operación. La generación de una clave nueva en cada nueva llamada del adaptador principal no sustituye ese comportamiento de la interfaz; sigue pendiente su integración completa. Los registros antiguos con metadata serializada de otra forma pueden generar conflicto conservador al reutilizar claves.
- Quedan pendientes cobertura global del 50 %, recorridos completos, carga, observabilidad, restauración, secretos y los siguientes bloques del plan. No se reducen umbrales ni se desactivan controles para presentar una aprobación artificial.

**Publicación:** rama y PR de revisión; no se fusiona ni se despliega este bloque mientras continúen los bloqueos globales de tipos/cobertura. No se ejecutan migraciones ni movimientos monetarios reales.


## Registro de avance — Conciliación segura y reportes, bloque 4 — 24 de octubre de 2026

**Base:** `831ee40`, fusión del PR #245. Rama: `fix/financial-report-contracts-v1`. Por instrucción del propietario, el siguiente PR se publica **sin borrador**, listo para revisión; ese estado no equivale a aprobación de los controles ni a certificación de producción.

### Hallazgos corregidos

- **dry_run ignorado:** `/reconciliation/fix-all-discrepancies` llamaba al servicio que escribía incluso con dry_run=True. Ahora la vista previa no modifica caché, versión ni ledger. Informa discrepancy_count y total_discrepancy_amount; fixed_count y total_adjusted_amount permanecen en cero durante la simulación.
- **GET con efectos monetarios:** GET `/reconciliation/wallet/{rider_id}` pasa a ser estrictamente informativo. Para sincronizar la caché existe POST `/reconciliation/wallet/{rider_id}/sync`, exclusivo de SUPERADMIN y con dry_run=True por defecto; la escritura exige dry_run=false. No se invoca contra datos productivos durante este trabajo.
- **Asientos artificiales de conciliación:** una discrepancia de caché generaba un AJUSTE_MANUAL, que además tiene dirección de débito en el ledger canónico. Esto podía cambiar la fuente usada para conciliar y dejar saldos incoherentes tras repetir la operación. Ahora la aplicación explícita sincroniza únicamente riders.wallet_balance con el saldo del ledger y aumenta su versión; no fabrica ingresos, retiros ni ajustes contables. Se usa bloqueo de fila y rollback si falla el guardado.
- **Control de versión no atómico:** la comprobación de versión y su escritura eran pasos separados. Se sustituyen por UPDATE condicionado por la versión esperada, con incremento SQL y RETURNING. Dos solicitudes con la misma versión no pueden ganar ambas. El método participa en la transacción del llamador y no confirma por su cuenta.
- **Fuente de saldo:** el último snapshot se restringe a movimientos procesados/pagados; una fila pendiente o rechazada no puede sustituirlo. En el fallback de snapshots históricos nulos, AJUSTE_MANUAL deja de contarse simultáneamente como débito y ajuste. AJUSTE conserva su signo.
- **Permisos y consultas:** las rutas de conciliación pasaban listas a require_role, cuyo contrato real recibe roles separados. Se corrige el contrato. El informe diario consulta nombres sin relaciones de carga diferida; las fechas históricas se rechazan explícitamente, porque comparar la caché actual bajo una fecha antigua producía un informe engañoso. Los UUID de las rutas se validan antes de consultar.
- **Liquidación diaria:** row.count identificaba el método de la fila, no el agregado SQL llamado count. Se lee la columna por su mapping; el resultado contiene un entero incluso cuando no hay movimientos.
- **Importe mostrado de órdenes:** si faltaba subtotal y había artículos y envío, el cálculo podía devolver solamente el envío. Ahora considera los artículos antes de usar únicamente la tarifa. Se mantienen la prioridad de totales explícitos y la prevención de doble suma.
- **Paginación del frontend financiero:** límites negativos, cero, fraccionarios y no finitos se normalizan a límites válidos en historial, desglose y reporte de órdenes. Los fallos del servidor siguen propagándose; no se sustituyen por reportes ficticios.

### Validación

| Control | Resultado local |
|---|---|
| Suite backend completa con PostgreSQL aislado | **237 aprobadas**, 12 nuevas frente a la base; cuatro advertencias anteriores |
| Concurrencia nueva en PostgreSQL | Dos pruebas aprobadas: compare-and-swap con un solo ganador y sincronizaciones repetidas sin asientos ni versiones duplicadas |
| Pruebas nuevas de persistencia / HTTP | Vista previa sin escrituras, aplicación sin alterar ledger, reintento, rollback, tolerancia de un centavo, perfil ausente, permisos, lote, fechas históricas, estados no procesados, fallback histórico y conteo de liquidación |
| Jest | **75 aprobadas**, 22 nuevas frente a la base |
| TypeScript / ESLint / build Next.js | Aprobados; advertencias anteriores de ESLint conservadas |
| Mypy global | **613 diagnósticos en 64 archivos**, frente a 629 en 66; sin diagnósticos en financial_service.py ni reconciliation.py en esta ejecución |
| Cobertura frontend global | Statements 2,16 %, branches 2,33 %, functions 1,50 %, lines 2,12 %; umbral global del 50 % todavía incumplido |
| Flake8 / Black / git diff --check | Aprobados |

La ejecución remota del bloque anterior [40108519477](https://github.com/corporacionbethelst-ux/Delivery_360-DEV/actions/runs/40108519477) confirmó pruebas backend y build aprobados, así como ejecución del análisis de seguridad. Los jobs globales fallaron en mypy y cobertura, tal como se había informado. Este bloque conserva todos esos controles.

### Límites y compatibilidad que deben revisarse

- **Cambio intencional de contrato:** GET ya no corrige saldos. Los consumidores que dependieran de esa escritura deben pasar al POST explícito. La simulación informa `discrepancy` donde antes el servicio podía devolver `reconciled` después de escribir. Se conservan los campos monetarios y se añaden dry_run/message e indicadores de discrepancias.
- La tolerancia previa de un centavo se mantiene. El lote confirma cada repartidor de forma independiente, informa fallos y no promete atomicidad global. La acción de sincronizar caché sigue requiriendo auditoría durable del actor antes de considerarse cerrada toda la fase financiera.
- Las pruebas demuestran coordinación entre sincronizaciones y actualizaciones con el nuevo control de versión, **no** que todos los escritores del ledger utilicen el mismo bloqueo ni que todos sus snapshots históricos sean correctos. La serialización global de asientos, revisión de snapshots, idempotencia del ledger principal y consolidación de los dos subsistemas financieros siguen pendientes.
- El auditor existente informa balances ausentes y distribución por tipo; se corrige su descripción para que no afirme verificar continuidad ni aritmética completa de saldos. Esa auditoría completa continúa pendiente.
- El cálculo de importe de orden es de presentación; no confirma cobros, modalidad de pago ni liquidación bancaria. Los reportes fiscales, moneda, carga, cobertura completa y recorridos de usuario requieren sus propios siguientes bloques.
- No se cambia el esquema, no se aplican migraciones, no se ejecutan conciliaciones sobre datos de negocio, no se envía dinero y no se despliega. **El PR se publica listo para revisión por petición del usuario, con los bloqueos globales informados y sin desactivar controles.**


## Registro de avance — Validación de sesiones y acceso al panel, bloque 5 — 24 de octubre de 2026

**Base:** `b6b05b8`, fusión del PR #246. Rama: `fix/session-validation-v1`. Publicación sin borrador por instrucción del propietario.

### Fallos verificados y cambios

1. **Suspensión sin efecto sobre tokens existentes.** El login comprobaba el perfil del repartidor, pero refresh y las dependencias de acceso solo validaban el usuario. Una cuenta con usuario activo y repartidor suspendido podía renovar y seguir utilizando tokens. La política compartida verifica el estado actual del perfil en login, refresh y las dos dependencias de acceso existentes. PENDIENTE, INACTIVO, SUSPENDIDO y perfil ausente reciben 403. ACTIVO y OCUPADO conservan acceso; estar realizando una entrega no equivale a una suspensión. Usuarios inactivos o sin rol siguen rechazándose.
2. **Autenticación basada en caché del navegador.** checkAuth promovía el perfil guardado a sesión autenticada antes de obtener el perfil del servidor, y Zustand rehidrataba isAuthenticated. Ahora los datos persistidos no acreditan autenticación: se ignoran al rehidratar y la sesión se habilita solo después de verificar un perfil activo con rol reconocido.
3. **Respuestas tardías después del cierre.** Se incorpora una revisión de operación para impedir que una respuesta de login o perfil obsoleta restaure la sesión o borre una sesión nueva. forceLogout invalida operaciones pendientes. El cierre local es inmediato aunque el servidor tarde o falle.
4. **Validación antes de montar páginas.** SessionGate verifica la sesión al entrar al dashboard y muestra un estado de espera. No monta las páginas protegidas ni sus consultas mientras espera. Una sesión inválida redirige a login. Se elimina una verificación redundante del resumen financiero para evitar un ciclo de montaje/validación.
5. **Limpieza excesiva por versión.** Se sustituye localStorage.clear por limpieza de credenciales y claves de autenticación propias. Se conservan preferencias ajenas a autenticación. Un login nuevo registra la versión actual, evitando que la siguiente verificación borre una sesión recién iniciada.
6. **Rotación de tokens y errores.** La cookie de navegación usa el token que queda almacenado tras validar el perfil, para no restaurar uno anterior si hubo renovación. Los errores del store se manejan como unknown, sin registrar su contenido completo.

### Verificación local

| Control | Resultado |
|---|---|
| Backend completo, PostgreSQL de pruebas configurado | **244 aprobadas**, incluidas las nueve pruebas anteriores de concurrencia; cuatro advertencias previas |
| Nuevas pruebas backend | Siete casos: cuatro estados/perfil ausente rechazados en acceso, refresh y login; ACTIVO/OCUPADO aceptados; suspensión posterior a emisión de tokens |
| Frontend completo | **92 aprobadas**, 17 nuevas frente a la base |
| Store | Login validado, perfil cacheado sin confianza, respuestas tardías, sesión nueva protegida frente a fallo antiguo, cambio de versión sin borrar preferencias, ausencia de tokens, perfil inactivo, fallo de verificación, cierre inmediato, rehidratación manipulada y cookie con token renovado |
| SessionGate | Contenido bloqueado hasta verificar, redirección en sesión inválida y retirada de contenido al cerrar sesión |
| Mypy global | **613 diagnósticos en 64 archivos**, igual que la base; nuevo módulo session_policy.py sin diagnósticos |
| Cobertura Jest | Statements 3,22 %, branches 2,95 %, functions 2,24 %, lines 3,20 %; todavía no alcanza el mínimo global del 50 % |
| Flake8 / Black | Aprobados, 155 archivos de app formateados |
| TypeScript / ESLint / compilación | Aprobados; TypeScript repetido después del build para evitar competir por archivos generados de Next.js; advertencias anteriores de ESLint conservadas |
| git diff --check | Aprobado |

La ejecución remota anterior [40109567159](https://github.com/corporacionbethelst-ux/Delivery_360-DEV/actions/runs/40109567159) terminó con los bloqueos conocidos de mypy y cobertura; los pasos de pruebas backend y build fueron aprobados. Se mantienen controles y umbrales.

### Límites y siguientes pendientes

- Esta política actúa en las rutas que usan las dependencias HTTP corregidas. No acredita por sí sola la autorización de WebSockets, procesos en segundo plano ni módulos de autenticación alternativos. Se debe completar ese inventario.
- El logout continúa siendo cierre local; **no añade revocación centralizada de JWT**. Tokens copiados siguen sujetos a firma, vencimiento y validación del estado de cuenta en cada petición. Quedan pendientes revocación, rotación con detección de reutilización y gestión de sesiones por dispositivo.
- Se conserva el mecanismo existente de tokens accesibles desde JavaScript y cookies de navegación. SessionGate y las cookies no son una frontera de autorización; el backend sigue siendo responsable de comprobar cada operación. La migración a cookies HttpOnly/Secure y su protección CSRF requiere un bloque propio y pruebas de integración.
- El perfil puede guardarse como metadata de presentación, pero no se usa como prueba de autenticación. Las preferencias ajenas a autenticación se mantienen al cambiar de versión.
- El control verifica el estado cuando se solicita acceso o renovación; no promete desconectar activamente conexiones ya abiertas ni reaccionar en todas las pestañas sin una nueva petición.
- No se cambia el esquema, no se aplican migraciones, no se hacen pagos, no se modifica la política de CI ni se despliega. Se publica PR listo para revisión; **tipos y cobertura global siguen pendientes**.


## Registro de avance — Integridad de asientos y límites transaccionales, bloque 6 — 24 de octubre de 2026

**Base:** `bae9659`, fusión del PR #247. Rama: `fix/ledger-integrity-v1`. Publicación sin borrador, conservando controles y límites pendientes.

### Hallazgos corregidos

1. **Idempotencia sin comprobar identidad.** El servicio devolvía cualquier asiento que tuviera la misma clave, aunque el nuevo importe, repartidor o concepto fueran distintos. Ahora compara repartidor, monto normalizado, tipo, estado, descripción, referencia, origen y actor. Un reintento equivalente devuelve el mismo asiento; una reutilización incompatible devuelve conflicto 409. Se rechazan claves suministradas vacías o demasiado largas. Sin clave, dos llamadas siguen siendo operaciones diferentes.
2. **Snapshots simultáneos incompatibles.** Dos escrituras podían leer el mismo saldo previo. El servicio bloquea la fila padre del repartidor antes de leer y calcular el saldo. El asiento y sus snapshots se preparan bajo ese bloqueo. Esto también coordina el servicio con la sincronización de caché del bloque 4, que bloquea el mismo padre.
3. **Colisión global de claves.** Una clave puede competir entre repartidores distintos aunque cada uno tenga su bloqueo. El insert usa un savepoint: una violación de unicidad revierte el insert perdedor y permite comprobar la identidad del ganador sin dejar inutilizada la sesión. commit=False conserva la transacción y el commit en manos del llamador; commit=True revierte ante un fallo.
4. **Montos/snapshots fuera de contrato.** Se rechazan NaN, infinitos, booleanos, cero después del redondeo y valores fuera de NUMERIC(10,2). El saldo inicial opcional debe coincidir con el saldo real al adquirir el bloqueo y debe ser finito. Se preservan las reglas previas de dirección de créditos, débitos y AJUSTE firmado, así como el redondeo monetario existente.
5. **Orden temporal ambiguo.** El lector usa created_at/id para elegir el último snapshot. Se garantiza orden creciente de los nuevos asientos por repartidor aun con timestamps iguales o pequeños retrocesos del reloj. Si el historial se adelanta más de cinco segundos al reloj actual, se rechaza la escritura y se pide revisar su cronología; no se desplazan nuevas operaciones a otro período por arrastrar una fecha futura corrupta.
6. **Saldo disponible confundido con saldo contable.** La aprobación de un payout pasaba al ledger un saldo que ya descontaba otras reservas. Ahora el payout conserva su snapshot de disponibilidad, pero el asiento deriva el saldo contable bajo su propio bloqueo. Prueba concreta: con saldo 100, retiro 30 y otra reserva 20, el payout registra disponibilidad 80→50 y el ledger saldo contable 100→70. La reserva ajena no se convierte en un débito contable adicional.
7. **Notificaciones que confirmaban antes de terminar.** Aprobar y rechazar invocaban NotificationService dentro de la transacción; ese servicio hace commits internos y además recibía riders.id como user_id. Se retiran esas llamadas duplicadas. Se conservan los hooks omnicanal existentes, posteriores al commit y con sesión propia. Las pruebas verifican un solo commit de negocio y rollback de estado, historial y ledger si falla la confirmación final.
8. **Conflictos de dominio convertidos en 500.** Se registra AppException con su código de estado y mensaje público; una clave incompatible produce 409 en lugar de un error interno genérico.
9. **Frontend convertía importes defectuosos en cero.** El adaptador de transacciones valida números finitos e identidad mínima, normaliza strings numéricos y snapshots, conserva ajustes negativos y admite snapshots ausentes. Un importe nulo, booleano, vacío o no finito genera un error visible en lugar de datos financieros ficticios.

### Validación local

| Control | Resultado |
|---|---|
| Backend completo | **275 aprobadas**, 31 nuevas frente a las 244 de la base; cuatro advertencias previas |
| PostgreSQL real aislado | Seis pruebas nuevas del ledger: saldos consecutivos, reintentos concurrentes, colisión de clave entre repartidores forzada con barrera, rollback del llamador, timestamps iguales/retroceso pequeño e historial fechado en el futuro |
| Persistencia / retiros | Identidad de operación, montos inválidos, snapshots explícitos, rollback, respuesta HTTP 409 y aprobación/rechazo sin commits tempranos; pruebas anteriores del servicio convertidas de stubs incompletos a filas reales |
| Total de pruebas PostgreSQL | 15, incluidas las nueve anteriores; conexión explícita a test_* y esquemas privados con limpieza |
| Frontend | **110 aprobadas**, 18 nuevas para el adaptador de transacciones |
| Mypy global | **606 diagnósticos en 64 archivos**, frente a 613; servicio financiero y manejador de dominio sin diagnósticos en esta ejecución |
| Cobertura frontend | Statements 3,77 %, branches 3,74 %, functions 2,51 %, lines 3,73 %; mínimo global del 50 % todavía incumplido |
| TypeScript / ESLint / build Next.js | Aprobados; advertencias anteriores de ESLint conservadas |
| Flake8 / Black / git diff --check | Aprobados |

La ejecución remota anterior [40113571917](https://github.com/corporacionbethelst-ux/Delivery_360-DEV/actions/runs/40113571917) terminó con los bloqueos conocidos de tipos y cobertura. No se cambia su exigencia ni se activa despliegue como parte de este bloque.

### Alcance real y siguientes pendientes

- La serialización protege las escrituras que pasan por FinancialService. Inserciones directas o cambios de estado de asientos existentes requieren inventario y adaptación; no se afirma que todo escritor del repositorio use ya ese protocolo.
- **No se certifica todo el circuito principal de retiros.** Su cálculo de disponibilidad, reservas simultáneas, estados terminales, deducciones, fallback de órdenes y notificaciones de creación necesitan el siguiente bloque con pruebas propias. El servicio contable conserva la posibilidad de balances negativos para la política de débitos/ajustes existente; este trabajo no equivale a una nueva regla universal de sobregiro.
- Los snapshots históricos y sus fechas no se reescriben ni se auditan por completo. El bloqueo rechaza cronología futura excesiva para revisión; no intenta repararla automáticamente. La tolerancia de cinco segundos se limita a ordenación técnica, no autoriza backdating de negocio.
- La identidad estricta puede revelar usos anteriores de una misma clave para operaciones diferentes o reintentos después de modificar el estado del asiento. Esos casos requieren resolver el contrato de origen, no sobrescribir el historial ni ignorar el conflicto.
- commit=False no confirma ni revierte por su cuenta toda la unidad externa. El llamador debe propagar el error y hacer rollback; get_db lo hace cuando falla una petición. Un savepoint no sustituye una transacción de negocio completa.
- Los hooks posteriores al commit usan el mecanismo anterior de tareas en memoria. No se añade outbox durable ni se garantiza entrega de notificaciones si el proceso termina. Los eventos Redis emitidos antes de la confirmación tampoco constituyen auditoría transaccional durable.
- El frontend conserva sus compatibilidades previas de tipos/estados y moneda; validar importes no acredita alineación completa de enums, contabilidad multimoneda ni cifras agregadas de todos los reportes.
- No se altera el esquema, no se aplican migraciones, no se ejecutan movimientos de negocio reales ni se despliega. Se mantienen pendientes 606 diagnósticos de tipos, cobertura global, conciliación completa y los siguientes bloques del plan.


## Registro de avance — Reservas y disponibilidad de retiros, bloque 7 — 24 de octubre de 2026

**Base:** `5214ca3`, fusión del PR #248. Rama: `fix/payout-reservations-v1`. Publicación sin borrador, sin modificar los controles globales pendientes.

### Correcciones implementadas

1. **Respaldo contable de disponibilidad.** El cálculo anterior sumaba créditos, ignoraba deducciones y podía recurrir al valor de órdenes entregadas sin asiento de ingreso. Ahora parte del saldo procesado/pagado del ledger y resta únicamente las reservas que todavía no tienen un débito correspondiente. Las deducciones y ajustes ya afectan ese saldo; no se inventa crédito retirable desde órdenes. Los saldos negativos no producen disponibilidad positiva.
2. **Estados que retenían/liberaban incorrectamente dinero.** PENDIENTE y APROBADO se consideran pendientes; EN_PROCESO y COMPLETADO continúan comprometidos. Un retiro sin asiento de débito sigue retenido, incluso completado, hasta conciliación. Si existe un RETIRO procesado/pagado del mismo repartidor, importe y referencia/origen de payout, no se descuenta dos veces. Los estados nulos históricos se retienen conservadoramente; una reserva de importe inválido bloquea el cálculo con 409 para revisión.
3. **Reservas simultáneas.** Solicitar, aprobar y rechazar coordinan su decisión mediante el bloqueo del repartidor padre usado también por el ledger. El saldo se comprueba después de adquirirlo. Las transiciones refrescan el estado del payout al bloquearlo, evitando aceptar una instancia obsoleta de la sesión. El snapshot de saldo liberado al rechazar se recalcula excluyendo esa reserva, en lugar de sumar su monto a un valor previamente limitado a cero.
4. **Reintentos e identidad de solicitud.** La misma clave solo devuelve la solicitud previa si coinciden usuario, repartidor, monto, método y últimos dígitos. Las reutilizaciones incompatibles devuelven 409. La restricción única global resuelve colisiones entre repartidores mediante rollback y consulta del registro ganador; no quedan historial ni reservas del perdedor.
5. **Validación de entrada.** El monto usa Decimal, máximo de NUMERIC(10,2) y hasta dos decimales. Se mantiene el mínimo de 10.00. Los últimos dígitos, cuando se proporcionan, deben ser cuatro números; las claves no pueden estar vacías. Booleanos, NaN y exceso de precisión se rechazan antes de escribir.
6. **Notificación aislada.** Se sustituye la llamada de notificación que compartía la sesión de creación del retiro por un registro de inbox en una sesión propia, lanzado después del commit. Un fallo de esa sesión no revierte ni confirma nuevamente el retiro. La notificación queda pendiente; este bloque no simula haberla entregado a un proveedor push.
7. **Lectura de enums antiguos.** El filtro compartido de estados contables compara su representación textual, evitando que una lectura de PROCESADO/PAGADO falle únicamente porque el enum físico antiguo no contiene PAGADO. Una prueba PostgreSQL crea esa variante en su esquema privado y verifica el saldo. Esto no añade etiquetas físicas ni habilita escrituras con estados inexistentes.
8. **Formulario de retiro.** Conserva una misma clave para reintentar el mismo importe/cuenta después de una respuesta incierta; cambia de intención al modificar esos datos. Valida sufijos incompletos. Se retiran promesas de depósito por ciclo/viernes que no estaban garantizadas por el backend; el usuario puede consultar el estado de su solicitud.

### Evidencia local

| Control | Resultado |
|---|---|
| Backend completo con PostgreSQL de pruebas | **295 aprobadas**, 20 nuevas frente a la base; cuatro advertencias anteriores |
| Total PostgreSQL | **23 pruebas**, ocho nuevas: competencia por saldo, reintentos, colisión global forzada, aprobación/solicitud, aprobaciones simultáneas, rechazo/solicitud, identidad obsoleta y paymentstatus antiguo |
| Persistencia / HTTP | Estados comprometidos y nulos, débito ya contabilizado sin descuento doble, deducciones, ausencia de ledger, monto/clave/banco inválidos, identidad estricta y fallo de notificación aislado |
| Frontend | **113 aprobadas**, tres nuevas sobre reintento del formulario, cambio de intención y sufijo bancario incompleto |
| TypeScript / ESLint | Aprobados; advertencias anteriores conservadas |
| Compilación Next.js | Aprobada |
| Mypy global | **605 diagnósticos en 64 archivos**, frente a 606; sin introducir ignores ni reducir controles |
| Cobertura frontend | Statements 4,58 %, branches 4,25 %, functions 3,21 %, lines 4,57 %; no alcanza el umbral del 50 % |
| Flake8 / Black / git diff --check | Aprobados |

Las pruebas PostgreSQL usan esquemas privados de una base test_* explícita. La variante de enum se modifica únicamente allí y se elimina con el esquema. No se ejecutan cambios de esquema ni migraciones sobre datos de negocio. La ejecución remota anterior [40122510284](https://github.com/corporacionbethelst-ux/Delivery_360-DEV/actions/runs/40122510284) continuó fallando en tipos y cobertura; los pasos de pruebas backend y build estuvieron aprobados.

### Compatibilidad, alcance y siguientes pendientes

- **Cambio deliberado para instalaciones históricas:** órdenes sin crédito contable ya no financian retiros. Los saldos aparentes que dependían de ese fallback requieren revisión y conciliación autorizada; no se crean asientos retrospectivos ni se liberan fondos automáticamente.
- `pending` incorpora APROBADO y `processed` incorpora COMPLETADO. Son agrupaciones de solicitudes, no pruebas de una transferencia bancaria. Se añaden `ledger_balance` y `reserved` para explicar la disponibilidad; se conservan las claves anteriores del contrato.
- El reconocimiento de un retiro contabilizado exige importe completo, repartidor y referencia/origen coincidentes. Débitos parciales o sin vínculo identificable mantienen una retención conservadora hasta conciliación. Los datos históricos inconsistentes no se reparan en este bloque.
- Los GET de saldo son informativos y pueden cambiar mientras otras transacciones avanzan. La garantía de decisión serializada corresponde a las escrituras que participan en el protocolo de bloqueo. Escritores directos del ledger o cambios administrativos ajenos a ese protocolo requieren inventario y adaptación.
- La clave del formulario se conserva durante la vida de la página, no después de recargar o cerrar el navegador. La recuperación durable de una intención incierta, el historial visible para resolverla y la idempotencia entre dispositivos requieren un bloque adicional.
- Las notificaciones siguen siendo tareas en memoria y no constituyen un outbox durable. Los mensajes Redis y hooks existentes necesitan su propia revisión de entrega y auditoría transaccional. No se implementa un proveedor bancario/push ni se garantiza entrega efectiva.
- La compatibilidad de lectura con paymentstatus antiguo no acredita todos los enums/migraciones físicos. La moneda permanece en el contrato anterior COP y no se consolida con la wallet alternativa USD.
- Continúan pendientes 605 diagnósticos de tipos, cobertura global, auditoría completa de históricos, conciliación integral, proveedor de pagos, restauración/carga y los siguientes bloques del plan. No se fusiona ni despliega automáticamente este PR.


## Registro de avance — Recuperación de solicitudes inciertas, bloque 8 — 24 de octubre de 2026

**Base:** `2b28602`, fusión del PR #249. Rama: `fix/withdrawal-recovery-v1`. PR sin borrador, conservando controles y bloqueos globales.

### Comportamiento implementado

- **Intención recuperable tras recargar.** Antes de enviar un retiro se conserva en sessionStorage un registro versionado y separado por usuario: clave de idempotencia, monto en centavos y sufijo bancario opcional. No incluye tokens ni cuenta bancaria completa. Se valida formato, versión, propietario, precisión y límites antes de reutilizarlo. Si no puede conservarse, no se envía el POST.
- **Consulta de estado con autorización.** GET `/payouts/request-status?idempotency_key=...` devuelve únicamente una solicitud perteneciente al perfil del repartidor autenticado. La clave no concede permisos. Otro repartidor recibe el mismo 404 que una clave inexistente; otros roles reciben 403. El endpoint es informativo y no crea solicitudes, reservas, historial ni asientos.
- **Respuesta incierta.** Tras un fallo de red/servidor se conservan la clave y los datos; el formulario impide cambiar monto o cuenta mientras no esté resuelta esa intención. Ofrece consultar su estado, revisar historial o reintentar la misma solicitud. Una consulta 404 no elimina la intención: el POST original aún podría estar en curso. Tampoco se elimina si un reintento responde 400/422 después de una incertidumbre anterior.
- **Recuperación al montar la página.** Se restaura la intención y se consulta al servidor. Si existe, se muestran el monto y el estado devueltos, incluido RECHAZADO; no se vuelve a enviar. Si no aparece o el servidor falla, se conserva la misma clave. El reintento puede recuperar una reserva ya registrada aunque el saldo mostrado sea ahora menor: el backend comprueba la identidad existente antes de decidir si debe reservar fondos nuevos.
- **Limpieza condicionada.** Se retira la metadata al recibir confirmación del servidor, sin borrar una intención nueva que pudiera haberse guardado con otra clave. Un fallo de limpieza del navegador no convierte una respuesta confirmada en fracaso; una recarga puede volver a consultar esa misma clave con seguridad.
- **Rechazo inicial definitivo.** Una primera respuesta 400/422, sin una incertidumbre anterior, permite corregir los datos y comenzar una intención nueva. Los datos locales nunca se usan para confirmar autorización, saldo ni estado bancario.

### Evidencia local

| Control | Resultado |
|---|---|
| Backend completo | **305 aprobadas**, diez nuevas frente a la base; cuatro advertencias anteriores |
| PostgreSQL real aislado | **24 pruebas** en total; nueva comprobación de consulta por clave, propiedad y ausencia de reservas/historial adicionales |
| Nuevas pruebas HTTP | Lectura sin escrituras, estado actualizado, clave de otro repartidor indistinguible de una inexistente, roles, claves inválidas y falta de bearer token |
| Frontend | **130 aprobadas**, 17 nuevas frente a la base |
| Recuperación / navegador | Remontaje con saldo reducido y misma clave, registro ya existente sin POST adicional, estado RECHAZADO autoritativo, servicio de estado no disponible, rechazo después de incertidumbre, almacenamiento bloqueado, datos corruptos, separación por usuario y limpieza que respeta una intención más reciente |
| TypeScript / ESLint | Aprobados; advertencias anteriores conservadas |
| Compilación Next.js | Aprobada |
| Mypy global | **605 diagnósticos en 64 archivos**, igual que la base |
| Cobertura frontend | Statements 5,59 %, branches 5,19 %, functions 3,68 %, lines 5,54 %; umbral global del 50 % todavía incumplido |
| Flake8 / Black / git diff --check | Aprobados |

La consulta se declara antes de las rutas dinámicas de detalle para que request-status no sea interpretado como un UUID de payout. La API conserva sus rutas y contratos de retiro anteriores; se añade un GET y un método tipado del servicio frontend. No se añaden tablas ni migraciones.

### Límites y continuación necesaria

- sessionStorage conserva datos al recargar la **misma pestaña**, sin prometer persistencia después de cerrarla ni recuperación automática entre dispositivos. El historial del servidor continúa siendo la referencia. Una recuperación durable global requiere un modelo de intención/cancelación en backend y sus migraciones.
- No se añade cancelación ni tombstone de una intención aún inexistente. Si hubo incertidumbre, un 404 o un rechazo posterior no demuestra que ninguna petición original pueda terminar más tarde. Se conserva la clave hasta recuperar o registrar la solicitud, o resolver el caso mediante revisión del historial/soporte.
- Los datos locales son metadata no confiable: si están corruptos o tienen otra versión, se bloquea su reutilización y se indica revisar historial. No se descarta automáticamente una clave incierta para generar otra. La consulta de estado vuelve a comprobar el propietario en el servidor.
- Se mantienen las garantías y límites de reserva/idempotencia del bloque 7. Este trabajo no garantiza que solicitudes creadas deliberadamente con claves diferentes representen una sola intención de negocio, ni certifica exactamente-una-vez entre todos los dispositivos.
- No se realiza transferencia bancaria, no se acredita el proveedor de pagos ni se implementa outbox durable. Los estados mostrados son los del registro del sistema, no pruebas bancarias independientes.
- Continúan pendientes los 605 diagnósticos de tipos, la cobertura global, auditoría/conciliación integral, sesiones/revocación centralizadas y los siguientes bloques del plan. No se hacen migraciones sobre datos de negocio, pagos ni despliegues automáticos.


## Registro de avance — Cierre de calidad: contratos ORM, bloque 9 — 24 de octubre de 2026

**Base:** `b10d5c6`, fusión del PR #250. Rama: `fix/orm-financial-types-v1`. Este bloque prioriza reducir deuda de tipos y corregir consumidores; no incorpora otro producto o flujo financiero.

### Cambios

- Payout, PayoutStatusHistory, Rider y Vehicle declaran sus columnas mediante Mapped/mapped_column con UUID, Decimal, date/datetime, enums y nulabilidad reales. Los enums de Vehicle construidos con valores textuales se tipan como strings; no se confunden con los enums Python del repartidor. El JSON del repartidor tiene un contrato recursivo de valores JSON, sin sustituirlo por Any.
- Se tipan tres campos referenciados desde esos contratos: orders.assigned_rider_id, deliveries.rider_id y deliveries.locked_bonus_tier_level. Se conserva su nulabilidad original; no se endurece ni flexibiliza el esquema implícitamente.
- Las lecturas de estado/tipo de vehículo usan una conversión explícita que admite Enum, string heredado o None. Se evita llamar .value o .isoformat sobre campos históricos nulos. Los valores ausentes se representan como null, sin fabricar estados o fechas. El registro de cambios de vehículo ya no falla si el tipo anterior está ausente.
- El registro all_models importa explícitamente los modelos requeridos. Su paquete padre ya los importaba obligatoriamente; las guardas que asignaban None a clases/enums no aportaban opcionalidad efectiva y generaban contratos de tipos inconsistentes. Se mantienen los nombres exportados.
- La geometría last_location y las relaciones ORM no se convierten en este bloque; sus contratos de expresiones SQL/carga asíncrona requieren una revisión propia. No se emplean Any nuevos, casts para silenciar errores, ignores globales ni exclusiones de módulos.

### Prueba de conservación del esquema

Se tomó una instantánea **antes de modificar cada modelo** de las seis tablas implicadas: payouts, payout_status_history, riders, vehicles, orders y deliveries. Se compara automáticamente:

- DDL PostgreSQL: columnas, tipos, nulabilidad, claves y restricciones.
- Índices, incluidos los existentes de geometría.
- Defaults y onupdate de Python.
- Valores y opciones de enums.
- Claves foráneas, incluidos ondelete/onupdate y use_alter.

La comparación es exacta y pasa. Se conserva además el contrato previo de las cinco tablas del bloque 3. Esto demuestra equivalencia entre los modelos antes/después, **no** que una instalación productiva tenga sus migraciones aplicadas ni que sus datos históricos sean completos.

### Validación local

| Control | Resultado |
|---|---|
| Backend completo con PostgreSQL aislado | **309 aprobadas**, cuatro nuevas; 24 pruebas PostgreSQL incluidas; cuatro advertencias anteriores |
| Pruebas nuevas | Equivalencia de seis tablas; repartidor con estado/vehículo/fecha nulos y JSON persistido; enums textuales y fecha de seguro de vehículo; payout histórico con estado/método/fechas nulos |
| Mypy global | **511 diagnósticos en 60 archivos**, frente a 605 en 64: **94 diagnósticos menos** |
| Comparación de diagnósticos | Sin diagnósticos adicionales respecto al registro anterior, comparando módulo/mensaje y no números de línea |
| Flake8 / Black | Aprobados; 156 archivos de app formateados |
| Imports y registro de modelos | Verificados al importar la aplicación y ejecutar la suite |
| git diff --check | Aprobado |
| Frontend | Sin cambios en este bloque; última validación registrada: 130 pruebas y cobertura de líneas 5,54 % |

El comando global de mypy continúa fallando por los 511 diagnósticos restantes. No se declara CI aprobado ni producción lista; el mínimo frontend del 50 % continúa vigente.

### Hallazgo preservado y límites

**Política referencial pendiente:** deliveries.rider_id es NOT NULL y su FK declara ON DELETE SET NULL. Un borrado físico de un repartidor con entregas puede fallar al intentar establecer un nulo que la columna prohíbe. La contradicción ya existía; se preserva para no introducir una migración accidental. Su resolución exige definir la política de eliminación/retención de históricos y probar una migración deliberada. No se marca como corregida por este bloque.

Las anotaciones correctas no sustituyen validación de entrada, permisos o conciliación. Continúan pendientes otros modelos/consumidores, relaciones de carga diferida, contratos geográficos, documentos privados, sesiones y autorización restante. Los null de datos heredados no se corrigen con valores artificiales; deben tratarse explícitamente en clientes y procesos que los consuman.

No se altera el esquema, no se aplican migraciones, no se cambian saldos ni se ejecutan pagos. El PR se publica sin borrador, con los controles globales pendientes informados, sin fusión ni despliegue automáticos.

## Registro de avance — Cierre de calidad: pedidos y entregas, bloque 10 — 24 de octubre de 2026

**Base:** `49f1755`, fusión del PR #251. Rama: `fix/order-delivery-types-v1`.

### Correcciones y alcance

- Se completan los contratos Mapped/mapped_column de Order y Delivery: UUID, enums, fechas, nulabilidad, JSON recursivo y Decimal en las columnas Numeric de bonos. Se conserva Float en los importes de pedidos: convertirlos a Numeric requiere una migración deliberada y queda pendiente.
- La instantánea PostgreSQL existente de seis tablas sigue siendo la referencia, sin regenerarla. Se verifican DDL, índices, defaults, enums y claves foráneas; el esquema permanece idéntico. No se ejecutan migraciones.
- El servicio de pedidos usaba atributos que no existen en su DTO y nombres de coordenadas que no existen en el modelo. Ahora crea y actualiza usando los nombres persistidos, convierte los enums explícitamente y conserva el inicio PENDIENTE o ASIGNADO si se proporciona repartidor. Un estado terminal enviado al crear no salta ese inicio. El plazo por defecto sigue siendo de 60 minutos; no se presenta como motor de SLA configurable.
- Los cálculos de la API rechazan artículos con estructura incorrecta, importes negativos, booleanos, NaN, infinito y desbordamientos de multiplicación, suma o total. Se conserva la regla heredada por la que un total explícito cero usa subtotal más envío. No se cambia la política de precios ni se redondean a escondidas las columnas Float.
- El JSON compartido con Rider se valida como una copia recursiva de valores JSON: rechaza claves no textuales, objetos no serializables y flotantes no finitos.
- Los snapshots de bonos asignan Decimal cuantizado a dos decimales y enums canónicos. La configuración de bonos del servicio rechaza valores base no finitos/negativos y multiplicadores inválidos; devuelve cero con advertencia según su política anterior. Esto no certifica todas las rutas financieras ni implementa un proveedor de pagos.
- Los consumidores admiten estados históricos nulos sin llamar .value sobre None. Las consultas agregadas sin GROUP BY usan el contrato de una fila. Los filtros de entregas pasan argumentos explícitos y conservan sus condiciones anteriores.
- En el router legado combinado se corrige una fecha asignada a una columna de minutos: las duraciones son enteros no negativos y el tiempo en recogida solo se deriva cuando existen ambas marcas temporales. Este router de entregas no sustituye el router canónico registrado; su corrección no acredita por sí sola permisos, OTP o transiciones del legado.

### Evidencia y límites

- Mypy global: **410 errores en 58 archivos**, frente a 511 en 60; **101 menos**, sin mensajes nuevos al comparar módulo/mensaje. El comando todavía falla por deuda pendiente. No se añaden Any, casts de evasión, exclusiones de módulos ni ignores globales.
- Las pruebas nuevas cubren creación/actualización persistida de coordenadas y prioridad, estado inicial, JSON inválido, importes y desbordamientos, configuración inválida de bonos y un snapshot Decimal persistido sin commit dentro del helper.
- La comparación exacta de seis tablas y el contrato financiero previo se mantienen dentro de la suite. Los resultados finales de pruebas se registran abajo.
- Frontend sin cambios; última validación registrada: 130 pruebas y 5,54 % de cobertura de líneas. El umbral global del 50 % sigue incumplido. No se declara CI global aprobado ni producción lista.
- Se conserva el hallazgo NOT NULL / ON DELETE SET NULL en deliveries.rider_id. Siguen pendientes política de retención y migración explícita, tipos restantes, relaciones/geometría, revisión integral de autorizaciones y estados, conciliación y fases funcionales del plan.
- Persisten cuatro advertencias de pytest/ORM anteriores, incluidas relaciones superpuestas que requieren revisión propia. Esta mejora no silencia esas advertencias.

No se modifican datos de negocio, no se ejecutan pagos y no se fusiona ni despliega automáticamente. El PR se publica listo para revisión, sin borrador.

**Resultados finales locales:** suite completa **327 aprobadas**, incluidas las 24 pruebas PostgreSQL; después, el archivo completo de regresiones **19 aprobadas**, con una prueba adicional de persistencia Decimal incorporada tras iniciar la suite. Son **328 casos distintos aprobados**, 19 nuevos frente a los 309 de la base; no se presenta ese total como una única ejecución completa de 328. Black verifica 157 archivos de app, Flake8 crítico registra cero y git diff --check pasa. Se mantienen cuatro advertencias anteriores.

## Registro de avance — Fase 0: turnos y asistencia, bloque 11 — 24 de octubre de 2026

**Base:** `59b882d`, fusión del PR #252. Rama: `fix/shift-transition-safety-v1`. Alcance: API de turnos del panel operador, registrada como `/api/v1/shifts`, y reglas de transición que esa API utiliza.

### Problemas corregidos

1. **Concurrencia entre turnos del mismo repartidor.** Dos solicitudes podían consultar estados anteriores y activar simultáneamente dos turnos distintos. Las transiciones ahora bloquean primero la fila del repartidor y después la del turno mediante SELECT FOR UPDATE. El inicio verifica, dentro de esa transacción, que no exista otro turno EN_CURSO para el mismo repartidor. Un conflicto devuelve HTTP 409; los demás repartidores conservan sus bloqueos independientes.
2. **Reintentos y carreras de asistencia.** Dos inicios/cierres concurrentes podían duplicar marcas IN/OUT. Un reintento con el turno todavía en el estado solicitado devuelve el resultado existente, sin otra marca ni modificación de la hora. No se reabren turnos completados/cancelados. Esto es idempotencia por estado del recurso, no un registro durable de intenciones: intentar iniciar después de que otro proceso ya lo finalizó continúa rechazándose.
3. **Cancelación de un turno activo.** La API anterior permitía cancelar EN_CURSO sin registrar una salida. Ahora responde 409 e indica finalizar primero. PROGRAMADO e INCOMPLETO pueden cancelarse; repetir una cancelación ya realizada no cambia el motivo ni añade asistencia.
4. **Estado y asistencia en una misma transacción.** El helper no hace commit. Actualiza el estado y hace flush de la marca antes de que la API confirme ambos. Una inserción fallida o una respuesta que no se puede construir provoca rollback mediante la dependencia de sesión. La creación también prepara su respuesta antes del commit, evitando dejar un turno confirmado cuando falla la serialización previa.
5. **Horario planificado y real.** El cierre conserva end_time planificado; la salida real continúa en check_out_at. Se conserva el contrato de respuesta: si existe salida real, el campo end_time de la API la muestra; check_in_at/check_out_at siguen disponibles. No se toca el esquema para inventar un campo de duración.
6. **Turnos nocturnos y offsets.** Los horarios explícitos se normalizan a UTC sin zona, conforme a las columnas existentes. Las entradas sin offset se interpretan como UTC. La API acepta duración positiva de hasta 24 horas; rechaza con 422 los finales anteriores/iguales al inicio y los intervalos mayores, que no se representan fielmente con una sola fecha y dos campos Time. Un intervalo explícito de exactamente 24 horas sí se admite. Al serializar un horario planificado cuyo final es menor o igual al inicio, el final se interpreta al día siguiente. Esto es una convención para representar la planificación, no una reconstrucción certificada de históricos ambiguos. Si se omite el final, se conserva el valor por defecto 23:59 UTC, con paso al día siguiente cuando sea necesario.
7. **Datos históricos incoherentes.** Un cierre activo sin hora real de entrada, o con entrada futura, exige revisión con 409. Un reintento de inicio/cierre con marcas faltantes o contradictorias tampoco confirma un éxito aparente. No se fabrican horas de asistencia ni se reparan datos históricos automáticamente.
8. **Lecturas de repartidor limitadas a lo necesario.** La creación verifica su identificador; las lecturas para serializar turnos cargan solo el identificador y la zona operativa del repartidor. Se evita cargar su geometría y demás campos personales sin necesitarlos. Las uniones de usuario/zona y el formato público del panel se conservan.

### Autorización y límites de concurrencia

- SUPERADMIN, GERENTE y OPERADOR conservan la gestión del panel. REPARTIDOR, CLIENTE, AUDITOR y rol ausente reciben 403 antes de consultar turnos. Sin sesión, la ruta devuelve 401. No se añade una API de autoservicio del repartidor.
- El bloqueo garantiza la exclusión entre las transiciones de **esta API** en PostgreSQL. No sustituye una restricción única parcial en base de datos ni controla scripts SQL u otros escritores que omitan el protocolo. Una restricción adicional exige auditar y resolver duplicados históricos antes de su migración.
- No se modifica Rider.status, is_online ni la autorización de sesiones al marcar asistencia. Su sincronización con disponibilidad, pedidos activos y suspensión necesita una política explícita.
- No se añade auditoría durable de actor/motivo para cada marca, cálculo de nómina, conciliación de horas, geocerca ni prueba de presencia. El campo zone de creación conserva el comportamiento anterior; este bloque no implementa asignación de zona por turno.
- No se convierten los modelos/schema legacy ni se aplican migraciones. Los horarios multilocalidad requieren una política de zona horaria del negocio y una interfaz que la muestre; UTC aquí establece el contrato técnico, no esa política comercial.

### Hallazgo pendiente: caminos antiguos de turnos

`app/services/shift_service.py`, `app/crud/shift.py` y `app/schemas/shift.py` conservan contratos antiguos incompatibles: IDs enteros frente a UUID, estados ACTIVE/SCHEDULED/COMPLETED inexistentes en el modelo y campos de horario/asistencia que no existen. El servicio intentaba además cambiar estados de Rider inexistentes y confirmar asistencia/disponibilidad en commits separados. El router de turnos de `routers_combined.py` también conserva inconsistencias y controles insuficientes para reutilizarlo.

El registro actual usa `app/api/v1/shifts.py`; la búsqueda de referencias no muestra llamadas al servicio/CRUD antiguos desde esa API. **No se consideran corregidos ni autorizados para reutilización por este bloque.** El siguiente cierre de contratos debe adaptarlos al flujo común o retirarlos deliberadamente, sin volver a exponer rutas alternativas que eviten sus reglas. La consolidación completa de turnos sigue pendiente.

### Validación local

- **30 pruebas nuevas:** 23 sobre HTTP/persistencia y siete en PostgreSQL real aislado.
- HTTP/persistencia: roles y autenticación, UUID inválidos/inexistentes, inicio/cierre/cancelación y sus reintentos, rechazo de reapertura, un turno activo, conservación del horario, offsets/nocturnos/24h, intervalos inválidos, históricos incompletos y rollback si falla la respuesta o asistencia.
- PostgreSQL: dos inicios del mismo turno producen una sola entrada; dos turnos del mismo repartidor no se activan juntos; dos cierres producen una sola salida; carrera inicio/cancelación; repartidores distintos; rollback por el dueño de la transacción; fallo real de NOT NULL al insertar asistencia después de actualizar el estado.
- **Mypy: 410 errores en 58 archivos**, igual que la base; sin mensajes nuevos por módulo/mensaje. El módulo nuevo no tiene diagnósticos. No se cambia la configuración para silenciar deuda.
- **Black:** 158 archivos de app verificados. **Flake8 crítico:** cero. **git diff --check:** aprobado.
- Frontend sin cambios; última validación registrada: 130 pruebas y cobertura de líneas 5,54 %. La deuda de tipos y el umbral de cobertura global mantienen pendientes los controles generales de CI. Cuatro advertencias anteriores de pytest/ORM permanecen visibles.

No se ejecutan pagos, no se modifican datos de negocio y no se despliega ni fusiona automáticamente. Se publica un PR sin borrador. El resultado completo de la suite se registra al finalizarla.

**Resultado final:** suite completa **358 pruebas aprobadas**, 30 nuevas frente a la base; **31 pruebas PostgreSQL** incluidas (24 anteriores y siete nuevas). Cuatro advertencias anteriores. Ningún modelo ni archivo de migración fue modificado en este bloque.

## Registro de avance — Fase 0: contratos de turnos, bloque 12 — 24 de octubre de 2026 (America/Caracas)

**Base:** `ad4f099`, fusión del PR #253. Rama: `fix/shift-contracts-v1`. Se continúa el hallazgo del bloque 11: servicio, CRUD y schemas internos no concordaban con la base de datos. La API del operador conserva sus rutas y sus nombres de estados de interfaz.

### Contratos y conservación del esquema

- Shift y CheckInOut pasan a Mapped/mapped_column con UUID, datetime, time, enums y nulabilidad reales. Se conservan defaults, índices, claves foráneas, cascadas y opciones de enums; los importes históricos de turnos continúan siendo Float. Las relaciones y geometría ajenas no se modifican.
- Se capturó **antes del cambio** una instantánea PostgreSQL de shifts y check_in_out. La comparación automática exacta de DDL, índices, defaults, claves y enums pasa contra esa referencia, sin regenerarla después. No se añaden migraciones ni se presume que una instalación productiva tenga su esquema al día.
- Los schemas internos usan UUID y el mismo ShiftStatus del modelo. ShiftCreate exige inicio programado y solo admite el estado inicial PROGRAMADO; ShiftUpdate admite horario y notas, sin una escritura genérica de estado. Los campos de horario no pueden borrarse con null.
- Los antiguos metadata_json, photo_url, estados PAUSADO/ACTIVE y campos no soportados se rechazan explícitamente, evitando aceptarlos sin almacenamiento real. Los schemas de respuesta reflejan atributos persistidos y conservan null históricos. Esto cambia contratos internos incompatibles que no tenían consumidores HTTP registrados; **no cambia los aliases PLANIFICADO/ACTIVO/FINALIZADO de la API del panel**.

### Unificación del comportamiento

1. **Creación común:** API, CRUD y servicio usan el mismo helper de programación, que valida horario/notas y existencia del repartidor. No se intenta crear usando columnas inexistentes. El servicio verifica que el rider_id de su argumento coincida con el DTO.
2. **Asistencia del turno solicitado:** check_in/check_out utilizan el shift_id del request, verifican su pertenencia al rider_id recibido y llaman a la transición común. Ya no crean otro turno automáticamente, ignoran el turno solicitado ni cambian Rider.status usando enums inexistentes.
3. **Datos de asistencia:** coordenadas finitas, dentro de rango y en pares; notas de hasta 500 caracteres. La marca y las columnas de coordenadas del turno se guardan en la misma transacción. No se exige geolocalización para todas las operaciones ni se presenta la coordenada recibida como prueba de presencia.
4. **Reintentos:** se recupera el evento IN/OUT original, asociado al repartidor, turno, tipo y timestamp exactos. Un reintento no sobrescribe sus notas/coordenadas. Si faltan eventos o hay más de uno coincidente, se exige revisión con 409 en lugar de fabricar evidencia. El mismo control se aplica a la API del operador, aunque esta no consuma el evento devuelto.
5. **Control compartido de concurrencia:** ediciones de planificación, servicio, CRUD y API toman el bloqueo Rider→Shift. Reprogramar un turno activo o modificar uno terminal/inconsistente se rechaza. Las notas pueden cambiar mientras está activo; no se reabre un estado terminal. Un turno activo debe finalizarse antes de cancelarse.
6. **Transacciones:** los helpers comunes no confirman. Los adaptadores conservan commit por defecto para sus operaciones completas y ofrecen commit=False para que el dueño de una transacción compuesta confirme o revierta todo. Una operación de asistencia ya no hace un commit de turno y otro de estado del repartidor. La gestión de disponibilidad permanece separada.
7. **Consultas:** IDs UUID, estados existentes, orden por fecha/hora con desempate por ID, paginación validada y detección explícita de activos históricos duplicados. Los filtros de fecha utilizan shift_date y la hora programada, incluyendo históricos que guardan medianoche en shift_date, en lugar de columnas inexistentes o comparar Time con datetime.

### Cálculo de horas y productividad

El tipado expuso un consumidor que restaba campos Time y buscaba el estado COMPLETED inexistente. Se corrige el servicio de productividad que consume turnos:

- La productividad de un turno finalizado utiliza check_in_at/check_out_at, incluso cruzando medianoche; sin marcas válidas responde 409. Los IDs de sus resultados son UUID y los límites de sus consultas son fechas completas.
- La productividad por repartidor calcula horas con las marcas de turnos completados cuya salida está en el periodo, y duración media con marcas válidas de entregas completadas en el periodo. No sustituye horas reales por duración programada. El cálculo por repartidor recorre columnas mediante streaming en lotes y cierra ambos resultados, sin materializar todo el historial en memoria.
- Las estadísticas del servicio de turnos cuentan completados por planificación dentro del periodo, calculan horas/medias solo para marcas coherentes y exponen shifts_requiring_review. Por su propósito, este periodo por planificación es distinto al periodo por salida de la productividad del repartidor; no se afirma que ambos informes sean conciliables para nómina sin una política adicional.
- Estas métricas se derivan de marcas persistidas: no certifican presencia, nómina, ausencia de intervalos solapados ni integridad de todo el histórico. No se añaden escrituras de métricas ni cálculos de pagos.

### Retirada del camino alternativo antiguo

Se eliminan los handlers de turnos no registrados de routers_combined.py. Contenían campos inexistentes y una salida que no comprobaba propiedad. Su export shifts_router apunta ahora al router canónico con los permisos del operador. No se montan rutas adicionales ni se habilita autoservicio de repartidores. Una prueba comprueba el registro real y la ausencia de /checkin, /checkout y prefijos duplicados de turnos.

No se retiran ni certifican por extensión otros handlers antiguos de entregas, productividad u otros módulos. Su revisión continúa pendiente.

### Validación y pendientes

- **45 pruebas nuevas:** 41 de contratos/persistencia/consumidores y cuatro PostgreSQL de adaptadores mixtos. Cubren equivalencia de dos tablas, schemas estrictos, UUID, pertenencia, turno solicitado, recuperación de la misma marca, rechazo de evidencia ausente, coordenadas inválidas, estados, planificación, filtros, null históricos, horas/productividad y commit=False.
- PostgreSQL nuevo: servicio contra CRUD al activar dos turnos del mismo repartidor; reintentos concurrentes del servicio que recuperan el mismo evento; carrera de reprogramación contra inicio; rollback externo del servicio. Se conservan las siete pruebas de concurrencia del bloque 11 y las 24 financieras anteriores.
- **Mypy: 342 errores en 53 archivos**, frente a 410 en 58: **68 menos**, sin diagnósticos nuevos al comparar módulo/mensaje. No se añaden ignores de mypy, casts de evasión ni exclusiones. El control global sigue fallando por deuda restante.
- Black verifica 158 archivos de app; Flake8 crítico registra cero; git diff --check pasa. Las cuatro advertencias anteriores de pytest/ORM se conservan.
- Frontend sin cambios; última validación registrada: 130 pruebas y cobertura de líneas 5,54 %. El umbral global del 50 % y los errores restantes mantienen CI pendiente. La ejecución de main posterior al PR #253 terminó con fallo; no se presenta este bloque como CI global verde.

**Límites:** los servicios internos no autentican al actor. Un futuro consumidor debe autorizarlo y resolver rider_id desde su identidad, además de aplicar el control de pertenencia; no basta con aceptar un rider_id enviado por un cliente. Sigue pendiente una restricción única parcial y la revisión de duplicados históricos, auditoría durable de actor, disponibilidad, geocercas, nómina y política de zona horaria del negocio. Los workers y contratos restantes de productividad conservan deuda ajena a este consumidor y requieren otro bloque. No se aplican migraciones, pagos, reparaciones de históricos, fusión ni despliegue automáticos.

El resultado final de la suite completa se añade después de su ejecución. El PR se publica sin borrador.

**Resultado final local:** suite completa **403 pruebas aprobadas**, 45 nuevas respecto a las 358 de la base; **35 pruebas PostgreSQL** incluidas. Cuatro advertencias anteriores. Comparación exacta de las dos tablas nueva y contratos anteriores aprobados; sin migraciones ni cambios de datos de negocio.

## Registro de avance — Fase 0: confidencialidad de documentos, bloque 13 — 24 de octubre de 2026 (America/Caracas)

**Base:** `9f0d777`, fusión del PR #254. Rama: `fix/private-rider-documents-v1`.

### Hallazgo y resultado

Las licencias, documentos de identidad, registros de vehículo y seguros se guardaban en uploads/documents y el montaje público /uploads permitía obtenerlos sin pasar por las reglas de autorización de las APIs de documentos. Los listados protegidos no protegían los bytes enlazados. El panel de gestión abría esos enlaces directamente en otra pestaña.

Este bloque cierra ese acceso público **en la aplicación** y añade una descarga autenticada, sin mover ni eliminar archivos históricos y sin cambiar las referencias almacenadas en la base.

### Cambios de acceso y compatibilidad

- Nuevo **GET /api/v1/riders/documents/{doc_id}/download**. Exige la sesión existente. SUPERADMIN, GERENTE y OPERADOR conservan la lectura administrativa que ya permitía el listado; REPARTIDOR solo puede descargar documentos cuyo perfil pertenece a su user_id. CLIENTE, AUDITOR y rol ausente se rechazan antes de consultar el documento.
- Para otro repartidor, la respuesta es el mismo 404 que para un documento inexistente. No se aceptan rutas de disco ni URLs remotas como parámetros de descarga y no se realizan peticiones a referencias externas.
- La resolución de la referencia exige un archivo del directorio del mismo rider_id. Rechaza traversal, subdirectorios, archivos ausentes y enlaces simbólicos que salgan de ese directorio. No se repara una referencia inválida con una ubicación alternativa ni se revela la ruta física en el error.
- La respuesta usa attachment con nombre generado desde doc_id, Cache-Control private/no-store, Vary Authorization, nosniff y CSP con sandbox. Los formatos PDF/PNG/JPEG conservan su MIME; otros archivos se descargan como binario. Esto no acredita que su contenido sea inocuo.
- PublicUploads sustituye al StaticFiles genérico: bloquea /uploads/documents, variantes normalizadas/codificadas y alias simbólicos que resuelvan dentro de documentos. Los demás archivos públicos se conservan; una prueba comprueba un recurso ajeno a documentos.
- El middleware HTTP de caché excluye **todo /uploads**, además del API privado ya excluido. Así no consulta ni devuelve entradas antiguas de documentos antes de ejecutar el bloqueo; tampoco intenta decodificar como texto los recursos binarios públicos. Una prueba simula una entrada antigua con contenido privado y comprueba que no se lee.
- Los listados propios/administrativos y las respuestas de subida mantienen la clave file_url, pero ahora contienen el endpoint autenticado por ID, o null si no hay referencia. Se elimina la construcción de una URL absoluta con localhost y doble slash. **Ese valor ya no es un enlace público para abrir sin cabecera Authorization.** Los consumidores externos deben usar el flujo autenticado.
- Las consultas de existencia para los listados cargan el identificador necesario del repartidor, sin pedir su geometría ni sus demás datos. No se cambian estados de documentos, reglas de aprobación ni pertenencia.

### Panel y descarga

- Se reemplaza la apertura directa del enlace en el panel de gestión por DocumentDownloadButton. El servicio llama al cliente API autenticado usando un endpoint relativo fijo y doc_id validado; no usa file_url como destino, no coloca tokens en URLs y no recurre al enlace público si falla.
- El botón muestra progreso, evita clics duplicados, permite reintentar tras un error y descarga un Blob con nombre local controlado. Rechaza respuestas vacías o que no sean Blob y libera la URL temporal generada.
- Cambiar de documento o desmontar el componente cancela la petición e impide descargar una respuesta tardía. No se añade persistencia de blobs, enlaces firmados ni tokens nuevos. Las descargas ya completadas por un usuario autorizado no se pueden revocar desde la aplicación.

### Contrato de base de datos

RiderDocument se tipa con Mapped/mapped_column: UUID, enums, strings y fechas con la nulabilidad existente. Una instantánea PostgreSQL tomada **antes de modificar el modelo** verifica exactamente columnas, índices, defaults SQL, claves foráneas, cascadas y opciones de enums. Pasa sin regenerar la referencia. No hay migración, traslado de archivos ni reparación de registros.

El volumen uploads existente sigue siendo la ubicación física. No se presenta como un nuevo almacén de objetos privado ni se cambia su política de retención.

### Evidencia local

| Control | Resultado |
|---|---|
| Backend completo | **434 aprobadas**, 31 nuevas; **35 PostgreSQL** anteriores incluidas; cuatro advertencias anteriores |
| Pruebas de documentos | Roles, propietario y recurso ajeno, ausencia de sesión, cabeceras/attachment, metadata sin URL pública, referencias inválidas/remotas, traversal, archivos ausentes, alias simbólicos, GET/HEAD y variantes codificadas, recurso público conservado y bypass de caché antiguo |
| Frontend completo | **143 aprobadas**, 13 nuevas, en 12 suites |
| Pruebas de descarga frontend | Ruta fija y cancelación, IDs inválidos, errores sin fallback público, Blob/nombre/extensión, liberación de URL, doble clic, reintento, desmontaje y cambio de documento |
| TypeScript / ESLint / Next.js build | Aprobados; advertencias anteriores conservadas |
| Mypy | **330 errores en 52 archivos**, frente a 342 en 53: **12 menos**, sin diagnósticos nuevos por módulo/mensaje |
| Black / Flake8 crítico / git diff --check | Aprobados; 159 archivos de app verificados, cero errores críticos de lint |
| Contrato PostgreSQL de documentos | Comparación exacta aprobada; contratos anteriores conservados |
| Cobertura frontend | Statements **6,15 %**, branches **5,44 %**, functions **4,06 %**, lines **6,07 %**; sigue incumpliendo el mínimo global del 50 % |

Las 143 pruebas frontend pasan, pero el comando con cobertura termina con error por ese umbral. Mypy también termina con error por los 330 diagnósticos restantes. No se afirma CI global verde ni producción lista.

### Límites y requisitos para publicar la aplicación

1. **Límite de esta protección:** controla las respuestas que pasan por FastAPI. Un proxy, servidor estático, bucket o CDN que sirva directamente el volumen puede evitar ese control. Antes de desplegar se debe impedir el acceso directo a uploads/documents en esas capas y purgar copias públicas previas cuando existan. No se han inspeccionado ni modificado servicios de producción externos; no se afirma haber retirado contenido ya descargado o cacheado fuera de la aplicación.
2. Backend y panel deben publicarse coordinadamente. Los enlaces públicos antiguos dejan de servir documentos; se mantiene el acceso a archivos locales históricos mediante el endpoint autorizado. No hay fallback anónimo por compatibilidad.
3. Siguen pendientes validación robusta de tamaño/formato/contenido de subida, análisis de malware, cuotas, retención/borrado físico, cifrado del almacén y copias de seguridad, auditoría durable de cada lectura y protección operativa del volumen. Este bloque no modifica los escritores ni elimina archivos reemplazados u huérfanos.
4. El endpoint utiliza las reglas actuales de sesión. No añade una excepción de acceso para cuentas pendientes/suspendidas ni resuelve por sí solo la experiencia de onboarding y recuperación de documentación de esas cuentas.
5. Continúan los 330 diagnósticos, la cobertura global y las demás fases funcionales/operativas del plan. No se ejecutan pagos, migraciones ni cambios sobre datos de negocio. El PR se publica sin borrador, sin fusión ni despliegue automáticos.

## Registro de avance — Fase 0: subidas y ciclo de guardado de documentos, bloque 14 — 24 de octubre de 2026 (America/Caracas)

**Base:** `db3e173`, fusión del PR #255. Rama: `fix/document-upload-validation-v1`. Se conservan la descarga autenticada y el bloqueo estático del bloque 13.

### Política común de entrada

Las tres vías de escritura —registro público de repartidor, subida propia y subida administrativa— dejan de copiar archivos sin límite mediante helpers duplicados. Utilizan una política común:

- **Máximo 10 MiB por archivo**, medido leyendo como máximo el límite más un byte. No se confía en el tamaño declarado por el cliente. Un exceso devuelve 413; un archivo vacío, 422.
- Solo extensiones PDF, PNG y JPEG, con MIME congruente y una comprobación de sus cabeceras mágicas. Se admite MIME genérico application/octet-stream o ausente si extensión y cabecera concuerdan. SVG, HTML, extensiones no soportadas y discordancias devuelven 415. JPEG se guarda con extensión canónica .jpg.
- **Es una validación básica de contenedor**, no una decodificación completa, prueba de integridad del documento, sanitización ni análisis de malware. Un archivo con cabecera válida puede contener contenido malicioso; no se certifica su inocuidad.
- Los cuatro documentos del registro se validan antes de crear usuario/perfil o escribir archivos definitivos. Un cuarto documento inválido no deja una cuenta parcial ni las tres subidas anteriores guardadas.
- El navegador usa la misma selección de formatos/tamaño para mensajes tempranos. Los selectores de registro y perfil ya no anuncian image/* cuando solo se admiten PNG/JPEG; ambos servicios de subida y el servicio de registro verifican las selecciones. La validación del servidor sigue siendo la autoridad. Se eliminan cuatro ts-ignore del armado de archivos de registro usando el tipo existente con archivos.

### Límite anterior al parser multipart

DocumentUploadLimitMiddleware limita las tres rutas POST, también cuando llevan slash final:

| Ruta | Límite del cuerpo completo |
|---|---|
| Registro con cuatro documentos | **41 MiB**: cuatro archivos de 10 MiB y 1 MiB de margen multipart/campos |
| Subida propia o administrativa | **11 MiB**: un archivo de 10 MiB y 1 MiB de margen |

Cuenta los bytes recibidos, incluyendo cuerpos por chunks y Content-Length falso o ausente. Un Content-Length excesivo se rechaza antes de recibir el cuerpo; longitudes malformadas/duplicadas/inconsistentes se rechazan con 400. El parser multipart solo recibe el cuerpo después de verificar el límite.

Para ello usa un spool temporal privado: hasta 1 MiB en memoria y después disco temporal, con reproducción en chunks de 64 KiB y cierre garantizado al finalizar, fallar o desconectarse el cliente. Las operaciones de disco se ejecutan fuera del event loop. CORS y rate limiting envuelven este control; se comprueba una respuesta 413 a través de la aplicación real, con su cabecera CORS.

El límite es **por petición**, no una cuota global de RAM, disco o concurrencia. El spool y los temporales del framework pueden coexistir y duplicar datos temporalmente. No sustituye límites/timeouts del proxy, cuotas del volumen ni protección frente a muchas subidas simultáneas. No se limitan por extensión otras rutas ajenas a documentos.

### Archivos nuevos y transacción SQL

DocumentUploadBatch controla exclusivamente los archivos nuevos de su operación y la sesión transaccional de esa petición:

1. Los nombres se generan desde el tipo documental y un UUID; se descarta el nombre del cliente como destino. La creación exclusiva evita sobrescribir un archivo previo, incluso si colisiona el nombre. Los nuevos archivos tienen permisos 0600 y los nuevos directorios documentales, 0700; no se cambian permisos históricos.
2. Se rechazan enlaces simbólicos en el directorio documental o del repartidor antes de escribir fuera de la ubicación prevista. El contenido se escribe y sincroniza antes del commit SQL.
3. Ante una validación/política rechazada no se guarda un nuevo archivo. Ante fallo de disco o flush SQL **antes de intentar commit**, se hace rollback y se intenta eliminar solo los archivos nuevos de ese lote. Los originales y sus versiones históricas nunca se borran por compensación.
4. La respuesta se prepara antes del commit; se evita un refresh posterior como condición para devolver el éxito. No se confirma usuario, perfil o documentos en commits separados.
5. **Si se intentó commit y su confirmación falla, no se borran los archivos nuevos.** La base podría haber confirmado aunque el cliente haya perdido el acuse. Se devuelve 503 indicando consultar el estado antes de reenviar; un log operativo marca la incertidumbre sin incluir contenido, nombres originales ni parámetros SQL.
6. La cancelación anterior al commit limpia los archivos nuevos y propaga la cancelación. La limpieza/rollback se protegen frente a cancelación; si falla la limpieza se registra la necesidad de conciliación.

Esto es compensación controlada, **no una transacción atómica distribuida entre filesystem y PostgreSQL**. Un cierre abrupto del proceso, fallo de limpieza o resultado incierto puede dejar archivos para conciliación. No hay todavía registro durable de intención, job de recuperación ni garantía exactamente-una-vez para todos los reintentos administrativos. Las versiones anteriores se conservan hasta definir retención/borrado físico.

### Estado documental y concurrencia

- Se conservan las reglas: el repartidor puede crear o reemplazar rechazados; no puede reemplazar APROBADO ni PENDIENTE. GERENTE/SUPERADMIN pueden reemplazar pendientes, pero no aprobados. Los roles ajenos continúan rechazándose antes de guardar archivos.
- Las subidas incluidas toman el bloqueo Rider→RiderDocument y vuelven a leer el estado dentro de esa transacción. Dos subidas propias concurrentes no crean dos documentos pendientes del mismo tipo. Una revisión que confirma APROBADO antes de liberar el bloqueo impide que la subida posterior lo sobrescriba.
- Revisión y eliminación por ID usan el mismo orden de bloqueo. Las consultas auxiliares de revisión no cargan geometría ni campos innecesarios del repartidor. Los duplicados históricos del mismo tipo devuelven 409 y requieren revisión, sin elegir un registro arbitrariamente.
- Las referencias siguen bajo el volumen existente y la metadata sigue devolviendo la descarga autenticada. No se modifica el esquema ni se cambia la política de sesión/aprobación de cuentas.

### Evidencia final local

| Control | Resultado |
|---|---|
| Backend completo | **494 aprobadas**, **60 nuevas** frente a 434; cuatro advertencias anteriores |
| PostgreSQL real aislado | **40 pruebas** incluidas: cinco nuevas y 35 anteriores |
| PostgreSQL nuevo | Subidas propias concurrentes, repartidores distintos, fallo real de NOT NULL antes del commit, pérdida de acuse después de un commit real, espera de revisión y rechazo de sobrescritura de APROBADO |
| Política/persistencia/HTTP | Formatos, MIME/cabeceras, vacío y límite exacto; reemplazo propio/administrativo; permisos, estados y duplicados; registro de cuatro documentos; fallos parciales de disco/SQL; commit incierto; cancelación; nombres en colisión, symlinks, revisión y eliminación |
| Límite ASGI | Content-Length excesivo/falso/duplicado, chunks reales, reproducción del spool y cierre, desconexión, rutas ajenas conservadas, CORS y aplicación real |
| Frontend | **161 aprobadas**, **18 nuevas**, en 13 suites |
| TypeScript / ESLint / Next.js build | Aprobados; advertencias anteriores conservadas |
| Mypy | **330 errores en 52 archivos**, igual que la base; sin mensajes nuevos por módulo/mensaje. Los dos módulos nuevos no añaden diagnósticos |
| Black / Flake8 crítico / git diff --check | Aprobados; 161 archivos de app verificados, cero errores críticos de lint |
| Cobertura frontend | Statements **6,60 %**, branches **5,79 %**, functions **4,28 %**, lines **6,53 %**; sigue bajo el mínimo global del 50 % |

Las pruebas frontend pasan, pero su comando con cobertura falla por el umbral. Mypy mantiene su salida con error por la deuda anterior. No se declara CI global verde ni producción lista. Los contratos de esquema anteriores siguen dentro de la suite; no se aplican migraciones, pagos ni modificaciones sobre datos de negocio.

### Hallazgos y siguiente prioridad

**Revisión por versión pendiente.** La aprobación actual recibe doc_id y estado, pero no una revisión del archivo que vio el operador. Aunque las mutaciones se serializan, un reemplazo anterior a la confirmación del revisor puede hacer que este apruebe una versión distinta de la examinada. El próximo bloque debe exponer una revisión opaca del archivo y exigirla al aprobar/rechazar, rechazando revisiones desactualizadas. No se considera solucionado mediante el bloqueo por sí solo.

**Existencia y habilitación pendientes.** _required_document_error se apoya en tipos/estados, sin comprobar la disponibilidad física ni la revisión exacta de cada archivo. Los históricos aprobados con referencias ausentes o inválidas necesitan control explícito antes de habilitar al repartidor. La eliminación de un documento tampoco consolida por sí sola la política de suspensión/disponibilidad de su cuenta. Debe revisarse ese circuito junto con la aprobación por versión.

También siguen pendientes decodificación estructural completa/antimalware, cuotas y timeouts operativos, conciliación durable y retención de archivos, auditoría de acceso/revisión y los límites de proxy/CDN del bloque 13. No se despliega, no se fusiona automáticamente y el PR se publica sin borrador.

## Bloque 15 — Revisión documental por versión y habilitación coherente

Fecha: 24 de octubre de 2026 (America/Caracas). Base: main, commit 2204f64e233aed1beec2a3e96bd24cb0a741fc6d. Rama: fix/document-review-revisions-v1.

### Comportamiento implementado

Cada documento expone una revisión SHA-256 de su metadata: identidad, repartidor, tipo, referencia almacenada, estado, motivo de rechazo y fecha de actualización. Aprobar, rechazar y eliminar exigen la revisión esperada. Una operación desactualizada devuelve 409 sin modificar la versión actual; un token mal formado devuelve 422. La descarga admite If-Match y devuelve ETag. Se actualiza CORS para permitir/exponer estas cabeceras.

El panel captura la revisión al iniciar la acción, incluido el modal de rechazo. Una actualización en segundo plano no sustituye la revisión capturada. Ante conflicto se informa y recarga la lista; nunca se reintenta automáticamente una aprobación con la nueva versión. El botón de descarga cancela la petición anterior al cambiar la revisión. Los logs del servicio frontend dejan de imprimir errores Axios completos que podrían contener cabeceras de autorización.

Revisión, sustitución, eliminación y cambios administrativos de habilitación incluidos comparten bloqueo del repartidor antes del documento. Las consultas refrescan la metadata de la sesión SQL para evitar responder con valores previamente cargados.

Para habilitar se exigen los cuatro tipos documentales actuales, sin duplicados, aprobados y con archivo local seguro, legible y no vacío. Aprobar un archivo ausente, vacío o con referencia insegura se rechaza. El rechazo sigue disponible para corregir esas situaciones.

- Reemplazar documentación la deja pendiente y deshabilita disponibilidad. Una documentación incompleta convierte ACTIVO/OCUPADO en PENDIENTE y fuerza is_online=false; conserva estados cerrados como SUSPENDIDO/INACTIVO.
- La revisión documental solo activa automáticamente una cuenta PENDIENTE con todos sus documentos válidos. No levanta automáticamente suspensiones ni inactivaciones y la activación deja al repartidor desconectado.
- Eliminar metadata documental vuelve a evaluar la habilitación. Los archivos físicos históricos se conservan según la política anterior.
- La aprobación administrativa explícita y el cambio a ACTIVO verifican disponibilidad documental. La suspensión administrativa fuerza desconexión. La activación explícita de un administrador autorizado puede levantar una suspensión si se cumplen los requisitos.
- Los endpoints de disponibilidad y heartbeat de riders verifican el estado y los documentos antes de permitir conexión.

### Contratos y compatibilidad

approveDocument/rejectDocument envían expected_revision en JSON; DELETE exige If-Match. Se admiten tokens hexadecimales de 64 caracteres y, en cabecera, su representación entre comillas. Una revisión ausente se rechaza con 409. Clientes antiguos deben actualizarse para realizar estas escrituras; las descargas de lectura sin condición siguen disponibles con autorización. Backend y frontend deben publicarse coordinadamente.

No se cambian modelos ORM ni esquema, no se añaden migraciones y no se intervienen datos de negocio. La revisión no es una credencial, una firma de auditoría, un contador monotónico ni un hash del contenido. Su vínculo con el archivo depende de las referencias inmutables y los nombres exclusivos usados por las subidas de la aplicación. Una modificación externa de bytes bajo la misma referencia no queda detectada por este token.

### Verificación local

| Control | Resultado |
|---|---|
| Backend completo | **537 pruebas aprobadas**, 43 nuevas frente a 494; cuatro advertencias anteriores |
| PostgreSQL real aislado | **46 pruebas** incluidas, seis nuevas sobre carreras de revisión, sustitución, borrado, activación y suspensión |
| Frontend | **183 pruebas aprobadas** en 15 suites, 22 nuevas |
| TypeScript / ESLint / Next.js build | Aprobados; advertencias anteriores |
| Black / Flake8 crítico / git diff --check | Aprobados; 162 archivos de app, cero errores críticos de lint |
| Mypy | **330 errores en 52 archivos**, misma base; sin diagnósticos nuevos por archivo/mensaje |
| Cobertura frontend | Statements **8,16 %**, branches **6,74 %**, functions **5,53 %**, lines **8,19 %** |

Las pruebas cubren tokens ausentes/malformados/desactualizados, estados que invalidan la revisión, referencias inseguras y archivos vacíos/ausentes, preservación de suspensiones, duplicados, conflictos HTTP y carreras reales de PostgreSQL. El panel tiene pruebas de revisión capturada antes de refrescos y de ausencia de reintento automático. Las pruebas frontend pasan, pero el comando con cobertura continúa fallando por el mínimo global del 50 %. Mypy conserva deuda anterior. Estos resultados no equivalen a CI global verde ni certificación para producción.

### Hallazgos pendientes y siguiente bloque

1. **Otros escritores de disponibilidad.** telemetry.py y tracking_service.py pueden establecer is_online=true sin aplicar este protocolo documental y de bloqueo. No modifican Rider.status, pero pueden dejar inconsistente la bandera de conexión, especialmente con peticiones en vuelo. El siguiente bloque debe unificar estos escritores y probarlos con concurrencia.
2. **Cambio de vehículo y documentación.** update_my_profile conserva su circuito previo de invalidación documental: solo convierte ACTIVO en PENDIENTE y no comparte todavía el protocolo completo. Debe incluir OCUPADO y coordinarse con seguimiento/disponibilidad. Este bloque no modifica ese flujo.
3. **Documentos históricos y almacenamiento.** Se verifica acceso seguro y lectura de un byte; no hay análisis completo del contenedor, antivirus, OCR, caducidad legal ni certificación retrospectiva de revisiones humanas. La pérdida externa de archivos se detecta al ejecutar las comprobaciones incluidas, no mediante vigilancia continua del volumen.
4. **Auditoría y recuperación.** Quedan pendientes historial durable del actor/revisión, conciliación de archivos, retención y recuperación tras fallos. No hay atomicidad distribuida filesystem/SQL.
5. **Operación de entregas activas.** Deshabilitar disponibilidad no cancela ni reasigna entregas existentes. Falta definir y probar la política operativa cuando se invalida documentación durante una entrega.

No se fusiona ni despliega automáticamente. El PR se publica listo para revisión, sin borrador.

## Bloque 16 — Disponibilidad coherente en GPS y cambio propio de vehículo

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit 54c7a4f, con PR #257 fusionado. Rama: fix/rider-telemetry-eligibility-v1.

### Problema y comportamiento resultante

Los escritores de ubicación de telemetry.py y TrackingService podían asignar is_online=true sin verificar el estado administrativo ni la documentación. Un reporte concurrente podía reconectar la bandera de una cuenta suspendida o con documentos invalidados. El cambio propio de vehículo solo restringía ACTIVO y podía dejar OCUPADO conectado; además, su respuesta anunciaba PENDIENTE incluso si la cuenta conservaba una suspensión.

Se centraliza ensure_rider_can_report_online en el servicio documental. Toma el bloqueo del repartidor, refresca su estado dentro del bloqueo y verifica los documentos aprobados y físicamente disponibles antes de permitir escrituras de posición. Los escritores incluidos mantienen el bloqueo hasta confirmar su actualización SQL.

- Telemetría, TrackingService y heartbeat de riders admiten ACTIVO/OCUPADO con documentación válida. OCUPADO conserva su estado durante el seguimiento de una entrega. El interruptor explícito de conexión conserva su contrato anterior: exige ACTIVO.
- PENDIENTE, SUSPENDIDO e INACTIVO se rechazan con 403 y se conserva la desconexión. Si falta documentación válida en una cuenta ACTIVO/OCUPADO, se restringe a PENDIENTE y se desconecta.
- La comprobación se ejecuta antes de añadir historial GPS o cambiar coordenadas. Un reporte rechazado no guarda su posición ni emite su broadcast. La restricción de seguridad sí se confirma antes de devolver el error.
- TrackingService devuelve 404 para un repartidor inexistente antes de insertar ubicación. La autorización de propiedad/roles permanece en los endpoints y precede las mutaciones de seguridad.
- Las consultas calientes de ingreso cargan solo la identidad/estado necesario, sin cargar geometría ni relaciones como vehículos. Las actualizaciones geográficas de telemetría mantienen su escritura PostGIS anterior; el seguimiento conserva su snapshot plano.

### Cambio propio de vehículo

PUT /riders/me toma el mismo bloqueo y refresca tipo/placa/estado antes de detectar el cambio. La invalidación de documentos conserva su política previa y actualiza sus revisiones. ACTIVO y OCUPADO pasan a PENDIENTE; SUSPENDIDO e INACTIVO se conservan; todos quedan desconectados.

Tras la actualización SQL se refrescan explícitamente status/is_online antes de construir la auditoría: la expresión CASE puede expirar atributos del ORM y su lectura implícita provocaba MissingGreenlet. El evento y la respuesta ahora reflejan el estado real y el mensaje indica revisión documental/disponibilidad deshabilitada sin afirmar una reactivación o cambio a PENDIENTE inexistente.

### Compatibilidad y límites

No se modifican modelos, esquema, migraciones ni frontend. Los reportes que antes podían aceptar cuentas no habilitadas ahora devuelven 403. Los reportes válidos conservan formatos de respuesta y persistencia; el heartbeat de riders incorpora el caso OCUPADO que antes rechazaba. Las restricciones anteriores de aprobación documental por versión permanecen vigentes.

El helper confirma las restricciones al denegar y exige que sus llamadores lo invoquen antes de añadir cambios de negocio; no es un guard genérico para reutilizar después de acumular escrituras. Se preserva la emisión del evento de ubicación después del commit. Un evento correspondiente a un reporte válido ya confirmado puede llegar después de una suspensión posterior: no se garantiza orden global de eventos ni revocación retroactiva del historial.

### Hallazgos y prioridades siguientes

1. El cambio **administrativo** de vehículo/asignación y los demás flujos de flota requieren una revisión específica de invalidación documental y bloqueos. Este bloque cubre el cambio propio de tipo/placa; no declara cerrado todo el ciclo de vehículos.
2. No se cancelan ni reasignan entregas activas al invalidar documentos o suspender una cuenta. Debe definirse la continuidad operativa y el acceso mínimo necesario para cerrar esas entregas.
3. La comprobación física lee los archivos requeridos en cada intento de conexión/reporte; falta medir carga y latencia con concurrencia de producción antes de diseñar una caché coherente con las revisiones.
4. El rate limit de tracking sigue siendo local al proceso; faltan un límite distribuido, cuotas y controles del proxy/volumen. No se corrigen mediante el bloqueo SQL.
5. Persisten las limitaciones de históricos, análisis estructural/antimalware, auditoría durable de revisiones y conciliación/retención de archivos descritas en los bloques anteriores. Los logs heredados del cambio de vehículo todavía requieren revisión de minimización de datos personales.

### Evidencia final local del bloque 16

| Control | Resultado |
|---|---|
| Backend completo | **564 pruebas aprobadas**, 27 nuevas frente a 537; cuatro advertencias anteriores |
| PostgreSQL real aislado | **51 pruebas** incluidas, cinco nuevas: persistencia válida ACTIVO/OCUPADO, suspensión antes/después del bloqueo GPS y borrado concurrente |
| Nuevas pruebas restantes | 22 casos con base SQLite: denegación sin posición/broadcast, cuenta inexistente, propiedad, requisitos documentales, heartbeat nuevo/antiguo, cambio propio y auditoría en cuatro estados |
| Mypy con --ignore-missing-imports | **330 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje |
| Black / Flake8 crítico / git diff --check | Aprobados; 162 archivos de app, cero errores críticos de lint |
| Frontend | Sin cambios; se conserva la validación anterior de 183 pruebas y build, no repetida en este bloque exclusivamente backend |

Los dobles de sesión de Fase 8 se adaptan al contrato de consultas y documentos requeridos, con archivos reales temporales; no se omite la comprobación de elegibilidad para mantener esas pruebas. El doble de edición ordinaria incorpora la consulta asíncrona del bloqueo. Las pruebas PostgreSQL usan una base test_* y esquemas aislados, nunca datos de negocio.

Se mantienen la deuda Mypy y el umbral de cobertura frontend incumplido. No se declara producción lista ni CI global verde. El PR se publica sin borrador; no se fusiona ni despliega automáticamente.

## Bloque 17 — Integridad de asignaciones y cambios administrativos de vehículo

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit bcc0ae4, con PR #258 fusionado. Rama: fix/fleet-assignment-integrity-v1.

### Hallazgos tratados

La edición administrativa del repartidor no invalidaba sus documentos al cambiar tipo, placa, modelo o asignación. La reasignación actualizaba el vehículo nuevo, pero no liberaba siempre Vehicle.rider_id del anterior. Las comprobaciones de disponibilidad no bloqueaban el vehículo y podían aceptar solicitudes competidoras. La eliminación comprobaba únicamente Vehicle.rider_id, omitiendo referencias desde Rider.assigned_vehicle_id.

El nuevo servicio fleet_assignment comparte validaciones, bloqueo e invalidación entre la edición administrativa y la propia. La creación administrativa de repartidores con vehículo de empresa también usa el bloqueo y comprueba ambos vínculos.

### Protocolo transaccional

1. Se bloquean los vehículos anterior/nuevo por UUID ordenado, antes de bloquear el repartidor. Después se refrescan los campos relevantes dentro del bloqueo. Las operaciones documentales siguen bloqueando repartidor y luego documentos; no toman bloqueos de vehículos.
2. Si la asignación del repartidor cambió mientras esperaba, se devuelve 409 para recargar y revisar el perfil. No se aplica automáticamente la petición sobre una asignación distinta de la observada inicialmente.
3. Un vehículo de empresa debe existir y estar ACTIVO. Se comprueban tanto su vínculo a users.id como las referencias de perfiles riders.id; una referencia de otro perfil o un propietario incompatible devuelve 409. Las contradicciones históricas detectadas no se reparan eligiendo un dueño arbitrario.
4. Una reasignación libera el vínculo del vehículo anterior y establece el nuevo en la misma transacción que el perfil. Cambiar a PROPIO limpia la asignación de empresa y libera el vehículo anterior. Un fallo de validación produce rollback de la operación, incluida la creación de usuario cuando corresponda.
5. Para EMPRESA, tipo/placa/modelo se obtienen del vehículo de flota al asignarlo. Una edición directa incompatible de esos datos en un perfil ya asignado se rechaza con 409: debe desasignarse antes de editar el vehículo desde flota.
6. Un cambio real de tipo, placa, modelo, propiedad o asignación rechaza la documentación vigente y actualiza sus revisiones; ACTIVO/OCUPADO pasan a PENDIENTE y quedan desconectados. Se conservan SUSPENDIDO/INACTIVO. Reenviar exactamente la misma asignación/datos no invalida documentos aprobados sin motivo.

Los helpers no confirman transacciones: cada endpoint conserva el commit/rollback de la operación completa. No se añade un bloqueo global de flota; se serializan las filas que comparten los cambios. La garantía concurrente se verifica sobre PostgreSQL; SQLite no ofrece bloqueos de fila equivalentes.

### Edición y eliminación desde flota

Las rutas PATCH/DELETE de vehículos bloquean primero la fila del vehículo. La eliminación y los cambios efectivos de placa, tipo, modelo, año, estado o vencimiento del seguro exigen ausencia de propietario y ausencia de referencias desde perfiles. Un vehículo asignado devuelve 409 indicando desasignarlo antes. Esto evita modificar silenciosamente el vehículo que respalda documentos ya aprobados.

Color y notas pueden editarse conservando la asignación. Reenviar valores críticos sin cambios no se considera una modificación. Los campos obligatorios no admiten null y devuelven 422; insurance_expiry sigue admitiendo null, sujeto al control de asignación cuando cambia. Se conserva la normalización de placa y su comprobación previa de duplicados. La respuesta de edición vuelve a cargar explícitamente usuario/perfil para conservar los identificadores de asignación y evitar accesos lazy durante la serialización.

No se modifican frontend, modelos ORM, esquema ni migraciones. Los clientes deben gestionar 409 por ocupación, conflicto o necesidad de desasignar. El formato de las respuestas se mantiene; para EMPRESA los datos físicos reflejan la flota y no valores contradictorios del formulario. La creación rechazada no deja usuario/perfil parcial.

### Límites y próximos hallazgos

- Falta una conciliación de solo lectura de todos los históricos para identificar vínculos huérfanos/contradictorios, vehículos inactivos ya asignados y metadata física desactualizada. Las operaciones nuevas no certifican automáticamente los datos antiguos.
- Los listados heredados de disponibilidad aún se apoyan en Vehicle.rider_id; un vehículo con una referencia histórica incompleta puede anunciarse como libre aunque la nueva asignación se rechace. Debe alinearse la lectura con la validación de ambos vínculos.
- No se incorpora una restricción única adicional en Rider.assigned_vehicle_id ni triggers para escritores externos. Los bloqueos protegen las rutas de aplicación incluidas; una escritura SQL externa puede violar los vínculos.
- Sigue pendiente auditoría durable y uniforme de cambios administrativos de asignación. La auditoría propia conserva su circuito previo; no se declara un historial completo de flota.
- La comprobación previa de placa duplicada no sustituye la restricción única existente: falta tratar uniformemente sus conflictos concurrentes y revisar normalización histórica.
- No se programa automáticamente la caducidad de seguros ni se certifica validez legal de documentos. No hay reassignment/cancelación automática de entregas activas cuando un repartidor queda restringido.
- Se mantienen las deudas generales de tipado, cobertura, rendimiento bajo carga, rate limit distribuido, archivos históricos, recuperación y retención de los bloques anteriores.

El control de conflicto de asignación detecta cambios entre lectura inicial y adquisición del bloqueo en el servidor. Aún no exige una revisión esperada enviada por el formulario: no detecta por sí solo un formulario abierto antes de que comenzara la petición. Esa protección de edición obsoleta sigue pendiente.

### Evidencia final local del bloque 17

| Control | Resultado |
|---|---|
| Backend completo | **598 pruebas aprobadas**, 34 nuevas frente a 564; cuatro advertencias anteriores |
| PostgreSQL real aislado | **57 pruebas** incluidas; seis nuevas para asignaciones competidoras, liberación/reutilización, borrado, suspensión, mantenimiento y asignaciones obsoletas concurrentes |
| Pruebas nuevas restantes | 28 casos con SQLite: endpoints administrativos, estados, metadata canónica, no-op, rechazo sin vínculos parciales, creación/rollback, nulos, edición cosmética/crítica y eliminación |
| Mypy con --ignore-missing-imports | **330 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 163 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; 163 archivos de app; cero errores críticos de lint |
| Frontend | Sin cambios; se conserva su validación anterior de 183 pruebas y compilación, no repetida para este bloque backend |

PostgreSQL se ejecuta sobre una base test_* y esquemas privados por prueba. Las adiciones de columnas/tipos dentro de los fixtures solo construyen esos esquemas efímeros y no son migraciones de la aplicación. No se modifica una base de negocio. La deuda Mypy y el umbral de cobertura frontend siguen pendientes; no se declara CI global verde. El PR se publica sin borrador, sin fusión ni despliegue automáticos.

## Bloque 18 — Catálogo disponible coherente y conciliación de flota de solo lectura

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit b3518b7, con PR #259 fusionado. Rama: fix/fleet-reconciliation-readonly-v1.

### Catálogo de vehículos disponibles

GET /api/v1/vehicles/available y GET /api/v1/vehicles?available_only=true comparten ahora available_vehicle_condition: el vehículo debe estar ACTIVO, Vehicle.rider_id debe ser null y ningún perfil puede referenciarlo mediante Rider.assigned_vehicle_id. Se excluyen referencias históricas incompletas, aunque el propietario del vehículo esté ausente, y se conservan reservas de perfiles suspendidos hasta una desasignación explícita.

La ruta /available exige ACTIVO incluso sin ownership_type=EMPRESA; anteriormente podía devolver vehículos de mantenimiento o baja si se omitía ese filtro. Se mantienen filtros de tipo, límites y forma de respuesta, con desempate de orden por UUID. En el listado general, available_only=false conserva la consulta de vehículos asignados/inactivos según los filtros solicitados. Un filtro de estado incompatible con available_only=true devuelve cero candidatos.

La disponibilidad es una lectura del momento, no una reserva: una solicitud concurrente puede asignar el candidato después. La escritura debe seguir usando los controles transaccionales del bloque 17.

### Informe de conciliación

Nueva ruta: **GET /api/v1/vehicles/reconciliation**. Acceso: GERENTE y SUPERADMIN. OPERADOR, REPARTIDOR, CLIENTE y AUDITOR no acceden al informe; las rutas del catálogo conservan sus permisos anteriores. La ruta está registrada antes de /{vehicle_id} para que no se interprete como UUID de vehículo.

Parámetros:

| Parámetro | Contrato |
|---|---|
| limit | 100 por defecto; entre 1 y 500 hallazgos por página |
| code | Código opcional de la enumeración de controles; valores desconocidos devuelven 422 |
| cursor | Cursor devuelto en next_cursor; hasta 120 caracteres, formato/código/UUID validados; inválidos devuelven 422 |

El informe devuelve read_only=true, generated_at en UTC, snapshot_scope=single_statement_per_page, findings, page_count, has_more, next_cursor y checks. Cada hallazgo contiene únicamente code, entity_type, entity_id, related_id y description. No devuelve nombres, correos, placas, modelos ni documentos. Para entity_type=rider, related_id identifica el vehículo cuando existe referencia; para entity_type=vehicle, identifica users.id del vínculo propietario.

### Diccionario de hallazgos

| Código | Condición observada |
|---|---|
| COMPANY_WITHOUT_VEHICLE | Perfil EMPRESA sin vehículo asignado |
| NONCOMPANY_WITH_VEHICLE | Perfil no EMPRESA con una referencia de vehículo de flota |
| MISSING_VEHICLE | La referencia apunta a un vehículo inexistente; útil para importaciones/históricos sin integridad referencial |
| OWNER_MISMATCH | Vehicle.rider_id está ausente o difiere del usuario del perfil que lo referencia |
| MULTIPLE_RIDERS | Varios perfiles referencian el mismo vehículo; se informa cada perfil implicado |
| METADATA_MISMATCH | Tipo, placa o modelo del perfil EMPRESA difieren del vehículo; la comparación distingue null y diferencias de formato |
| INACTIVE_VEHICLE | Un perfil referencia un vehículo cuyo estado no es ACTIVO |
| OWNER_WITHOUT_PROFILE | El usuario vinculado al vehículo no tiene perfil de repartidor |
| OWNER_PROFILE_MISMATCH | El perfil del usuario vinculado al vehículo no referencia ese mismo vehículo |
| INVALID_OWNERSHIP | Propiedad del vehículo del perfil ausente o distinta de PROPIO/EMPRESA |

Una entidad puede producir varios hallazgos. page_count cuenta hallazgos de la página, no vehículos/repartidores ni el total global. checks enumera los controles disponibles, incluso al filtrar por un código. Una página vacía no certifica documentación, legalidad ni toda la salud del sistema.

### Garantía de lectura y consistencia

Se ejecuta una sola sentencia SELECT con CTE/UNION ALL por página, sin cargar entidades ORM, geometría ni relaciones. El servicio no hace commit, flush, delete, UPDATE ni FOR UPDATE; no_autoflush evita persistir cambios pendientes de una sesión llamadora. La respuesta usa Cache-Control: private, no-store y Vary: Authorization; el middleware existente excluye las rutas API/autenticadas de caché compartida.

PostgreSQL ofrece una vista consistente de los controles dentro de esa sentencia. La paginación por clave ordena código e identificadores y lee hasta limit+1 resultados para indicar si queda otra página. No emite un conteo global separado ni conserva una transacción histórica entre peticiones.

**Límite de snapshot:** cada página consulta el estado actual. Si cambian vínculos entre páginas, hallazgos pueden desaparecer, cambiar de clave o aparecer antes del cursor. No se promete una exportación inmutable ni un inventario completo de un instante al recorrer varias peticiones. Para una exportación histórica consistente haría falta un snapshot durable o una tarea específica. generated_at identifica la generación de la respuesta, no una certificación durable de los registros.

### Alcance y siguientes prioridades

No se cambian modelos, esquema, migraciones ni frontend. Este bloque habilita diagnóstico mediante API; no incorpora una pantalla de conciliación ni botones de reparación. No se ejecuta el informe sobre datos de producción durante el desarrollo y no se corrigen históricos automáticamente.

Quedan pendientes revisión operativa de hallazgos reales, reparaciones explícitas con revisión esperada y auditoría durable, protección de formularios obsoletos de asignación, conflicto uniforme de placas, caducidad de seguros y continuidad de entregas activas. El informe no revisa bytes/documentos, aprobaciones humanas, permisos de archivos, balances ni validez legal.

El límite controla la respuesta, no el coste total del escaneo/agregación SQL. No se ha medido un plan de ejecución ni latencia a escala de producción; hacen falta mediciones, índices efectivos y límites operativos antes de afirmar rendimiento bajo carga. Se conservan la deuda de Mypy, cobertura y los demás pendientes de producción previamente documentados.

Al cambiar el filtro code debe iniciarse de nuevo sin cursor. El cursor es una clave de recorrido de los resultados actuales, no una revisión del inventario ni una credencial de autorización.

### Evidencia final local del bloque 18

| Control | Resultado |
|---|---|
| Backend completo | **639 pruebas aprobadas**, 41 nuevas frente a 598; cuatro advertencias anteriores |
| PostgreSQL real aislado | **61 pruebas** incluidas; cuatro nuevas sobre READ ONLY, enums/comparación de metadata, duplicados/paginación, visibilidad de commits y desaparición de hallazgos entre páginas |
| Nuevas pruebas restantes | 37 casos HTTP/SQLite: diez códigos, catálogos/filtros, paginación, permisos/autenticación, no-store, parámetros inválidos y una sola consulta sin mutaciones/autoflush |
| Mypy con --ignore-missing-imports | **330 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 164 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; 164 archivos de app; cero errores críticos de lint |
| Frontend | Sin cambios; validación anterior de 183 pruebas y compilación conservada, no repetida en este bloque backend |

Las pruebas usan SQLite temporal y una base PostgreSQL test_* con esquemas privados. No se consulta ni repara una base de negocio. La prueba PostgreSQL ejecuta el servicio dentro de SET TRANSACTION READ ONLY; las pruebas HTTP verifican que roles denegados no llegan a consultar datos y que la salida no incluye campos personales. No se declara CI global verde ni producción lista: persisten Mypy y cobertura pendientes. El PR se publica sin borrador, sin fusión ni despliegue automáticos.

## Bloque 19 — Precondiciones de estado para formularios de asignación

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit 4a18785, con PR #260 fusionado. Rama: fix/fleet-form-preconditions-v1.

### Problema y contrato nuevo

El bloque 17 detectaba cambios entre la lectura inicial del servidor y la adquisición de los bloqueos, pero un formulario abierto anteriormente podía enviar datos antiguos después de una reasignación ya confirmada. Se añade assignment_revision a las respuestas serializadas de repartidores y expected_assignment_revision a RiderUpdate.

La revisión es SHA-256 de la identidad del perfil/usuario y sus campos de vehículo: propiedad, vehículo asignado, tipo, placa y modelo. El servidor compara el valor esperado después de bloquear vehículos/repartidor y refrescar esos campos, antes de modificar vínculos, documentos o campos personales del mismo envío.

- PATCH /api/v1/riders/{rider_id} y PUT /api/v1/riders/me exigen la revisión cuando el payload aplicado incluye campos de vehículo; los no-op que incluyen esos campos también se condicionan.
- Una revisión ausente o distinta del estado actual devuelve 409. Un formato distinto de 64 caracteres hexadecimales minúsculos devuelve 422.
- La revisión se excluye del payload aplicado al ORM: no se guarda como un atributo transitorio ni como columna.
- Las actualizaciones exclusivamente ajenas al vehículo conservan su contrato sin revisión de asignación. Crear un repartidor no requiere una revisión anterior inexistente.
- Las lecturas individuales y propias refrescan metadata previamente cargada en la sesión para devolver el estado actual.

No se reutiliza Rider.version, reservado para concurrencia financiera, ni updated_at, modificado por GPS y otras operaciones. Ubicación, conexión, estado administrativo, fechas y balance no invalidan por sí mismos el formulario de flota. La invalidación documental y preservación de suspensiones del bloque 17 permanecen vigentes.

### Editor de gerencia

Se corrige riderService.updateRider: enviaba PUT a /riders/{id}, mientras que el endpoint real acepta PATCH. El servicio conserva una copia del payload al retirar datos propios incompatibles con una asignación de empresa; no modifica el objeto del llamador.

RiderEditModal captura el perfil completo al abrir y conserva tanto los datos editados como la revisión inicial. Un refresco de props para el mismo perfil no reemplaza silenciosamente la revisión ni reinicia el borrador. La carga del catálogo tampoco cambia la selección del formulario. El vehículo actualmente asignado puede conservarse aunque no aparezca entre los disponibles.

Ante 409 el guardado queda bloqueado. El operador puede cerrar y recargar para revisar el estado vigente; no se descarga una revisión nueva para reenviar automáticamente los cambios antiguos. Cerrar/reabrir inicia un borrador nuevo. Las respuestas de una petición que ya no corresponde al borrador activo no cierran ni confirman otro editor.

El payload tiene tipo UpdateRiderPayload y declara tier/revisión. Además, el backend persiste phone/first_name/last_name administrativos en el User relacionado: antes los asignaba como atributos no persistidos del objeto Rider. La prueba nueva verifica persistencia real del teléfono y ausencia de cambios parciales ante conflicto de flota.

### Perfil propio

El formulario carga la revisión junto con los datos de la API, sin reemplazarla por refrescos del mismo usuario en el store de autenticación. El fallback del store permite visualizar datos, pero no habilita un guardado de vehículo sin revisión del servidor.

Un conflicto bloquea nuevos envíos y solicita Recargar perfil. Esta acción explícita repone datos y revisión juntos; no reenvía la edición anterior. El guardado también se deshabilita mientras se recarga. El 409 no se interpreta como si los documentos hubieran sido reiniciados ni redirige a documentos por ese motivo.

### Compatibilidad y límites de la garantía

Backend y frontend requieren publicación coordinada. Los clientes anteriores que escriban campos de vehículo sin expected_assignment_revision recibirán 409 y deben recargar con la versión nueva del cliente. La lectura sigue siendo compatible; el campo TypeScript es opcional para representar respuestas históricas, pero los servicios validan la revisión antes de enviar una escritura de flota.

**Es una precondición del estado actual, no un contador monotónico ni una prueba de eventos.** Si el sistema vuelve exactamente a los mismos valores de vehículo, la huella vuelve a ser la misma (caso A→B→A). No detecta por sí sola una historia intermedia ni acredita revisión humana. No es una credencial de autorización y no sustituye los permisos existentes.

La huella tampoco incluye la metadata del vehículo candidato todavía libre: la asignación toma los datos canónicos actuales bajo bloqueo. Si se requiere confirmar exactamente la ficha del candidato que vio el operador, hace falta una precondición adicional sobre ese vehículo. Tampoco protege de forma general ediciones concurrentes de teléfono, nombres o nivel cuando el estado de flota no cambia; queda pendiente un contrato de concurrencia específico de esos datos.

No se modifica esquema, modelos ni migraciones. Los escritores SQL externos o servicios alternativos no incorporados pueden modificar datos fuera del protocolo; no se declara un historial durable de asignaciones. Sigue pendiente auditoría uniforme de actor/cambio, reparaciones explícitas de históricos, conflictos de placas y continuidad de entregas activas.

### Evidencia final local del bloque 19

| Control | Resultado |
|---|---|
| Backend completo | **657 pruebas aprobadas**, 18 nuevas frente a 639; cuatro advertencias anteriores |
| PostgreSQL real aislado | **64 pruebas** incluidas; tres nuevas para formulario anterior, dos gestores con la misma revisión y cambio físico mientras una petición espera el bloqueo |
| Nuevas pruebas restantes de backend | 15 casos HTTP/SQLite: revisión ausente/malformada/incorrecta en ambas rutas, conflictos sin escrituras parciales, independencia GPS/finanzas, teléfono persistido y semántica A→B→A |
| Frontend | **204 pruebas aprobadas** en 18 suites; 21 nuevas para servicios, modal y perfil propio |
| TypeScript / ESLint / Next.js build | Aprobados; advertencias anteriores conservadas |
| Mypy con --ignore-missing-imports | **330 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 165 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; 165 archivos de app; cero errores críticos de lint |
| Cobertura frontend | Statements **9,72 %**, branches **8,23 %**, functions **6,77 %**, lines **9,82 %** |

La suite frontend pasa, pero su comando con cobertura mantiene salida con error por el umbral global del 50 %. Mypy conserva su deuda previa. No se declara CI global verde ni producción lista.

Las pruebas anteriores de flota se adaptan para enviar una revisión capturada antes de su operación. Los nuevos casos de conflicto conservan expresamente la revisión anterior; el frontend comprueba que no obtiene ni reenvía automáticamente una revisión nueva ante error. Las pruebas usan bases temporales/esquemas test_* aislados, nunca datos de negocio. No se aplican migraciones, pagos ni despliegues. El PR se publica listo para revisión, sin borrador; no se fusiona automáticamente.

## Bloque 20 — Auditoría transaccional de cambios de flota

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit 74dd458, con PR #261 fusionado. Rama: fix/fleet-audit-transactions-v1.

### Problema y resultado

La edición propia tenía una auditoría parcial dentro de un try/except que podía continuar sin registrar el cambio. La edición administrativa y la creación administrativa de perfiles no compartían ese registro. Se incorpora fleet_audit sobre la tabla audit_logs existente, con eventos RIDER_FLEET v1 dentro de la misma transacción SQL que el cambio de perfil, vínculos y documentos.

Rutas cubiertas:

| Ruta | source del evento | Alcance |
|---|---|---|
| POST /api/v1/riders | admin_create | Creación administrativa de perfil, propio o de empresa |
| PATCH /api/v1/riders/{id} | rider_patch | Cambios reales de vehículo/asignación autorizados en esa ruta |
| PUT /api/v1/riders/me | self_profile | Cambios reales de vehículo/asignación desde el perfil propio |

source identifica la ruta, no acredita por sí mismo un rol administrativo: la autorización previa del endpoint sigue siendo la autoridad. El actor se obtiene de la sesión autenticada, nunca del cuerpo enviado por el cliente.

### Contenido durable del evento

Se guarda el identificador del actor y su rol observado, resource_type=Rider y resource_id del perfil. No se duplica el correo, nombre, teléfono, tokens, IP ni user-agent del actor. El antes/después recoge usuario del perfil, propiedad, vehículo asignado, tipo, placa, modelo, estado, conexión, revisión de asignación y vínculos de los vehículos implicados.

Los datos nuevos incluyen event_family=RIDER_FLEET, schema_version=1, source, operation, changed_fields y documents_invalidated. Este último cuenta los registros documentales procesados/marcados RECHAZADO, no solo los que estaban aprobados. Se conserva status_changed_to para compatibilidad con la traza propia anterior. La hora occurred_at_utc lleva Z explícita y coincide con created_at almacenado como UTC naive según el modelo existente; identifica la generación del evento antes del commit, no una hora certificada de confirmación de PostgreSQL.

| operation | ActionType existente | Significado |
|---|---|---|
| CREATE | CREATE | Perfil creado desde administración |
| ASSIGN | ASSIGN | Primera asignación de empresa desde un perfil sin asignación |
| REASSIGN | REASSIGN | Sustitución de un vehículo asignado por otro |
| UNASSIGN | UPDATE | Liberación de la asignación de empresa |
| VEHICLE_UPDATE | UPDATE | Cambio de datos físicos/propiedad conservando la clasificación anterior de vínculos |
| LINK_REPAIR | UPDATE | Corrección de un vínculo incompleto inequívoco durante un guardado autorizado |

Los registros contienen datos personales operativos, incluidos placa e identificadores, y llevan contains_personal_data=true. No se presenta este historial como anonimizado ni como cumplimiento legal certificado.

### Transacción y fallos

El estado anterior se copia después de obtener bloqueos y validar la revisión esperada, antes de modificar los vínculos. Tras aplicar el cambio se invalidan documentos, se actualiza la disponibilidad y se registra el estado resultante. La inserción del evento hace flush, sin commit independiente. El endpoint confirma la operación completa.

Si una operación SQL de auditoría falla antes del commit, se hace rollback y se devuelve 503 sin exponer el error SQL. No se confirma el cambio de negocio sin su evento. Un rollback del llamador después del flush de auditoría también elimina ambos. El almacenamiento/permisos de audit_logs son una dependencia obligatoria de estas escrituras; si están indisponibles, las operaciones cubiertas dejan de confirmarse.

Las peticiones denegadas o con revisión desactualizada no producen eventos exitosos de cambio. Los no-op reales no añaden eventos ni invalidan documentos otra vez. Este flujo no registra todos los intentos fallidos ni sustituye los logs operativos de errores.

**Vínculo incompleto:** el servicio ya podía completar Vehicle.rider_id cuando había una única referencia compatible desde el perfil. Antes ese caso podía pasar como no-op. Ahora se considera un cambio, queda registrado como LINK_REPAIR e invalida documentación para revisión. No se toma posesión de vehículos con propietario contradictorio ni de referencias de otro perfil; esos casos siguen rechazándose.

Se eliminan las impresiones heredadas de correo/placa del cambio propio y el try/except que podía ocultar la ausencia de auditoría. Se conservan las revisiones y bloqueos de los bloques anteriores.

### Consulta y panel

Los eventos se consultan en el endpoint existente GET /api/v1/audit, filtrando resource_type=Rider y resource_id del perfil; search=RIDER_FLEET permite localizar esta familia. La API de lectura conserva sus permisos de GERENTE/SUPERADMIN y expone old_values/new_values existentes, sin añadir una API de escritura de eventos.

El panel muestra el identificador del usuario cuando falta su correo, en lugar de atribuir una acción humana a SYSTEM. Los eventos que sí tienen correo conservan esa presentación; SYSTEM se usa cuando no hay identidad. Para eventos nuevos se muestra la hora occurred_at_utc explícita; los antiguos conservan el fallback de fecha previo.

### Límites y próximos pendientes

No se modifica esquema, modelos ni migraciones. El registro SQL es durable tras un commit confirmado, pero no es inmutable frente a un administrador de base de datos ni está firmado/encadenado criptográficamente. No reconstruye autores ni estados históricos anteriores a este bloque.

Un fallo de comunicación durante commit puede dejar incierto el acuse para el cliente: negocio y auditoría pertenecen a la misma transacción, pero no se añade una clave de idempotencia de petición ni una garantía universal exactamente-una-vez. Debe consultarse el estado antes de repetir a ciegas.

Quedan fuera los cambios exclusivamente de nombres/teléfono/nivel, las ediciones de inventario de vehículos, la inscripción propia de auth/register y escritores alternativos/SQL externos que no usan estas rutas. No se certifica que toda escritura del sistema esté auditada. Siguen pendientes retención, exportación/anónimos y políticas de acceso/operación de datos personales, revisión esperada de la ficha del vehículo candidato, concurrencia del perfil ajeno a flota y reparación operativa de históricos. No se cancelan ni reasignan entregas activas automáticamente.

### Evidencia final local del bloque 20

| Control | Resultado |
|---|---|
| Backend completo | **671 pruebas aprobadas**, 14 nuevas frente a 657; cuatro advertencias anteriores |
| PostgreSQL real aislado | **68 pruebas** incluidas; cuatro nuevas para persistencia tras commit, rechazo por CHECK real de auditoría, rollback posterior al flush y dos cambios con la misma revisión |
| Nuevas pruebas restantes de backend | 10 casos HTTP/SQLite: antes/después, actor distinto del usuario del perfil, rutas/orígenes, no-op, conflicto/denegación, corrección de vínculo, creación y tres fallos reales de inserción con rollback |
| Frontend | **206 pruebas aprobadas** en 19 suites; dos nuevas para identidad humana/sistema/legado y fecha UTC explícita |
| TypeScript / ESLint / Next.js build | Aprobados; advertencias anteriores conservadas |
| Mypy con --ignore-missing-imports | **329 errores en 52 archivos**, uno menos que la base y sin diagnósticos nuevos por archivo/mensaje; 166 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; 166 archivos de app; cero errores críticos de lint |
| Cobertura frontend | Statements **10,19 %**, branches **8,85 %**, functions **7,16 %**, lines **10,31 %** |

El comando frontend con cobertura sigue fallando por el umbral global del 50 %, aunque las pruebas pasan. Mypy mantiene deuda anterior; no se declara CI global verde ni producción lista.

Los fallos de auditoría se provocan con triggers SQLite y una restricción CHECK real en PostgreSQL aislado. No se intervienen datos de negocio ni se ejecutan cambios de esquema sobre producción. La adaptación de DDL SQLite para el default de UUID solo afecta al fixture y restaura el metadata original. No se aplican migraciones ni se despliega. El PR se publica sin borrador, sin fusión automática.

## Bloque 21 — Revisión esperada del vehículo seleccionado

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit de555ee, con PR #262 fusionado. Rama: fix/selected-vehicle-preconditions-v1.

### Problema y contrato de lectura

La precondición del bloque 19 protege el estado del repartidor, pero no la ficha del vehículo candidato. Un vehículo libre podía cambiar de placa/modelo/tipo después de mostrarse en el catálogo y ser asignado usando datos distintos de los elegidos por el operador.

Las respuestas de vehículos incorporan revision. El vehículo ya asignado, incluido dentro del perfil del repartidor, también devuelve su revisión. Es SHA-256 de id, tipo, placa, modelo, color, año, estado, vencimiento del seguro y usuario vinculado. No incluye notas administrativas ni updated_at/created_at, para no invalidar una selección por cambios de notas/fechas que no alteran la ficha protegida.

### Precondición de escritura

RiderCreate y RiderUpdate aceptan expected_vehicle_revision: 64 caracteres hexadecimales minúsculos. Al crear o guardar un perfil EMPRESA se exige la revisión del vehículo asignado, incluso cuando se conserva la asignación actual. Para PROPIO no se requiere ficha de empresa.

- Ausencia o diferencia respecto de la ficha actual: 409 y solicitud de recarga/reselección.
- Formato inválido: 422.
- La comparación ocurre bajo el bloqueo del vehículo, después del bloqueo/refresco del repartidor en las actualizaciones y antes de cambiar vínculos o documentos.
- La creación administrativa toma el mismo bloqueo; un rechazo revierte también el usuario/perfil parcialmente preparados.
- La revisión del repartidor sigue siendo necesaria en actualizaciones de flota. Las dos condiciones protegen estados distintos; una revisión fresca del repartidor no autoriza una ficha candidata antigua.
- Las reglas de estado ACTIVO, propietario y referencias de otros perfiles permanecen vigentes. La revisión no sustituye esas validaciones.

La auditoría RIDER_FLEET guarda selected_vehicle_revision con la revisión aceptada para EMPRESA. Para PROPIO se guarda null, sin presentar una huella suministrada pero no comprobada como si hubiera sido validada. Al asignar un vehículo libre cambia su propietario y, por tanto, su revisión resultante: el valor auditado identifica la ficha anterior a esa asignación.

### Formularios y servicios

El modal captura una copia del candidato en el momento de selección, incluido el caso de selección inicial. Un refresco del catálogo padre no sustituye esa copia ni la revisión que se enviará. El vehículo de empresa que ya estaba asignado usa la revisión incluida en el perfil capturado al abrir. Tras un conflicto se conserva el bloqueo de guardado y la recarga explícita del bloque 19.

El registro de repartidores captura la ficha cargada/seleccionada y adjunta su revisión. Un 409 bloquea nuevos envíos; Recargar vehículos limpia la selección anterior y muestra datos/revisión actuales antes de un nuevo guardado manual. No se reenvía automáticamente la petición rechazada. El guardado queda deshabilitado mientras se carga el catálogo o falta candidato. La presentación del candidato seleccionado conserva su copia, sin cambiar silenciosamente sus datos mientras el formulario está abierto.

El perfil propio conserva la revisión de su vehículo de empresa junto con los demás datos cargados. Los servicios de creación/edición validan la presencia/forma de la huella pertinente sin obtener una ficha nueva en el momento de enviar.

El store de repartidores valida la revisión al crear y delega la edición al servicio compartido. Se corrige allí la llamada PUT heredada a /riders/{id} por PATCH, que es el método existente; las precondiciones viajan con el comando. La política restante de creación del store se conserva. Los logs de error de vehículos y de creación del store dejan de imprimir errores Axios completos con posibles cabeceras de autorización.

### Compatibilidad y límites

Backend y frontend requieren publicación coordinada. Los clientes anteriores sin expected_vehicle_revision reciben 409 en escrituras EMPRESA, incluidas las que conservan vehículo. Los clientes actualizados pueden obtener la revisión desde el catálogo/detalle o el vehículo incorporado al perfil. Las respuestas mantienen los demás campos. No se modifica esquema, modelos ni migraciones.

Es una huella de estado actual, no un contador monotónico, firma, credencial ni comprobante de revisión humana. Si los datos vuelven exactamente al estado anterior, la huella también puede repetirse. No acredita una historia intermedia ni constituye una reserva de vehículo: los bloqueos y comprobaciones al escribir siguen siendo necesarios.

Se comprueba que el vencimiento del seguro no haya cambiado desde la selección; no se añade una certificación legal ni una regla automática que prohíba todo seguro caducado. No se incorporan precondiciones a las ediciones/eliminaciones del inventario mismo ni se cierran los pendientes de concurrencia de nombres/teléfono/nivel, retención de auditoría, reparación de históricos o continuidad de entregas activas.

### Evidencia final local del bloque 21

| Control | Resultado |
|---|---|
| Backend completo | **692 pruebas aprobadas**, 21 nuevas frente a 671; cuatro advertencias anteriores |
| PostgreSQL real aislado | **71 pruebas** incluidas; tres nuevas sobre ficha cambiada antes de la petición, cambio durante espera del bloqueo y dos perfiles compitiendo por la misma ficha libre |
| Nuevas pruebas restantes de backend | 18 casos HTTP/SQLite: precondición ausente/malformada/incorrecta en tres rutas, siete cambios de ficha, revisión visible/auditada y notas sin invalidación de la huella |
| Frontend | **218 pruebas aprobadas** en 21 suites; 12 nuevas para servicios/store, selección capturada, catálogo refrescado, recarga explícita y logs sin credenciales |
| TypeScript / ESLint / Next.js build | Aprobados; advertencias anteriores conservadas |
| Mypy con --ignore-missing-imports | **329 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 167 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; 167 archivos de app; cero errores críticos de lint |
| Cobertura frontend | Statements **11,95 %**, branches **9,99 %**, functions **9,16 %**, lines **12,08 %** |

La suite frontend pasa, pero su comando con cobertura sigue fallando por el mínimo global del 50 %. Mypy conserva deuda anterior; no se declara CI global verde ni producción lista.

Las pruebas existentes se adaptan para presentar revisiones capturadas antes de su operación; los nuevos conflictos usan expresamente una revisión anterior y prueban ausencia de cambios parciales y de eventos de éxito. Las pruebas de formulario verifican que no se consulta una ficha fresca para reenviar automáticamente el comando. Se usan SQLite temporal y PostgreSQL test_* con esquemas aislados, nunca datos de negocio. No se aplican migraciones ni despliegues. El PR se publica sin borrador y no se fusiona automáticamente.

## Bloque 22 — Edición, baja y eliminación de inventario con precondición

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit db45c21, con PR #263 fusionado. Rama: fix/vehicle-inventory-preconditions-v1.

### Revisión de selección y revisión de edición

La revisión del bloque 21 excluye notas para no invalidar una selección de candidato por cambios administrativos. Usarla para editar inventario permitiría sobrescribir notas desde un formulario antiguo. Se añade edit_revision: SHA-256 de la revisión de selección y las notas actuales. Protege todos los campos editables de inventario, además del usuario vinculado.

revision conserva su contrato de selección. edit_revision es la precondición para editar, dar de baja o eliminar la ficha; las dos huellas no son intercambiables. Ambas se devuelven en las respuestas de vehículos. No se añaden columnas ni se reutiliza una versión financiera.

### Contrato HTTP

| Operación | Requisito |
|---|---|
| GET /api/v1/vehicles/{id} | Refresca metadata de sesión, devuelve edit_revision y ETag entre comillas; Cache-Control: private, no-store y Vary: Authorization |
| PATCH /api/v1/vehicles/{id} | If-Match con edit_revision observada, comprobada después de bloquear el vehículo y antes de modificarlo |
| Baja lógica | PATCH de status=BAJA con la misma precondición |
| DELETE /api/v1/vehicles/{id} | If-Match comprobado bajo bloqueo antes de validar desasignación y eliminar |

La cabecera acepta una huella hexadecimal minúscula de 64 caracteres, cruda o entre comillas. Ausencia o estado distinto devuelven 409; formato incorrecto, comodín, lista o etiqueta débil devuelven 422. No se admite If-Match=* como forma de omitir la revisión concreta. Una ficha eliminada por otro proceso puede devolver 404.

Los permisos previos siguen vigentes: solo GERENTE/SUPERADMIN pueden escribir inventario. La huella no autoriza una operación ni sustituye la exigencia de desasignar antes de cambios críticos o eliminación. Notas/color siguen pudiendo editarse en un vehículo asignado si la revisión vigente coincide. Un cambio de propietario invalida incluso una edición cosmética abierta anteriormente.

ETag representa el estado editable que usa esta precondición; no se incorpora una caché ni un mecanismo de 304 por bytes de toda la respuesta con datos derivados de usuario. Las fechas internas y los nombres del usuario relacionado no forman parte de la huella de campos editables.

### Formularios y servicios

El editor conserva id y edit_revision cargados junto con el formulario. Guardar usa ese id capturado, no un parámetro de ruta que pudiera haber cambiado mientras terminaba una petición. Una carga obsoleta se descarta al navegar a otra ficha. La respuesta de un guardado anterior tampoco confirma ni redirige otro formulario activo.

Tras 409 se bloquea guardar y se mantiene la indicación de conflicto aunque se edite un campo. Recargar ficha es una acción explícita que repone datos y revisión juntos; no reenvía automáticamente la edición anterior. La baja lógica captura una copia del registro al abrir la confirmación. Un refresco de la lista no reemplaza la revisión de ese diálogo; ante conflicto se exige cerrar/actualizar antes de intentarlo de nuevo.

vehicleService.update, deactivate y delete validan la revisión capturada antes de enviar y construyen If-Match entre comillas. No consultan una ficha nueva para reemplazar la precondición durante el guardado. delete queda protegido aunque no se añada una pantalla nueva de borrado físico.

Se corrige el vaciado de campos opcionales del editor: limpiar notas o fecha de seguro envía null. Antes se enviaba undefined, por lo que PATCH conservaba silenciosamente el dato anterior. VehicleUpdateInput admite estas anulaciones sin cambiar el contrato de creación.

### Compatibilidad y límites

Se requiere publicación coordinada de backend/frontend. Los clientes anteriores que editen, den de baja o eliminen sin If-Match reciben 409. Los listados y la creación conservan sus contratos, con el nuevo campo de lectura. Las revisiones de asignación del repartidor y del candidato continúan siendo independientes y necesarias en sus rutas correspondientes.

No se modifican esquema, modelos ni migraciones. Las huellas comparan estado, no cuentan eventos: un retorno exacto A→B→A puede repetir una revisión. No son recibos firmados, credenciales ni una garantía universal exactamente-una-vez. La pérdida del acuse de commit puede dejar una operación confirmada con respuesta incierta; la precondición evita sobrescribir cambios posteriores, pero no certifica al cliente ese acuse.

Este bloque protege la concurrencia del inventario; todavía no incorpora una auditoría transaccional específica de creación/edición/baja/borrado de vehículos. Siguen pendientes esa traza, el tratamiento uniforme de colisiones de placa, retención de auditoría, caducidad de seguros, concurrencia ajena a flota y continuidad de entregas activas. No se modifican datos de negocio ni se despliega automáticamente.

### Evidencia final local del bloque 22

| Control | Resultado |
|---|---|
| Backend completo | **716 pruebas aprobadas**, 24 nuevas frente a 692; cuatro advertencias anteriores |
| PostgreSQL real aislado | **75 pruebas** incluidas; cuatro nuevas: editores con la misma revisión, notas cambiadas durante espera del bloqueo, edición/borrado concurrentes y cambio de propietario |
| Nuevas pruebas restantes de backend | 20 casos HTTP/SQLite: precondiciones inválidas/ausentes, notas y revisión de selección independientes, tags crudos/citados, vaciado explícito, segundo editor, revisión equivocada y permisos |
| Frontend | **231 pruebas aprobadas** en 23 suites; 13 nuevas para servicios, editor, cambios de ruta y confirmación de baja frente a refresco/conflicto |
| TypeScript / ESLint / Next.js build | Aprobados; advertencias anteriores conservadas |
| Mypy con --ignore-missing-imports | **329 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 167 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; 167 archivos de app; cero errores críticos de lint |
| Cobertura frontend | Statements **13,35 %**, branches **11,15 %**, functions **10,43 %**, lines **13,48 %** |

Las pruebas frontend pasan, pero el comando con cobertura mantiene salida con error por el umbral global del 50 %. Mypy conserva deuda anterior; no se declara CI global verde ni producción lista.

Las pruebas existentes presentan una revisión obtenida antes de su escritura; los casos nuevos conservan expresamente un tag antiguo para comprobar rechazo sin sobrescritura. Las carreras se ejecutan en PostgreSQL test_* con esquemas privados y las pruebas HTTP en SQLite temporal, sin datos de negocio. No se aplican migraciones ni despliegues. El PR se publica sin borrador y no se fusiona automáticamente.

## Bloque 23 — Auditoría transaccional del inventario de vehículos

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit 203731c, con PR #264 fusionado. Rama: fix/vehicle-inventory-audit-v1.

### Problema y rutas cubiertas

Los bloques anteriores protegían asignaciones e inventario contra sobrescrituras, pero las operaciones de inventario no compartían una traza durable. Se incorpora vehicle_inventory_audit usando la tabla audit_logs existente; no se crea una tabla ni una migración nuevas.

| Ruta | Evento |
|---|---|
| POST /api/v1/vehicles | CREATE, con el estado creado |
| PATCH /api/v1/vehicles/{id} | UPDATE, STATUS_CHANGE o DEACTIVATE según los campos realmente modificados |
| DELETE /api/v1/vehicles/{id} | DELETE, conservando el estado anterior aunque desaparezca la fila |

Se mantienen If-Match, los bloqueos de vehículo, permisos de GERENTE/SUPERADMIN y los controles de desasignación. El registro de auditoría no permite omitir una revisión ni conceder acceso a otro rol.

### Datos registrados

El actor se toma del usuario autenticado: user_id y rol observado, sin duplicar correo/nombre, IP, user-agent ni cabeceras de autenticación. resource_type=Vehicle y resource_id conserva el UUID del vehículo sin depender de una FK hacia la fila que puede eliminarse.

old_values contiene la ficha anterior o null en una creación. new_values contiene event_family=VEHICLE_INVENTORY, schema_version=1, source=vehicle_inventory, operation, vehicle_id, changed_fields, occurred_at_utc y state. state contiene la ficha resultante; es null cuando se elimina físicamente.

La ficha registrada incluye tipo, placa, modelo, color, año, estado, seguro, notas, usuario vinculado, revision y edit_revision. Se conservan además created_at/updated_at como UTC explícito según la convención de timestamps del modelo. El evento lleva contains_personal_data=true: la placa, identificadores y notas son datos operativos que requieren gestión de retención/acceso. No se presenta el contenido como anonimizado.

| operation | ActionType |
|---|---|
| CREATE | CREATE |
| UPDATE | UPDATE |
| STATUS_CHANGE | STATUS_CHANGE |
| DEACTIVATE, cuando el nuevo estado es BAJA | STATUS_CHANGE |
| DELETE | DELETE |

Si un PATCH cambia estado y otros datos, la clasificación de estado no oculta los demás campos: changed_fields y las dos fichas conservan el conjunto completo. Se omiten eventos cuando los campos materiales editables no cambian; una actualización interna de updated_at no se considera por sí sola una edición de inventario a auditar.

### Atomicidad y lectura después del borrado

El estado anterior se captura bajo bloqueo después de comprobar If-Match. La escritura/eliminación y el INSERT de auditoría usan la misma sesión/transacción. El servicio hace flush, nunca commit independiente; el endpoint confirma ambos juntos.

Un fallo SQL durante el registro revierte la operación y devuelve 503 con mensaje genérico, sin revelar la causa SQL. Una inserción de auditoría rechazada restaura también un vehículo que ya había sido eliminado dentro de la transacción. Un rollback posterior al flush del evento elimina la traza y revierte el negocio. No se generan eventos de éxito para conflictos, denegaciones o no-op materiales.

La tabla audit_logs y los permisos de INSERT son ahora una dependencia obligatoria también para estas escrituras de inventario. Una indisponibilidad impide confirmar la operación, en lugar de guardar un cambio sin traza.

Los registros se consultan en GET /api/v1/audit con resource_type=Vehicle y resource_id del vehículo. search=VEHICLE_INVENTORY localiza la familia mediante la descripción. El historial sigue disponible después de que GET /vehicles/{id} devuelva 404. El panel existente ya admite la identidad por UUID y occurred_at_utc; no se modifica frontend en este bloque.

### Alcance y límites

No se modifica esquema, modelos, precondiciones, forma de respuesta ni frontend. No se reconstruye la historia anterior a esta versión ni se añaden reparaciones/undo automáticos de vehículos borrados. La fecha del evento se genera antes del commit y no es una certificación de su instante de confirmación.

La historia SQL no es inmutable frente a un administrador de base de datos, ni está firmada o encadenada. La transacción garantiza la pertenencia conjunta de negocio y evento, pero no una garantía universal exactamente-una-vez ante pérdida del acuse del commit. Debe consultarse estado/historial antes de reenviar a ciegas.

Quedan pendientes retención y gestión de datos personales, tratamiento uniforme de colisiones de placa, validaciones operativas de seguros, concurrencia de datos personales/nivel y continuidad de entregas activas. Los scripts/SQL externos que no usan estas rutas no quedan automáticamente auditados. No se modifican bases de negocio ni se despliega o fusiona automáticamente.

### Evidencia final local del bloque 23

| Control | Resultado |
|---|---|
| Backend completo | **731 pruebas aprobadas**, 15 nuevas frente a 716; cuatro advertencias anteriores |
| PostgreSQL real aislado | **79 pruebas** incluidas; cuatro nuevas para historia tras commit/borrado, restauración del borrado por fallo CHECK de auditoría, rollback externo tras flush y competencia por una revisión |
| Nuevas pruebas restantes | 11 casos HTTP/SQLite: ciclo de inventario completo, consulta tras eliminación, estado/baja, no-op/conflicto, cuatro fallos de inserción con rollback y cuatro roles no autorizados |
| Mypy con --ignore-missing-imports | **329 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 168 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; 168 archivos de app; cero errores críticos de lint |
| Frontend | Sin cambios; se conserva la validación anterior de **231 pruebas**, TypeScript, lint y compilación, no repetida en este bloque backend |

Los fallos se fuerzan mediante un trigger SQLite y una restricción CHECK real de PostgreSQL. Las pruebas nativas vuelven a abrir sesiones para comprobar persistencia o rollback, y verifican que un vehículo eliminado por una transacción fallida siga disponible con la misma revisión. Se usan bases temporales/test_* y esquemas aislados; no se intervienen datos de negocio.

Mypy conserva deuda previa y la cobertura frontend anterior (**13,48 % de líneas**) sigue bajo el mínimo global del 50 %. No se declara CI global verde ni producción lista. No se aplican migraciones ni despliegues. El PR se publica sin borrador y no se fusiona automáticamente.

## Bloque 24 — Normalización y conflictos concurrentes de placas

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit ad3f767, con PR #265 fusionado. Rama: fix/vehicle-plate-conflicts-v1.

### Problema resuelto y contrato de entrada

Las altas y ediciones consultaban placas antes de escribir, pero esa consulta por sí sola no protegía dos solicitudes simultáneas. Una colisión del índice UNIQUE podía terminar como error interno o como indisponibilidad de auditoría. La búsqueda también podía fallar al encontrar varias filas históricas con diferencias de mayúsculas o espacios.

POST /api/v1/vehicles y PATCH /api/v1/vehicles/{id} comparten ahora un normalizador: elimina espacios ASCII exteriores (espacio, tabulación, CR, LF, tabulación vertical y salto de página), acepta entre 1 y 20 letras ASCII, números o guiones, y guarda mayúsculas. Rechaza vacío, espacios interiores, caracteres no ASCII y otros símbolos con 422. La validación se realiza antes de las escrituras y conserva las reglas de campos obligatorios.

Esta restricción hace explícita en API la política de caracteres ya utilizada por el servicio frontend. Las integraciones que antes enviaban otros caracteres deberán adecuar sus solicitudes; no se transforma ni elimina automáticamente información histórica.

### Reserva de placa dentro de la transacción

En PostgreSQL cada alta o edición que incluye placa obtiene un pg_advisory_xact_lock para la placa canónica. La clave combina el espacio de nombres 0x44563350 con un entero firmado de 32 bits derivado de SHA-256. Solicitudes a la misma placa esperan la finalización de la transacción anterior; después vuelven a consultar las filas existentes. Una colisión del hash únicamente serializa placas diferentes y la consulta final distingue sus valores.

El bloqueo es transaccional: commit o rollback lo liberan. PATCH mantiene primero el bloqueo de la fila del vehículo y la revisión If-Match; después reserva la placa. Las reglas de desasignación para cambios críticos siguen vigentes. El control se apoya en el aislamiento READ COMMITTED usado por las sesiones PostgreSQL del proyecto, para observar el resultado confirmado por el solicitante anterior al hacer la consulta siguiente.

La búsqueda usa UPPER sobre TRIM/BTRIM de espacios ASCII, consulta solo un identificador y limita a una coincidencia. Reconoce diferencias históricas de mayúsculas y espacios exteriores, sin exigir que solo exista una coincidencia. La edición excluye su propia fila, pero no ignora otros registros equivalentes.

### Error de negocio uniforme y atomicidad

| Situación | Resultado |
|---|---|
| Placa ocupada detectada en la consulta | 409, detail.code=VEHICLE_PLATE_CONFLICT y mensaje legible |
| Violación real del índice/restricción UNIQUE de placa | Mismo conflicto 409, con rollback |
| Placa mal formada | 422, sin cambios |
| Ficha modificada desde que fue cargada | Conserva el conflicto de revisión y exige recarga |
| Fallo al insertar la auditoría | Conserva 503 y rollback del negocio; no se presenta como placa duplicada |

El respaldo ante IntegrityError reconoce SQLSTATE 23505 y los nombres ix_vehicles_plate o vehicles_plate_key en los metadatos de PostgreSQL, incluida la causa del adaptador asyncpg. En SQLite exige el código extendido UNIQUE y la referencia exacta vehicles.plate. No interpreta cualquier excepción ni una coincidencia parcial del texto SQL como placa duplicada.

La escritura del vehículo se descarga con flush antes de registrar la auditoría, dentro de la misma transacción. Una colisión no confirma cambios secundarios como notas y no crea un evento de éxito. Los fallos propios del registro de auditoría siguen siendo gestionados por su servicio. No se modifica la estructura ni el contenido del evento VEHICLE_INVENTORY.

### Comportamiento del formulario

El servicio frontend conserva el código estructurado, estado HTTP y mensaje de la API. El editor distingue VEHICLE_PLATE_CONFLICT de un conflicto de revisión: muestra el error, mantiene el borrador y permite corregir la placa y reenviar con la revisión originalmente cargada. No obtiene otra revisión ni reintenta automáticamente la operación.

Si la ficha cambia mientras se corrige la placa, If-Match sigue protegiéndola y la nueva solicitud será rechazada por revisión. Los conflictos de ficha desactualizada continúan bloqueando el guardado hasta la recarga explícita.

### Límites y pendientes

No se añaden índices, restricciones, tablas ni migraciones. El índice UNIQUE existente continúa siendo sensible al valor almacenado; la equivalencia canónica entre escritores concurrentes se garantiza mediante este protocolo de API en PostgreSQL. SQL externo o procesos que no utilizan el protocolo pueden introducir variantes equivalentes. SQLite conserva la comprobación previa y el respaldo del índice, pero no ofrece esta serialización de reservas entre conexiones.

No se reparan duplicados anteriores, no se recorre el inventario para limpiarlo y no se aplica equivalencia Unicode ni eliminación de espacios interiores. La cancelación/borrado de otra transacción puede hacer necesario reenviar una solicitud rechazada tras verificar el estado. No se incorpora idempotencia para altas ante pérdida del acuse de commit.

Continúan pendientes la gestión de duplicados históricos con revisión operativa, retención de auditoría/datos personales, validaciones operativas de seguros, concurrencia de datos personales/nivel y continuidad de entregas activas. Las pruebas usan SQLite temporal y PostgreSQL test_* con esquemas aislados. No se modifican datos de negocio ni se despliega o fusiona automáticamente.

### Evidencia final local del bloque 24

| Control | Resultado |
|---|---|
| Backend completo | **751 pruebas aprobadas**, 20 nuevas frente a 731; cuatro advertencias anteriores |
| PostgreSQL real aislado | **86 pruebas** incluidas; siete nuevas: tres carreras de altas/renombrados, espera hasta commit y liberación por rollback, dos violaciones reales del índice de placa y otra restricción UNIQUE que no se confunde con la placa |
| Nuevas pruebas restantes de backend | 13 casos HTTP/SQLite: normalización, ocho entradas inválidas, rechazo atómico con corrección posterior, varias equivalencias históricas y dos fallos reales del índice sin comprobación previa |
| Frontend | **233 pruebas aprobadas** en 23 suites; dos nuevas para conservar el error estructurado y corregir una placa duplicada sin perder borrador/revisión |
| TypeScript / ESLint / Next.js build | Aprobados; advertencias anteriores conservadas |
| Mypy con --ignore-missing-imports | **329 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 169 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; formato comprobado también en las dos suites nuevas |
| Cobertura frontend | Statements **13,41 %**, branches **11,34 %**, functions **10,51 %**, lines **13,53 %** |

El comando de cobertura conserva salida con error por el umbral global del 50 %, aunque todas las pruebas frontend pasan. Mypy mantiene deuda anterior; no se declara CI global verde ni producción lista. El PR se publica sin borrador y no se fusiona automáticamente.

## Bloque 25 — Diagnóstico de placas históricas duplicadas

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit 14e2f91, con PR #266 fusionado. Rama: fix/fleet-plate-reconciliation-v1.

### Finalidad y consulta

El control transaccional del bloque 24 evita nuevas colisiones desde las rutas de inventario, pero no identifica por sí solo todos los registros históricos que requieren revisión. Se amplía el informe existente con el código DUPLICATE_PLATE:

```http
GET /api/v1/vehicles/reconciliation?code=DUPLICATE_PLATE&limit=100
```

La consulta requiere GERENTE o SUPERADMIN. Se mantienen autenticación, Cache-Control: private, no-store, Vary: Authorization, límites entre 1 y 500 y paginación por cursor. El catálogo checks incorpora el nuevo código; el esquema de cada hallazgo conserva sus campos anteriores.

### Qué se detecta

El informe agrupa vehículos por UPPER(TRIM/BTRIM(plate)) retirando exclusivamente los espacios ASCII exteriores, incluyendo tabulaciones y saltos de línea. Se comparte la expresión SQL con la comprobación de placas de las altas/ediciones para evitar dos criterios distintos. Una agrupación con más de una fila produce un hallazgo por vehículo, con entity_type=vehicle, entity_id igual al UUID del registro y related_id=null. Este último campo no representa un propietario ni un duplicado elegido arbitrariamente.

La detección incluye vehículos ACTIVO, MANTENIMIENTO y BAJA, tengan o no repartidor vinculado. Por ejemplo, `" abc-123 "` y `"ABC-123"` originan dos hallazgos. No se eliminan guiones ni espacios interiores, ni se aplica equivalencia de acentos. El informe no certifica que la placa cumpla el formato admitido para nuevas escrituras: un valor histórico inválido también puede formar un grupo repetido.

Los hallazgos identifican registros; la revisión de su ficha se realiza con las rutas de inventario existentes. No se añaden placas, nombres ni información personal al cuerpo del diagnóstico. Cada registro aparece una vez para este código, sin multiplicar resultados por todos los pares de un grupo.

### Solo lectura, consistencia y límites

El diagnóstico conserva una única sentencia SELECT por página y no realiza flush, commit, bloqueo de filas, reserva advisory ni escrituras de auditoría. Funciona dentro de una transacción PostgreSQL READ ONLY y no descarga cambios pendientes de la sesión. La subconsulta de agrupación y los hallazgos pertenecen a la misma sentencia.

Como en el informe anterior, snapshot_scope=single_statement_per_page: páginas consultadas en momentos distintos pueden reflejar cambios confirmados entre ellas. No se promete una fotografía estable de todo el recorrido ni se devuelve un recuento global. Los cursores existentes siguen admitidos; los consumidores que filtren códigos con una enumeración propia deben incorporar DUPLICATE_PLATE.

No se fusionan, eliminan, renumeran ni corrigen registros automáticamente. Tampoco se modifica la disponibilidad del catálogo o la asignación de vehículos históricos por este hallazgo. Cualquier corrección posterior requiere revisar propietarios, documentación y entregas, y usar las precondiciones y controles de inventario existentes. No se añade índice funcional: la agrupación puede examinar el inventario completo aunque la página sea pequeña; debe medirse su coste en inventarios grandes antes de sondeos frecuentes.

Se mantienen pendientes la revisión operativa y reparación autorizada de duplicados, validaciones de seguros, concurrencia de datos personales/nivel, continuidad de entregas activas y retención de auditoría. No se cambian modelos, esquema, frontend ni bases de negocio. No se aplican migraciones, despliegues ni fusiones automáticas.

### Evidencia final local del bloque 25

| Control | Resultado |
|---|---|
| Backend completo | **760 pruebas aprobadas**, nueve nuevas frente a 751; cuatro advertencias anteriores |
| PostgreSQL real aislado | **88 pruebas** incluidas; dos nuevas para duplicados/paginación bajo READ ONLY y visibilidad antes/después del commit de otra sesión |
| Nuevas pruebas restantes | Siete casos HTTP/SQLite: nuevo código en el catálogo de anomalías, tres estados de vehículo con paginación/sin reparación, y tres pares que no deben fusionarse al normalizar |
| Regresión enfocada | **70 pruebas aprobadas** de conciliación y placas, incluyendo las carreras del bloque 24 |
| Mypy con --ignore-missing-imports | **329 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 169 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; Black comprobó app y los dos archivos de pruebas modificados |
| Frontend | Sin cambios; se conserva la validación anterior de **233 pruebas**, TypeScript, lint y build, no repetida en este bloque |

Las pruebas nativas usan PostgreSQL test_* con esquemas privados y las pruebas HTTP usan SQLite temporal. No se consultan ni corrigen duplicados en bases de negocio. Mypy conserva deuda anterior y la cobertura frontend previa (**13,53 % de líneas**) sigue bajo el mínimo global del 50 %. No se declara CI global verde ni producción lista. El PR se publica sin borrador y no se fusiona automáticamente.

## Bloque 26 — Diagnóstico de fechas de seguro en el inventario

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit 61a1775, con PR #267 fusionado. Rama: feat/fleet-insurance-diagnostics-v1.

### Finalidad y contrato

La fecha insurance_expiry ya estaba almacenada en Vehicle, pero no aparecía en los controles de conciliación. El informe incorpora dos diagnósticos independientes, sin introducir un bloqueo operativo basado en una política de seguros aún pendiente:

| Código | Condición y significado |
|---|---|
| INSURANCE_EXPIRED | La fecha registrada es anterior al día de referencia UTC |
| INSURANCE_EXPIRY_MISSING | No hay fecha registrada; la vigencia es desconocida |

Se consultan en GET /api/v1/vehicles/reconciliation con code=INSURANCE_EXPIRED o code=INSURANCE_EXPIRY_MISSING. Si no se filtra por código, aparecen junto con las anomalías de vínculos y placas. Cada hallazgo representa un vehículo con entity_type=vehicle, entity_id igual a su UUID y related_id=null. Se incluyen vehículos ACTIVO, MANTENIMIENTO y BAJA, asignados o libres.

### Regla temporal explícita

La respuesta añade insurance_reference_date, en formato YYYY-MM-DD. Se obtiene del mismo instante UTC usado en generated_at antes de ejecutar la consulta; no depende de CURRENT_DATE ni de la zona horaria de la sesión SQL. La comparación con la columna Date se realiza dentro de la sentencia del informe.

Una fecha igual al día de referencia no se marca vencida; empieza a aparecer como vencida al día siguiente UTC. Esta es una regla de diagnóstico de fechas registradas, no una determinación legal sobre horarios de cobertura de una aseguradora. Si una consulta cruza medianoche mientras espera, se mantiene el día de referencia capturado y publicado para esa página. Otras páginas pueden tener una referencia diferente al cruzar el cambio de día; el recorrido no fija una fotografía global.

Una fecha ausente no se interpreta como seguro vencido ni como ausencia demostrada de póliza. Una fecha futura tampoco certifica cobertura válida: no se verifican contrato, aseguradora, pago, documentos, hora de vencimiento ni vigencia legal. No se añaden estos hallazgos a documentación personal de vehículos PROPIO que no pertenezcan al inventario Vehicle.

### Preservación del comportamiento operativo

El informe sigue usando una sola sentencia SELECT por página, sin autoflush, commit, reservas de placa, bloqueos de filas ni eventos de éxito de auditoría. Mantiene permisos GERENTE/SUPERADMIN, cabeceras privadas y límites/cursor. Funciona dentro de una transacción PostgreSQL READ ONLY. Los valores almacenados y estados de los vehículos no se cambian al consultar.

No se rechaza una asignación, no se cambia el catálogo disponible, no se desconecta un repartidor y no se altera una entrega por estos diagnósticos. El endurecimiento operativo requiere completar una política de fechas/zonas, tratamiento de fechas desconocidas, acreditación de pólizas y continuidad de entregas activas antes de activarlo. Este bloque permite identificar los datos pendientes sin adoptar esas decisiones de forma implícita.

El catálogo checks añade los dos códigos y el cuerpo añade insurance_reference_date; los consumidores con validación estricta deben admitirlos. No se cambian modelos, tablas, índices, migraciones ni frontend. El coste del diagnóstico depende del inventario examinado, además de la paginación de resultados. No se intervienen bases de negocio ni se despliega o fusiona automáticamente.

### Evidencia final local del bloque 26

| Control | Resultado |
|---|---|
| Backend completo | **771 pruebas aprobadas**, once nuevas frente a 760; cuatro advertencias anteriores |
| PostgreSQL real aislado | **89 pruebas** incluidas; una nueva con columna Date nativa, fechas vencidas/ausentes y transacción READ ONLY |
| Nuevas pruebas restantes | Diez casos HTTP/SQLite: dos códigos en el catálogo de anomalías, cuatro fechas límite/ausencia, tres estados con paginación y conservación de datos, y cambio de día UTC |
| Regresión enfocada | **61 pruebas aprobadas** de conciliación, incluidas las de placas y los controles anteriores de lectura/permisos |
| Mypy con --ignore-missing-imports | **329 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 169 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; formato comprobado en app y los dos archivos de pruebas modificados |
| Frontend | Sin cambios; se conserva la validación anterior de **233 pruebas**, TypeScript, lint y build, no repetida |

Las pruebas usan SQLite temporal y PostgreSQL test_* con esquemas privados. Los datos saludables de las pruebas de conciliación incluyen ahora una fecha futura conocida, para distinguirlos de un inventario con fecha desconocida. No se modifican las fechas de bases de negocio. Mypy conserva deuda anterior y la cobertura frontend previa (**13,53 % de líneas**) sigue bajo el mínimo global del 50 %. No se declara CI global verde ni producción lista. El PR se publica sin borrador y no se fusiona automáticamente.

## Bloque 27 — Precondiciones para datos personales y nivel del repartidor

Fecha: 25 de octubre de 2026 (America/Caracas). Base: main, commit 0d333d6, con PR #268 fusionado. Rama: fix/rider-profile-preconditions-v1.

### Problema y contrato de escritura

La revisión de asignación protegía el vehículo, pero dos formularios podían sobrescribir teléfono, nombre o nivel usando información anterior. PUT /api/v1/riders/me y PATCH /api/v1/riders/{id} requieren ahora expected_profile_revision cuando actualizan valores no nulos de first_name, last_name, phone, operating_zone, cpf, cnh o tier. Una revisión ausente o desactualizada devuelve 409; una revisión mal formada devuelve 422. Los permisos sobre nivel y flota se verifican antes y no cambian.

Las respuestas Rider generadas por el serializador común incluyen profile_revision. Es una huella SHA-256 de los identificadores del perfil/usuario y sus valores personales/nivel persistidos. Incluye campos de User y Rider para que una modificación en cualquiera de ellos invalide una ficha anterior. Es independiente de assignment_revision y de la revisión del vehículo seleccionado.

No intervienen GPS, disponibilidad, estado administrativo, puntos, saldos, fechas internas ni metadatos del vehículo. Un cambio de flota no obliga por sí solo a descartar una edición exclusivamente personal. Una solicitud que cambia ambos ámbitos debe presentar ambas revisiones; las selecciones EMPRESA siguen requiriendo además expected_vehicle_revision.

### Bloqueos y atomicidad

Las actualizaciones personales bloquean primero Rider y luego User. Si la solicitud también toca flota, mantiene el orden previo de vehículos por UUID, Rider, User y finalmente documentos. Antes de comparar la revisión se vuelven a leer los campos personales de Rider y se refresca User bajo bloqueo; no se confía en valores antiguos de la sesión ORM.

La comprobación precede a la aplicación de datos personales/nivel y no confirma una transacción propia. Si el cambio de flota había preparado vínculos y falla la revisión personal, el rollback de la solicitud revierte toda la operación, sin asignación parcial, invalidación de documentos ni evento de éxito. Los cambios de User se aplican al usuario cargado y bloqueado del perfil tanto en la ruta personal como en la administrativa.

### Formularios y compatibilidad

El editor de gerencia captura profile_revision junto con el borrador ya congelado. Un refresco de la lista del mismo repartidor no sustituye silenciosamente la revisión; cerrar y reabrir permite capturar la ficha nueva. El perfil del repartidor carga ambas revisiones desde el servidor, las envía al guardar y bloquea nuevos envíos tras un conflicto hasta una recarga explícita. Los datos de respaldo del almacén local no autorizan un guardado sin revisión de servidor.

El servicio frontend valida la revisión antes de enviar cambios personales/nivel; no obtiene un token nuevo ni reintenta automáticamente. Los consumidores anteriores de estas dos rutas deben incorporar expected_profile_revision. Las escrituras exclusivamente de flota conservan su contrato anterior. Se mantiene el tratamiento previo de null como campo omitido en RiderUpdate; este bloque no añade borrado explícito de campos personales.

### Límites y pendientes

La huella representa valores, no un contador de eventos: volver exactamente a los valores anteriores produce la misma revisión. No es una credencial, firma de auditoría, anonimización ni prueba de que una persona revisó el contenido. La combinación de varios campos no implica que sus datos personales puedan divulgarse sin control.

La exclusión optimista cubre las dos rutas Rider modificadas. Las rutas generales /users/me y /users/{id}, tareas, scripts y SQL que actualicen datos sin este protocolo siguen pendientes de unificación. Si un cambio externo ya se confirmó antes de la comprobación, la nueva lectura lo detecta; no se garantiza evitar sobrescrituras originadas después por escritores que no presentan su propia precondición. Tampoco se incorpora aquí una auditoría personal/nivel ni protección monotónica contra cambios y retornos al mismo valor.

Las garantías de espera y bloqueo se validan en PostgreSQL. SQLite permite comprobar contrato HTTP y rollback, pero no representa esos bloqueos de fila. No cambian esquema, modelos, migraciones, reglas de cálculo de bonos o permisos. No se modifican datos de negocio ni se despliega o fusiona automáticamente.

### Evidencia final local del bloque 27

| Control | Resultado |
|---|---|
| Backend completo | **785 pruebas aprobadas**, catorce nuevas frente a 771; cuatro advertencias anteriores |
| PostgreSQL real aislado | **92 pruebas** incluidas; tres nuevas para editores simultáneos, refresco del usuario tras esperar y coexistencia de perfil/flota sin orden inverso de bloqueos |
| Nuevas pruebas restantes | Once casos HTTP/SQLite: revisiones ausentes/malformadas/desactualizadas en ambas rutas, segundo editor, rollback mixto de perfil/flota, independencia de telemetría/flota y denegación del cambio de tier a REPARTIDOR |
| Frontend | **240 pruebas aprobadas** en 23 suites; siete nuevas para rechazos locales, ausencia de revisión en formularios y conservación de revisión en el almacén |
| TypeScript / ESLint / Next.js build | Aprobados; advertencias anteriores conservadas |
| Mypy con --ignore-missing-imports | **329 errores en 52 archivos**, sin diagnósticos nuevos por archivo/mensaje; 170 archivos de app |
| Black / Flake8 crítico / git diff --check | Aprobados; los archivos Python nuevos también fueron formateados |
| Cobertura frontend | Statements **13,57 %**, branches **11,45 %**, functions **10,67 %**, lines **13,66 %** |

Las pruebas anteriores de autorización con persistencia simulada aíslan ahora ese objetivo del servicio de precondición; las pruebas nuevas ejercitan la protección real con SQLite y PostgreSQL. Los auxiliares de pruebas obtienen la revisión antes de cambios independientes; los casos de conflicto conservan expresamente una revisión antigua. El almacén frontend puede incluir propiedades undefined sin convertirlas en cambios personales: se valida la revisión de los valores no nulos que realmente se enviarían.

El comando de cobertura sigue terminando con error por el umbral global del 50 %, aunque todas las pruebas frontend pasan. Mypy mantiene deuda anterior; no se declara CI global verde ni producción lista. Se usan únicamente bases temporales/test_* con esquemas aislados. El PR se publica sin borrador, sin despliegue ni fusión automática.

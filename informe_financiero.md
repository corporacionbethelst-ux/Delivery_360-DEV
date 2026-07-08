# Informe Financiero: Sistema de Pagos a Repartidores

## 1. Situación Actual

### 1.1 Configuración Global Existente
El sistema cuenta con parámetros financieros configurables en `/manager/admin/settings`:

- **Tarifa Base de Envío**: Lo que paga el cliente por el servicio de delivery
- **Comisión %**: Porcentaje que retiene la plataforma sobre cada pedido
- **Pedido Mínimo**: Valor mínimo para aceptar una orden

**Problema Crítico Identificado**:
El bono por entrega exitosa al repartidor está **hardcodeado** como `2.50` en múltiples ubicaciones del backend:
- `/backend/app/api/v1/orders.py` (línea 638)
- `/backend/app/api/v1/deliveries.py` (línea 508)
- `/backend/app/services/financial_service.py` (línea 177)

### 1.2 Archivos Clave Identificados

#### Frontend
| Archivo | Función Actual | Relación con Mejoras |
|---------|---------------|---------------------|
| `/frontend/src/app/(dashboard)/manager/admin/settings/page.tsx` | Configuración global de tarifas y comisiones | Aquí se agregará el campo "Bono por Entrega" |
| `/frontend/src/app/(dashboard)/manager/fleet/zones/[id]/page.tsx` | Configura tarifa base por zona (`delivery_fee_base`) | Base para futuros multiplicadores zonales |
| `/frontend/src/app/(dashboard)/rider/productivity/page.tsx` | Muestra ganancias totales del repartidor | Visualiza resultados de cálculos financieros |
| `/frontend/src/services/settings.service.ts` | Interfaz `PlatformSettings` | Requiere agregar `rider_delivery_bonus` |

#### Backend
| Archivo | Función Actual | Cambio Requerido |
|---------|---------------|-----------------|
| `/backend/app/models/platform_settings.py` | Modelo key-value para configuración | Agregar validación para nueva clave |
| `/backend/app/api/v1/settings.py` | CRUD de settings | Sin cambios mayores necesarios |
| `/backend/app/api/v1/orders.py` | Cálculo de pago al rider (2.50 hardcoded) | Reemplazar con valor dinámico |
| `/backend/app/api/v1/deliveries.py` | Cálculo de pago al rider (2.50 hardcoded) | Reemplazar con valor dinámico |
| `/backend/app/services/financial_service.py` | Servicio financiero central (2.50 hardcoded) | Reemplazar con valor dinámico |

### 1.3 Comportamiento Actual del Sistema

```
Flujo de Pago Actual:
1. Cliente paga: tarifa_base + variables
2. Plataforma retiene: comisión%
3. Repartidor recibe: 2.50 (FIJO, no configurable)
4. Restaurante recibe: resto después de comisiones
```

**Limitaciones**:
- No se puede ajustar el pago al repartidor sin modificar código
- No hay diferenciación por tipo de repartidor, zona o vehículo
- No hay compensación configurable para entregas fallidas
- El historial financiero no muestra desglose de componentes del pago

---

## 2. Mejoras Propuestas

### 2.1 Objetivos Generales

1. **Dinamizar parámetros financieros**: Que el gerente pueda configurar valores sin tocar código
2. **Trazabilidad completa**: Saber exactamente cómo se calculó cada pago
3. **Flexibilidad progresiva**: Implementar por fases sin romper funcionalidad existente
4. **Equidad y motivación**: Permitir esquemas de pago diferenciados según contexto

### 2.2 Capacidades Deseadas

#### Para el Gerente/Administrador
- Configurar bono base por entrega exitosa (global)
- Configurar bono por entrega fallida (cuando el repartidor completó su parte)
- Definir multiplicadores por zona geográfica
- Establecer niveles de repartidores con diferentes tasas
- Programar bonos temporales (horas pico, días especiales)
- Ver reporte detallado de composición de pagos

#### Para el Repartidor
- Transparencia en cómo se calcula su ganancia
- Posibilidad de ganar más según zona, horario o desempeño
- Compensación justa cuando el fallo no es su responsabilidad
- Historial detallado de ingresos por componente

#### Para la Plataforma
- Control total sobre estructura de costos
- Ability to test different incentive models
- Data-driven decisions on pricing and bonuses
- Maintain historical accuracy for accounting

---

## 3. Fases de Desarrollo

### FASE 1: Configuración Global Básica (Prioridad Inmediata)

**Objetivo**: Eliminar el valor hardcoded 2.50 y hacerlo configurable globalmente.

**Cambios**:
- [ ] Backend: Leer `rider_delivery_bonus` desde platform_settings
- [ ] Backend: Reemplazar 2.50 en orders.py, deliveries.py, financial_service.py
- [ ] Backend: Default value = 2.50 si no existe configuración
- [ ] Frontend: Agregar input numérico en settings/page.tsx
- [ ] Frontend: Validar que sea número positivo
- [ ] Service: Actualizar interfaz PlatformSettings

**Impacto**: 
- ✅ No rompe funcionalidad existente
- ✅ Valor por defecto mantiene compatibilidad
- ✅ Transacciones anteriores no se modifican
- ⚠️ Solo un valor global para todos los repartidores

**Tiempo estimado**: 4-6 horas

---

### FASE 2: Bonos por Entregas Fallidas

**Objetivo**: Compensar repartidores cuando la falla no es su responsabilidad.

**Escenarios cubiertos**:
- Cliente da dirección incorrecta
- Cliente no recibe el pedido
- Cliente cancela después de que el repartidor ya hizo la ruta
- Restaurante demora excesivamente la preparación

**Cambios**:
- [ ] Backend: Agregar `rider_failed_delivery_bonus` en settings
- [ ] Backend: Crear enum para tipos de falla (CLIENTE, RESTAURANTE, CLIMA, OTROS)
- [ ] Backend: Modificar flujo de cancelación para calcular bono parcial
- [ ] Frontend: Agregar campo para bono por entrega fallida en settings
- [ ] Frontend: En productivity page, mostrar desglose: exitosas vs fallidas
- [ ] Database: Agregar campo `failure_reason` en tabla de deliveries

**Fórmula propuesta**:
```
Pago por entrega fallida = (rider_failed_delivery_bonus) * (porcentaje_completado)
Ejemplo: 2.50 * 0.6 = 1.50 si completó 60% de la ruta
```

**Impacto**:
- ✅ Mayor justicia para repartidores
- ✅ Reduce conflictos y reclamos
- ⚠️ Requiere definir claramente criterios de falla
- ⚠️ Necesita UI para que repartidor justifique falla

**Tiempo estimado**: 8-12 horas

---

### FASE 3: Multiplicadores por Zona Geográfica

**Objetivo**: Pagar más en zonas de difícil acceso, alto tráfico o alta demanda.

**Cambios**:
- [ ] Backend: Agregar `zone_multiplier` en modelo de zones
- [ ] Backend: Modificar cálculo: `pago_final = bono_base * zone_multiplier`
- [ ] Frontend: En fleet/zones/[id], agregar slider para multiplicador (0.8x - 3.0x)
- [ ] Frontend: Mostrar en mapa de zonas los multiplicadores actuales
- [ ] Database: Agregar columna `multiplier` en tabla zones

**Fórmula propuesta**:
```
pago_por_zona = rider_delivery_bonus * zone_multiplier
Ejemplo: Zona centro = 2.50 * 1.0 = 2.50
         Zona rural = 2.50 * 1.5 = 3.75
         Zona fácil = 2.50 * 0.9 = 2.25
```

**Impacto**:
- ✅ Incentiva repartidores a cubrir zonas difíciles
- ✅ Mejor distribución geográfica del servicio
- ⚠️ Requiere recalcular tarifas al cliente también
- ⚠️ Puede generar confusión si no se comunica bien

**Tiempo estimado**: 10-14 horas

---

### FASE 4: Niveles de Repartidores (Tier System)

**Objetivo**: Recompensar experiencia, desempeño y antigüedad.

**Niveles propuestos**:
- 🥉 **Bronce**: Nuevo repartidor (1.0x)
- 🥈 **Plata**: 50+ entregas, 4.5+ rating (1.1x)
- 🥇 **Oro**: 200+ entregas, 4.8+ rating (1.25x)
- 💎 **Platino**: 500+ entregas, 4.9+ rating, 0 incidentes (1.4x)

**Cambios**:
- [ ] Backend: Crear modelo `RiderLevel` con criterios automáticos
- [ ] Backend: Agregar `level_multiplier` al cálculo financiero
- [ ] Backend: Job nocturno para actualizar niveles basado en métricas
- [ ] Frontend: En perfil de repartidor, mostrar nivel actual y progreso
- [ ] Frontend: En admin panel, ver distribución de niveles
- [ ] Database: Agregar `current_level` y `level_history` en riders

**Fórmula final**:
```
pago_final = rider_delivery_bonus * zone_multiplier * level_multiplier
Ejemplo: Oro en zona rural = 2.50 * 1.5 * 1.25 = 4.69
```

**Impacto**:
- ✅ Retención de mejores repartidores
- ✅ Gamificación del sistema
- ⚠️ Complejidad aumentada en cálculos
- ⚠️ Requiere comunicación clara de criterios

**Tiempo estimado**: 16-20 horas

---

### FASE 5: Bonos Temporales y Dinámicos

**Objetivo**: Incentivar entregas en horarios pico, días lluviosos, eventos especiales.

**Tipos de bonos**:
- **Horas Pico**: 6-9 AM, 12-2 PM, 7-10 PM (1.3x)
- **Días Lluviosos**: Detección automática por API de clima (1.5x)
- **Eventos Especiales**: Configuración manual (Super Bowl, Navidad, etc.)
- **Zonas Calientes**: Heatmap en tiempo real de alta demanda (1.4x)

**Cambios**:
- [ ] Backend: Crear modelo `DynamicBonus` con reglas y vigencia
- [ ] Backend: Integrar API de clima para bonos automáticos
- [ ] Backend: Modificar cálculo para aplicar bono temporal activo
- [ ] Frontend: En rider app, mostrar bonos activos antes de aceptar pedido
- [ ] Frontend: En admin, crear UI para programar bonos manuales
- [ ] Frontend: Dashboard con heatmap de zonas calientes

**Fórmula completa**:
```
pago_final = base * zone * level * temporal_bonus
Ejemplo: Platino, zona rural, hora pico, lloviendo
         = 2.50 * 1.5 * 1.4 * 1.3 * 1.5 = 10.97
```

**Impacto**:
- ✅ Máxima flexibilidad operativa
- ✅ Respuesta ágil a condiciones del mercado
- ⚠️ Complejidad técnica significativa
- ⚠️ Costo variable difícil de predecir

**Tiempo estimado**: 20-25 horas

---

### FASE 6: Reportes y Analytics Financieros

**Objetivo**: Visibilidad total sobre costos, tendencias y ROI de bonos.

**Reportes a implementar**:
- Desglose de pagos por componente (base, zona, nivel, temporal)
- Comparativa de costos antes/después de cambios en bonos
- ROI de bonos temporales (¿más entregas justifican el costo?)
- Distribución de ingresos por nivel de repartidor
- Proyección de costos mensuales/anuales
- Alertas cuando costos superan umbrales configurados

**Cambios**:
- [ ] Backend: Crear endpoints dedicados para analytics financieros
- [ ] Backend: Agregar tablas de agregación para queries rápidos
- [ ] Frontend: Dashboard ejecutivo con gráficos interactivos
- [ ] Frontend: Exportar reportes a CSV/PDF
- [ ] Frontend: Configurar alertas de presupuesto

**Impacto**:
- ✅ Decisiones basadas en datos reales
- ✅ Control financiero preciso
- ⚠️ Requiere infraestructura de datos robusta
- ⚠️ Curva de aprendizaje para usuarios

**Tiempo estimado**: 15-20 horas

---

## 4. Cambios Generales por Capa

### 4.1 Base de Datos

#### Tablas Existentes (sin cambios estructurales mayores)
- `platform_settings`: Ya soporta key-value, solo agregar nuevas keys
- `zones`: Agregar columna `multiplier` (FLOAT, default 1.0)
- `riders`: Agregar columnas `current_level`, `total_earnings`, `completed_deliveries`

#### Nuevas Tablas Propuestas
```sql
-- Para FASE 2: Entregas fallidas
CREATE TABLE delivery_failures (
    id UUID PRIMARY KEY,
    delivery_id UUID REFERENCES deliveries(id),
    reason ENUM('CLIENT_ADDRESS', 'CLIENT_REFUSAL', 'RESTAURANT_DELAY', 'WEATHER', 'OTHER'),
    description TEXT,
    percentage_completed FLOAT,
    bonus_amount DECIMAL(10,2),
    created_at TIMESTAMP
);

-- Para FASE 4: Niveles de repartidores
CREATE TABLE rider_levels (
    id UUID PRIMARY KEY,
    name VARCHAR(50), -- Bronze, Silver, Gold, Platinum
    min_deliveries INT,
    min_rating FLOAT,
    max_incidents INT,
    multiplier FLOAT,
    is_active BOOLEAN
);

CREATE TABLE rider_level_history (
    id UUID PRIMARY KEY,
    rider_id UUID REFERENCES riders(id),
    old_level_id UUID REFERENCES rider_levels(id),
    new_level_id UUID REFERENCES rider_levels(id),
    changed_at TIMESTAMP,
    reason TEXT
);

-- Para FASE 5: Bonos temporales
CREATE TABLE dynamic_bonuses (
    id UUID PRIMARY KEY,
    name VARCHAR(100),
    bonus_type ENUM('TIME_RANGE', 'WEATHER', 'EVENT', 'ZONE_HEAT'),
    multiplier FLOAT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    applicable_zones JSONB,
    conditions JSONB, -- {"temperature": "<15", "precipitation": ">5"}
    is_active BOOLEAN
);
```

### 4.2 Backend (Python/FastAPI)

#### Servicios a Modificar
```python
# financial_service.py
class FinancialService:
    async def calculate_rider_payment(
        self, 
        delivery: Delivery, 
        config: PlatformConfig
    ) -> PaymentBreakdown:
        # Fase 1
        base_bonus = await self.get_rider_delivery_bonus()
        
        # Fase 3
        zone_multiplier = await self.get_zone_multiplier(delivery.zone_id)
        
        # Fase 4
        level_multiplier = await self.get_rider_level_multiplier(delivery.rider_id)
        
        # Fase 5
        temporal_bonus = await self.get_active_temporal_bonus(
            delivery.location, 
            delivery.timestamp
        )
        
        # Fase 2
        if delivery.status == 'FAILED':
            failure_bonus = await self.calculate_failed_delivery_bonus(
                delivery, 
                config.failed_delivery_bonus
            )
            return failure_bonus
        
        # Cálculo final
        total = base_bonus * zone_multiplier * level_multiplier * temporal_bonus
        
        return PaymentBreakdown(
            base=base_bonus,
            zone_adjustment=zone_multiplier,
            level_adjustment=level_multiplier,
            temporal_adjustment=temporal_bonus,
            total=total
        )
```

#### Endpoints Nuevos
```python
# GET /api/v1/financial/breakdown/{delivery_id}
# Devuelve desglose completo de cómo se calculó el pago

# POST /api/v1/financial/bonuses/temporal
# Crea un bono temporal (admin only)

# GET /api/v1/financial/analytics/summary
# Dashboard financiero con métricas clave

# PUT /api/v1/riders/{id}/level
# Ajuste manual de nivel (casos excepcionales)
```

### 4.3 Frontend (React/Next.js)

#### Componentes Nuevos
```tsx
// components/financial/BonusConfigurator.tsx
// UI para configurar todos los tipos de bonos

// components/financial/PaymentBreakdown.tsx
// Muestra desglose de pago en tiempo real

// components/financial/ZoneMultiplierMap.tsx
// Mapa interactivo con multiplicadores por zona

// components/financial/RiderLevelCard.tsx
// Tarjeta de progreso de nivel para repartidores

// components/financial/TemporalBonusScheduler.tsx
// Calendario para programar bonos temporales
```

#### Páginas a Modificar
- `/manager/admin/settings`: Agregar sección completa de "Pagos a Repartidores"
- `/manager/fleet/zones/[id]`: Agregar control de multiplicador zonal
- `/rider/productivity`: Mostrar desglose detallado, no solo total
- `/rider/profile`: Mostrar nivel actual y progreso al siguiente nivel
- `/manager/analytics/financial`: Nueva página de reportes financieros

---

## 5. Consideraciones Técnicas

### 5.1 Trazabilidad e Idempotencia

**Principio**: Una vez calculado, un pago nunca debe cambiar.

**Implementación**:
```python
# Guardar snapshot de configuración al momento del cálculo
class PaymentSnapshot(Base):
    delivery_id = Column(UUID, ForeignKey('deliveries.id'))
    base_bonus = Column(Float)  # 2.50 al momento del cálculo
    zone_multiplier = Column(Float)  # 1.5 al momento del cálculo
    level_multiplier = Column(Float)  # 1.25 al momento del cálculo
    temporal_bonus = Column(Float)  # 1.3 al momento del cálculo
    final_amount = Column(Float)  # Resultado congelado
    calculated_at = Column(DateTime)
    
# Si cambian los settings después, las transacciones pasadas no se afectan
```

### 5.2 Performance

**Optimizaciones requeridas**:
- Cache de configuración global (Redis, TTL 5 min)
- Pre-calcular multiplicadores de zonas en memoria
- Indexar tablas de histórico por fecha y rider_id
- Usar materialized views para reportes complejos

### 5.3 Seguridad y Auditoría

**Controles necesarios**:
- Log de todos los cambios en configuración financiera
- Approval workflow para cambios >20% en bonos base
- Role-based access: solo admins senior pueden modificar bonos
- Alertas automáticas si costos superan presupuesto mensual

### 5.4 Migración de Datos

**Para implementaciones futuras**:
```python
# Script de migración para FASE 3 (multiplicadores por zona)
async def migrate_zone_multipliers():
    zones = await db.all(Zones)
    for zone in zones:
        # Default 1.0 para todas las zonas existentes
        zone.multiplier = 1.0
        
        # Zonas céntricas podrían tener 1.2 por defecto
        if zone.name in ['Centro', 'Zona Rosa', 'Financial District']:
            zone.multiplier = 1.2
    
    await db.commit()
```

---

## 6. Matriz de Impacto

| Fase | Complejidad | Riesgo | Valor de Negocio | Tiempo Est. |
|------|-------------|--------|------------------|-------------|
| **Fase 1** | Baja | Mínimo | Alto | 4-6h |
| **Fase 2** | Media | Bajo | Alto | 8-12h |
| **Fase 3** | Media | Medio | Alto | 10-14h |
| **Fase 4** | Alta | Medio | Muy Alto | 16-20h |
| **Fase 5** | Muy Alta | Alto | Muy Alto | 20-25h |
| **Fase 6** | Alta | Bajo | Alto | 15-20h |

**Recomendación**: Implementar Fases 1-2 inmediatamente (máximo 2 días), luego evaluar métricas antes de continuar con Fases 3-4. Fases 5-6 son opcionales según crecimiento del negocio.

---

## 7. Escenarios de Prueba

### Scenario 1: Cambio de Bono Base (Fase 1)
```
Given: Bono actual = 2.50
When: Admin cambia a 3.00 en settings
Then: 
  - Próximas entregas pagan 3.00
  - Entregas anteriores mantienen 2.50
  - Rider ve nuevo valor antes de aceptar pedido
```

### Scenario 2: Entrega Fallida por Cliente (Fase 2)
```
Given: Repartidor completó 80% de ruta
When: Cliente da dirección incorrecta
Then: 
  - Repartidor marca falla como "CLIENT_ADDRESS"
  - Sistema calcula: 2.50 * 0.8 = 2.00
  - Repartidor recibe 2.00 aunque no hubo entrega
```

### Scenario 3: Multiplicador Zonal (Fase 3)
```
Given: Zona rural con multiplier = 1.5
When: Repartidor completa entrega en esa zona
Then: 
  - Pago = 2.50 * 1.5 = 3.75
  - Cliente ve tarifa ajustada también
```

### Scenario 4: Combinación Completa (Fases 1-5)
```
Given: 
  - Bono base: 2.50
  - Zona: 1.5x
  - Nivel rider: Oro (1.25x)
  - Hora pico: 1.3x
  - Lloviendo: 1.5x
  
When: Repartidor Platino completa entrega en zona rural, 8 PM, lluvia
  
Then: 
  - Pago = 2.50 * 1.5 * 1.25 * 1.3 * 1.5 = 10.97
  - Desglose visible en app del repartidor
```

---

## 8. Roadmap Recomendado

### Semana 1: Fundamentos
- [x] Este informe de planificación
- [ ] **Fase 1**: Bono base configurable (2 días)
- [ ] Testing y QA de Fase 1 (1 día)
- [ ] Deploy a producción (1 día)

### Semana 2: Justicia Operativa
- [ ] **Fase 2**: Bonos por entregas fallidas (3 días)
- [ ] Documentación para repartidores (1 día)
- [ ] Training a soporte (0.5 días)
- [ ] Deploy y monitoreo (0.5 días)

### Semana 3-4: Optimización Geográfica
- [ ] **Fase 3**: Multiplicadores por zona (4 días)
- [ ] Ajuste de tarifas al cliente (2 días)
- [ ] Comunicación a stakeholders (1 día)
- [ ] Deploy gradual por región (3 días)

### Mes 2: Retención de Talento
- [ ] **Fase 4**: Sistema de niveles (5 días)
- [ ] Campaña de lanzamiento interno (2 días)
- [ ] Analytics de adopción (3 días)

### Mes 3: Inteligencia de Negocio
- [ ] **Fase 5**: Bonos dinámicos (opcional, 5 días)
- [ ] **Fase 6**: Reportes avanzados (5 días)
- [ ] Iteración basada en feedback (continuo)

---

## 9. Métricas de Éxito

### KPIs a Monitorear
- **Retención de repartidores**: % que permanecen activos después de 30/60/90 días
- **Satisfacción de repartidores**: Rating promedio en encuestas
- **Costo por entrega**: Tendencia mensual (debe ser sostenible)
- **Tiempo de aceptación**: Cuánto tardan en aceptar pedidos (debe disminuir)
- **Cobertura geográfica**: % de zonas cubiertas consistentemente
- **Incidentes reportados**: Disminución en disputas por pagos

### Thresholds de Alerta
- Costo por entrega aumenta >15% en un mes → Revisar multiplicadores
- Retención cae <60% a 30 días → Revisar esquema de niveles
- >10% de entregas marcadas como fallidas → Investigar patrones
- Rating de repartidores <4.0 → Urgent action required

---

## 10. Conclusión y Siguientes Pasos

### Resumen Ejecutivo
El sistema actual tiene una deuda técnica crítica: el bono de repartidor está hardcodeado. Esto limita la capacidad del negocio para:
- Responder a condiciones del mercado
- Competir por mejor talento
- Optimizar costos operativos
- Ser justo con repartidores en situaciones complejas

### Recomendación Inmediata
**Proceder con Fase 1 urgentemente** (4-6 horas de trabajo):
- Elimina el hardcoded 2.50
- Permite ajustes sin deploy de código
- Mantiene 100% de compatibilidad hacia atrás
- Prepara infraestructura para fases futuras

### Próximos Pasos
1. ✅ Revisar y aprobar este informe
2. ⏳ Autorizar inicio de Fase 1
3. ⏳ Implementar cambios (backend + frontend)
4. ⏳ Testing en ambiente staging
5. ⏳ Deploy a producción con feature flag
6. ⏳ Monitorear métricas por 1 semana
7. ⏳ Decidir sobre Fase 2 basado en resultados

---

**Documento elaborado**: $(date)  
**Versión**: 1.0  
**Estado**: Pendiente de aprobación  
**Próxima revisión**: Después de completar Fase 1

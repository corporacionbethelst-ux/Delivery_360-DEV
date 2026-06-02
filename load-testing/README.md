# 🚀 Pruebas de Carga - Delivery360

## Descripción

Este directorio contiene scripts y configuraciones para realizar pruebas de carga y performance del sistema Delivery360.

## Herramientas Utilizadas

### 1. **Locust** (Principal)
Herramienta de load testing basada en Python que permite simular miles de usuarios concurrentes.

**Instalación:**
```bash
pip install locust
```

**Uso básico:**
```bash
# Con interfaz web (recomendado para exploración)
locust -f locustfile.py --host=http://localhost:8000

# Modo headless (para CI/CD o pruebas automatizadas)
locust -f locustfile.py --host=http://localhost:8000 --headless \
  --users=100 \
  --spawn-rate=10 \
  --run-time=5m \
  --csv=./results/load_test
```

**Parámetros recomendados:**
- `--users=100`: Número total de usuarios concurrentes
- `--spawn-rate=10`: Usuarios que se agregan por segundo
- `--run-time=5m`: Duración de la prueba
- `--headless`: Modo sin interfaz web

## Escenarios de Prueba

### 1. **Prueba de Estrés Básico**
Simula carga normal de operación durante hora pico.

```bash
locust -f locustfile.py --host=http://localhost:8000 \
  --headless --users=50 --spawn-rate=5 --run-time=10m
```

### 2. **Prueba de Carga Máxima**
Evalúa el límite del sistema antes de degradación.

```bash
locust -f locustfile.py --host=http://localhost:8000 \
  --headless --users=200 --spawn-rate=20 --run-time=15m
```

### 3. **Prueba de Resistencia**
Verifica estabilidad del sistema bajo carga sostenida.

```bash
locust -f locustfile.py --host=http://localhost:8000 \
  --headless --users=75 --spawn-rate=5 --run-time=1h
```

### 4. **Prueba de Picos (Spike Test)**
Simula aumentos repentinos de tráfico.

```bash
# Fase 1: Carga normal
locust -f locustfile.py --host=http://localhost:8000 \
  --headless --users=30 --spawn-rate=5 --run-time=5m

# Fase 2: Pico repentino (ejecutar en otra terminal)
locust -f locustfile.py --host=http://localhost:8000 \
  --headless --users=300 --spawn-rate=50 --run-time=2m
```

## Perfiles de Usuario Simulados

### 🛵 **RiderUser** (Repartidor)
- **Peso**: 40% del tráfico total
- **Comportamiento**: Actualiza ubicación frecuentemente, consulta órdenes asignadas
- **Endpoints principales**:
  - `GET /api/v1/orders/my-orders` (frecuencia alta)
  - `POST /api/v1/riders/update-location` (frecuencia media)
  - `GET /api/v1/dashboard/rider` (frecuencia baja)

### 👨‍💼 **OperatorUser** (Operador)
- **Peso**: 40% del tráfico total
- **Comportamiento**: Gestiona órdenes, asigna repartidores, crea nuevas entregas
- **Endpoints principales**:
  - `GET /api/v1/orders` (frecuencia muy alta)
  - `GET /api/v1/riders` (frecuencia alta)
  - `POST /api/v1/orders` (frecuencia media)
  - `POST /api/v1/orders/{id}/assign` (frecuencia media)

### 📊 **ManagerUser** (Gerente)
- **Peso**: 20% del tráfico total
- **Comportamiento**: Revisa dashboards, métricas y reportes financieros
- **Endpoints principales**:
  - `GET /api/v1/dashboard/manager` (frecuencia media)
  - `GET /api/v1/productivity/metrics` (frecuencia media)
  - `GET /api/v1/financial/summary` (frecuencia baja)

## Métricas a Monitorear

### 🎯 KPIs Principales

| Métrica | Objetivo | Acceptable | Crítico |
|---------|----------|------------|---------|
| **Response Time (p95)** | < 200ms | < 500ms | > 1000ms |
| **Response Time (p99)** | < 500ms | < 1000ms | > 2000ms |
| **Success Rate** | > 99.9% | > 99% | < 95% |
| **Requests/sec** | > 100 | > 50 | < 20 |
| **Error Rate** | < 0.1% | < 1% | > 5% |

### 📈 Métricas Específicas por Endpoint

#### Endpoints Críticos (SLA estricto):
- `GET /api/v1/orders` - p95 < 300ms
- `POST /api/v1/orders` - p95 < 500ms
- `GET /api/v1/riders` - p95 < 200ms

#### Endpoints Importantes:
- `GET /api/v1/dashboard/*` - p95 < 500ms
- `POST /api/v1/orders/{id}/assign` - p95 < 400ms

#### Endpoints Secundarios:
- `GET /api/v1/productivity/*` - p95 < 800ms
- `GET /api/v1/financial/*` - p95 < 1000ms

## Resultados Esperados

### ✅ Criterios de Aprobación

1. **Performance**:
   - 95% de las requests completadas en < 500ms
   - 99% de las requests completadas en < 1000ms
   
2. **Estabilidad**:
   - Tasa de éxito > 99% bajo carga normal
   - Tasa de éxito > 95% bajo carga máxima
   
3. **Recuperación**:
   - El sistema se recupera automáticamente después de picos de carga
   - No hay memory leaks después de pruebas prolongadas (>30min)

### ⚠️ Señales de Alerta

- Response time incrementa exponencialmente con la carga
- Tasa de errores > 5% bajo carga moderada
- El sistema no se recupera después de remover la carga
- Consumo de memoria crece continuamente

## Optimizaciones Implementadas

### Backend (FastAPI + Redis Cache)

1. **Caché HTTP Middleware**:
   - Caché automático para endpoints GET frecuentes
   - TTL configurable por tipo de endpoint
   - Invalidación automática en operaciones de escritura

2. **Servicio de Caché Especializado**:
   - Caché de órdenes (2 minutos TTL)
   - Caché de repartidores (1 minuto TTL)
   - Caché de dashboards (3 minutos TTL)

3. **Optimizaciones de Base de Datos**:
   - Índices en columnas frecuentemente consultadas
   - Query optimization con joinedload
   - Connection pooling configurado

### Frontend (Next.js + React Query)

1. **Hook useCachedQuery**:
   - Caché en memoria del cliente
   - Stale-while-revalidate strategy
   - Persistencia opcional en localStorage

2. **Servicios con Caché**:
   - order-cache.service.ts con invalidación inteligente
   - Reducción de llamadas API redundantes

## Guía de Análisis de Resultados

### 1. **Interpretar Dashboard de Locust**

- **Total Requests**: Volumen total procesado
- **Failures**: Requests fallidas (debe ser < 1%)
- **Median/Average**: Tiempo de respuesta típico
- **Min/Max**: Límites de performance
- **Requests/s**: Throughput del sistema

### 2. **Identificar Cuellos de Botella**

```bash
# Exportar resultados a CSV para análisis detallado
locust -f locustfile.py --headless \
  --users=100 --spawn-rate=10 --run-time=5m \
  --csv=./results/analysis
```

Archivos generados:
- `analysis_requests.csv`: Métricas por endpoint
- `analysis_failures.csv`: Detalle de fallos
- `analysis_history.csv`: Evolución temporal

### 3. **Correlacionar con Métricas del Sistema**

Monitorear simultáneamente:
- Uso de CPU (%): Debe mantenerse < 80%
- Uso de Memoria (MB): Sin crecimiento continuo
- Conexiones DB activas: Dentro del pool configurado
- Hit rate de caché Redis: Debe ser > 70%

## Troubleshooting Común

### ❌ Problema: Alta latencia en endpoints GET

**Solución**:
1. Verificar hit rate de caché Redis
2. Revisar queries SQL con EXPLAIN ANALYZE
3. Aumentar TTL de caché si los datos son estáticos

### ❌ Problema: Memory leak en backend

**Solución**:
1. Usar `memory_profiler` para identificar fugas
2. Verificar que las sesiones de DB se cierran correctamente
3. Revisar tamaño de connection pool

### ❌ Problema: Rate limiting demasiado agresivo

**Solución**:
1. Ajustar configuración en `RateLimitMiddleware`
2. Excluir endpoints críticos del rate limiting
3. Implementar rate limiting por usuario, no global

## Integración con CI/CD

### GitHub Actions Example

```yaml
name: Load Testing

on:
  push:
    branches: [main]

jobs:
  load-test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install locust
      
      - name: Run load tests
        run: |
          locust -f load-testing/locustfile.py \
            --host=${{ secrets.STAGING_URL }} \
            --headless \
            --users=50 \
            --spawn-rate=5 \
            --run-time=5m \
            --stop-timeout=60
```

## Referencias

- [Documentación oficial de Locust](https://docs.locust.io/)
- [Mejores prácticas de load testing](https://martinfowler.com/articles/load-testing.html)
- [Guía de performance de FastAPI](https://fastapi.tiangolo.com/advanced/benchmarks/)

---

**Última actualización**: Junio 2024  
**Responsable**: Equipo de Ingeniería Delivery360

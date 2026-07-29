# Guía de Causas de Entrega Fallida - Delivery360

## Resumen del Cambio

Se ha implementado un sistema estandarizado de causas para entregas fallidas mediante un ENUM `DeliveryFailureCause`. Esto reemplaza la lógica ambigua anterior basada en análisis de texto y permite determinar automáticamente si el repartidor recibe el bono por intento fallido (1500 COP).

## Cambios Realizados

### 1. Backend - Modelos

**Archivo:** `app/models/delivery.py`
- Nuevo ENUM `DeliveryFailureCause` con 15 causas posibles
- Nueva columna `failure_cause` en el modelo `Delivery`
- Campo `issue_type` se mantiene para compatibilidad pero está deprecado

**Archivo:** `app/models/enums.py`
- ENUM `DeliveryFailureCause` con propiedad `is_bonificable`

### 2. Backend - API

**Archivo:** `app/api/v1/deliveries.py`
- Endpoint `POST /deliveries/{id}/fail` ahora requiere `failure_cause` (ENUM)
- Endpoint `PATCH /deliveries/{id}/status` soporta ambos formatos (legacy y nuevo)
- Validación automática de causas válidas
- Decisión de bono basada en `failure_cause.is_bonificable`

### 3. Base de Datos

**Migración:** `alembic/versions/20260728_add_delivery_failure_cause_enum.py`
- Crea tipo ENUM `deliveryfailurecause` en PostgreSQL
- Agrega columna `failure_cause` a tabla `deliveries`

## Causas Disponibles

### ✅ CAUSAS EXTERNAS (BONIFICABLES - 1500 COP)

| Valor ENUM | Descripción | Cuándo Usar |
|------------|-------------|-------------|
| `CLIENTE_NO_ESTA` | Cliente no estaba en el lugar | Llegaste y no había nadie |
| `CLIENTE_NO_CONTESTA` | No responde teléfono/portero | Llamas y no contestan |
| `DIRECCION_INCORRECTA` | Dirección errónea o incompleta | La dirección no coincide |
| `DIRECCION_NO_EXISTE` | Dirección no existe | No encuentras la ubicación |
| `COMERCIO_CERRADO` | Restaurante/tienda cerrado | No puedes recoger el pedido |
| `CLIENTE_RECHAZA` | Cliente rechazó el pedido | El cliente no quiere el pedido |
| `ZONA_INSEGURA` | Zona peligrosa o inaccesible | No puedes entrar por seguridad |
| `FUERZA_MAYOR` | Lluvia extrema, bloqueo, accidente | Eventos fuera de control |
| `EDIFICIO_RESTRINGIDO` | Acceso denegado por seguridad | Seguridad no te deja pasar |

### ❌ CAUSAS DEL REPARTIDOR (NO BONIFICABLES)

| Valor ENUM | Descripción | Cuándo Usar |
|------------|-------------|-------------|
| `REPARTIDOR_NO_QUIERE_ENTREGAR` | Negativa por comodidad | No quieres hacer la entrega |
| `REPARTIDOR_LLEGO_TARDE` | Llegó fuera del tiempo SLA | Se te hizo tarde |
| `REPARTIDOR_ERROR_PROPIO` | Error operativo del rider | Te equivocaste en algo |
| `REPARTIDOR_VEHICULO_FALLA` | Falla mecánica de la moto | Tu vehículo falló |
| `REPARTIDOR_SIN_BATERIA` | Celular/moto sin batería | Te quedaste sin batería |
| `OTRO_REPARTIDOR` | Otro repartidor tomó la entrega | Confusión de asignación |

## Uso desde el Frontend

### Endpoint: `POST /api/v1/deliveries/{delivery_id}/fail`

```json
{
  "failure_cause": "CLIENTE_NO_ESTA",
  "issue_description": "Llegué al apartamento 105 y no había nadie. Llamé 3 veces al cliente y no contestó."
}
```

### Respuesta Exitosa (Causa Bonificable)

```json
{
  "id": "uuid-delivery",
  "status": "FALLIDA",
  "failure_cause": "CLIENTE_NO_ESTA",
  "bonus_applied": true,
  "bonus_amount": 1500.00,
  "is_bonificable": true
}
```

### Respuesta Exitosa (Causa NO Bonificable)

```json
{
  "id": "uuid-delivery",
  "status": "FALLIDA",
  "failure_cause": "REPARTIDOR_SIN_BATERIA",
  "bonus_applied": false,
  "bonus_amount": 0.00,
  "is_bonificable": false
}
```

### Lista de Causas Válidas

```bash
GET /api/v1/deliveries/failure-causes  # (Endpoint opcional para obtener lista)
```

O usa esta lista estática en el frontend:

```javascript
const FAILURE_CAUSES = {
  BONIFICABLES: [
    { value: "CLIENTE_NO_ESTA", label: "Cliente no estaba", bonificable: true },
    { value: "CLIENTE_NO_CONTESTA", label: "No responde teléfono", bonificable: true },
    { value: "DIRECCION_INCORRECTA", label: "Dirección incorrecta", bonificable: true },
    { value: "DIRECCION_NO_EXISTE", label: "Dirección no existe", bonificable: true },
    { value: "COMERCIO_CERRADO", label: "Comercio cerrado", bonificable: true },
    { value: "CLIENTE_RECHAZA", label: "Cliente rechazó pedido", bonificable: true },
    { value: "ZONA_INSEGURA", label: "Zona insegura", bonificable: true },
    { value: "FUERZA_MAYOR", label: "Fuerza mayor", bonificable: true },
    { value: "EDIFICIO_RESTRINGIDO", label: "Edificio restringido", bonificable: true },
  ],
  NO_BONIFICABLES: [
    { value: "REPARTIDOR_NO_QUIERE_ENTREGAR", label: "No quiere entregar", bonificable: false },
    { value: "REPARTIDOR_LLEGO_TARDE", label: "Llegó tarde", bonificable: false },
    { value: "REPARTIDOR_ERROR_PROPIO", label: "Error propio", bonificable: false },
    { value: "REPARTIDOR_VEHICULO_FALLA", label: "Falla vehículo", bonificable: false },
    { value: "REPARTIDOR_SIN_BATERIA", label: "Sin batería", bonificable: false },
    { value: "OTRO_REPARTIDOR", label: "Otro repartidor", bonificable: false },
  ]
};
```

## Migración de Datos Existentes

Los registros anteriores mantienen su campo `issue_type` como string. Para reportes históricos:
- Si `issue_analysis_result` contiene "causa externa" → tratar como bonificable
- Si `issue_type` está en lista legacy (`cliente_no_esta`, `direccion_incorrecta`, etc.) → bonificable

## Ejecutar Migración

```bash
# Desde el contenedor backend
docker compose exec backend alembic upgrade head
```

## Pruebas

```bash
# Probar causa bonificable
curl -X POST http://localhost:8000/api/v1/deliveries/{id}/fail \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"failure_cause": "CLIENTE_NO_ESTA", "issue_description": "Test"}'

# Probar causa NO bonificable
curl -X POST http://localhost:8000/api/v1/deliveries/{id}/fail \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"failure_cause": "REPARTIDOR_SIN_BATERIA", "issue_description": "Test"}'

# Probar causa inválida (debe retornar error 400)
curl -X POST http://localhost:8000/api/v1/deliveries/{id}/fail \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"failure_cause": "CAUSA_INVALIDA"}'
```

## Beneficios

1. **Claridad**: El repartidor sabe exactamente qué causa seleccionar
2. **Transparencia**: El bono se aplica automáticamente según la causa
3. **Consistencia**: Elimina ambigüedad del análisis de texto
4. **Trazabilidad**: Reportes precisos por tipo de falla
5. **Justicia**: Solo se paga cuando la falla es externa al repartidor

# Guía de Pruebas: Entregas Fallidas y Bono por Intento Fallido

## Resumen de Cambios Implementados

1. **`app/utils/delivery_analysis.py`**: Clase `DeliveryIssueAnalyzer` con listas de palabras clave en español para detectar causas externas vs. culpas del repartidor.

2. **`app/api/v1/deliveries.py`**: Endpoint `/deliveries/{id}/fail` actualizado para:
   - Capturar `issue_description` del payload
   - Analizar automáticamente la causa usando `DeliveryIssueAnalyzer`
   - Crear registro financiero si es causa externa
   - Retornar información del bono aplicado en la respuesta

3. **`app/models/delivery.py`**: Nuevo campo `issue_analysis_result` para guardar el análisis.

4. **`app/models/order.py`**: Nuevo campo `failure_cause_external` para indicar si la falla fue externa.

5. **`scripts/setup_failed_attempt_bonus.sql`**: Script SQL para configurar el setting `rider_failed_attempt_bonus`.

---

## 1. Ejecutar Script SQL de Configuración

Antes de probar, asegúrate de que el setting exista en la base de datos:

```bash
# Conéctate a tu base de datos PostgreSQL y ejecuta:
psql -U tu_usuario -d tu_base_de_datos -f /workspace/backend/scripts/setup_failed_attempt_bonus.sql
```

O ejecuta manualmente:
```sql
INSERT INTO platform_settings (key, value, description, is_active, created_at, updated_at)
VALUES (
    'rider_failed_attempt_bonus',
    '1500.00',
    'Bono pagado al repartidor cuando la entrega falla por causa externa.',
    TRUE,
    NOW(),
    NOW()
)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();
```

Verifica que el setting existe:
```sql
SELECT key, value FROM platform_settings WHERE key = 'rider_failed_attempt_bonus';
-- Debería retornar: rider_failed_attempt_bonus | 1500.00
```

---

## 2. Pruebas con cURL / Postman

### A. Caso: Causa Externa (Cliente no estaba) - DEBE APLICAR BONO

**Endpoint:** `POST /api/v1/deliveries/{delivery_id}/fail`

**Headers:**
```
Content-Type: application/json
Authorization: Bearer TU_TOKEN_DE_ACCESO
```

**Payload (Causa Externa):**
```json
{
    "issue_type": "cliente_no_esta",
    "issue_description": "El cliente no estaba en casa, nadie abrió la puerta después de llamar varias veces"
}
```

**Respuesta Esperada:**
```json
{
    "id": "...",
    "status": "fallida",
    "bonus_applied": true,
    "bonus_amount": 1500.0,
    "issue_analysis": {
        "is_external_fault": true,
        "reason": "Causa externa detectada: 'cliente no estaba'",
        "confidence": "high"
    }
}
```

**Verificación en Base de Datos:**
```sql
-- Verificar el registro financiero creado
SELECT 
    id, 
    rider_id, 
    amount, 
    transaction_type, 
    description, 
    status,
    created_at
FROM financials 
WHERE transaction_type = 'PAGO_INTENTO_FALLIDO' 
ORDER BY created_at DESC 
LIMIT 1;

-- Deberías ver un registro con amount = 1500.00
```

---

### B. Caso: Culpa del Repartidor (Se cayó la comida) - NO DEBE APLICAR BONO

**Payload (Culpa Rider):**
```json
{
    "issue_type": "producto_dañado",
    "issue_description": "Se me cayó la comida al subir las escaleras y se derramó todo"
}
```

**Respuesta Esperada:**
```json
{
    "id": "...",
    "status": "fallida",
    "bonus_applied": false,
    "bonus_amount": 0.0,
    "issue_analysis": {
        "is_external_fault": false,
        "reason": "Indicio de culpa del repartidor: 'se me cayó'",
        "confidence": "high"
    }
}
```

**Verificación en Base de Datos:**
```sql
-- No debería haber creado un nuevo registro financiero para este caso
-- (a menos que ya existiera uno previo con la misma idempotency_key)
SELECT COUNT(*) FROM financials 
WHERE transaction_type = 'PAGO_INTENTO_FALLIDO' 
AND description LIKE '%se me cayó%';
-- Debería ser 0 o no mostrar registros recientes
```

---

### C. Caso: Comercio Cerrado - DEBE APLICAR BONO

**Payload:**
```json
{
    "issue_type": "comercio_cerrado",
    "issue_description": "El restaurante estaba cerrado, no había nadie para entregar el pedido"
}
```

**Respuesta Esperada:**
```json
{
    "bonus_applied": true,
    "bonus_amount": 1500.0,
    "issue_analysis": {
        "is_external_fault": true,
        "reason": "Causa externa detectada: 'comercio cerrado'",
        "confidence": "high"
    }
}
```

---

### D. Caso: Dirección Incorrecta - DEBE APLICAR BONO

**Payload:**
```json
{
    "issue_type": "direccion_incorrecta",
    "issue_description": "La dirección está mal, no existe la calle indicada en el sistema"
}
```

**Respuesta Esperada:**
```json
{
    "bonus_applied": true,
    "bonus_amount": 1500.0,
    "issue_analysis": {
        "is_external_fault": true,
        "reason": "Causa externa detectada: 'direccion incorrecta'",
        "confidence": "high"
    }
}
```

---

## 3. Comandos cURL Listos para Usar

Reemplaza `{DELIVERY_ID}` y `{TOKEN}` con valores reales:

### Causa Externa (Cliente no estaba):
```bash
curl -X POST "http://localhost:8000/api/v1/deliveries/{DELIVERY_ID}/fail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {TOKEN}" \
  -d '{
    "issue_type": "cliente_no_esta",
    "issue_description": "El cliente no estaba en casa, nadie abrió la puerta"
  }'
```

### Culpa del Repartidor (Se cayó):
```bash
curl -X POST "http://localhost:8000/api/v1/deliveries/{DELIVERY_ID}/fail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {TOKEN}" \
  -d '{
    "issue_type": "producto_dañado",
    "issue_description": "Se me cayó la comida al subir las escaleras"
  }'
```

### Comercio Cerrado:
```bash
curl -X POST "http://localhost:8000/api/v1/deliveries/{DELIVERY_ID}/fail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {TOKEN}" \
  -d '{
    "issue_type": "comercio_cerrado",
    "issue_description": "El comercio estaba cerrado, no había nadie"
  }'
```

---

## 4. Consultas SQL de Verificación

### Ver todos los bonos aplicados hoy:
```sql
SELECT 
    f.id,
    f.rider_id,
    f.amount,
    f.transaction_type,
    f.description,
    f.created_at,
    d.issue_description,
    d.issue_analysis_result
FROM financials f
LEFT JOIN deliveries d ON f.source_id::uuid = d.id
WHERE f.transaction_type = 'PAGO_INTENTO_FALLIDO'
ORDER BY f.created_at DESC;
```

### Ver entregas fallidas con su análisis:
```sql
SELECT 
    id,
    status,
    issue_type,
    issue_description,
    issue_analysis_result,
    has_issues,
    updated_at
FROM deliveries
WHERE status = 'fallida'
ORDER BY updated_at DESC
LIMIT 10;
```

### Ver configuración del bono:
```sql
SELECT key, value, description, is_active
FROM platform_settings
WHERE key = 'rider_failed_attempt_bonus';
```

---

## 5. Palabras Clave Reconocidas por el Analizador

### Causas Externas (SÍ generan bono):
- "cliente no estaba"
- "no habia nadie"
- "nadie abrio"
- "puerta cerrada"
- "direccion incorrecta"
- "direccion mala"
- "no existe la direccion"
- "comercio cerrado"
- "restaurante cerrado"
- "tienda cerrada"
- "cliente no contesta"
- "telefono apagado"
- "no responde"
- "zona peligrosa"
- "inseguridad"
- "bloqueo"
- "protesta"
- "lluvia fuerte"
- "accidente via"
- "calles inundadas"

### Culpa del Repartidor (NO generan bono):
- "se me cayo"
- "se cayó la comida"
- "derrame"
- "olvide"
- "se me olvido"
- "llegue tarde"
- "me equivoque"
- "confundi la direccion"
- "error mio"
- "moto se daño"
- "ponchadura"
- "me quede sin bateria"
- "choque"
- "no quise subir"
- "pereza"
- "lejos"
- "mucha fila"

---

## 6. Solución de Problemas

### El bono no se aplica:
1. Verifica que el setting exista: `SELECT * FROM platform_settings WHERE key = 'rider_failed_attempt_bonus';`
2. Revisa los logs del backend para ver si hay errores al crear el registro financiero.
3. Asegúrate de que `issue_description` contenga palabras clave reconocidas.

### El análisis no detecta la causa correcta:
1. Revisa que el texto esté en español y use términos similares a las listas del analizador.
2. Si es un caso límite, el analizador retorna `confidence: "low"` y no aplica bono por defecto.

### Error 404 en el endpoint:
- Asegúrate de que el `delivery_id` sea un UUID válido y que la entrega exista.
- Verifica que la entrega esté en un estado permitido para fallar (`pendiente`, `iniciada`, `en_ruta`, etc.).

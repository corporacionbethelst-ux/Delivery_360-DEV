# 🔧 Solución al Error del ENUM `payoutstatus`

## 📋 PROBLEMA

El script `seed_data.py` falla con el siguiente error:

```
asyncpg.exceptions.InvalidTextRepresentationError: invalid input value for enum payoutstatus: "APROBADO"
```

**Causa Raíz:** El tipo ENUM `payoutstatus` en la base de datos no tiene los valores en español esperados por el código.

---

## ✅ SOLUCIÓN RÁPIDA (Recomendada)

Ejecuta el script de corrección automática:

```bash
cd /workspace/backend
./scripts/fix_enum_payoutstatus.sh
```

Este script:
1. Verifica si el ENUM `payoutstatus` existe
2. Lo crea con los valores correctos si no existe
3. Muestra los valores actuales para verificación

Luego ejecuta el seed data nuevamente:
```bash
docker compose exec backend python -m scripts.seed_data
```

---

## 🔍 SOLUCIÓN MANUAL (Alternativa)

Si prefieres ejecutar los comandos manualmente:

### Paso 1: Verificar estado actual del ENUM

```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
SELECT unnest(enum_range(NULL::payoutstatus)) AS valores_actuales;
EOF
```

**Resultado esperado (6 filas):**
```
valores_actuales
----------------
PENDIENTE
APROBADO
EN_PROCESO
COMPLETADO
RECHAZADO
FALLIDO
```

### Paso 2: Si el ENUM no existe o tiene valores incorrectos

```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
-- Eliminar el enum antiguo si existe
DROP TYPE IF EXISTS payoutstatus CASCADE;

-- Crear nuevo enum con valores en español
CREATE TYPE payoutstatus AS ENUM (
    'PENDIENTE',
    'APROBADO',
    'EN_PROCESO',
    'COMPLETADO',
    'RECHAZADO',
    'FALLIDO'
);

-- Verificar que quedó correcto
SELECT unnest(enum_range(NULL::payoutstatus)) AS valores_finales;
EOF
```

### Paso 3: Ejecutar seed data

```bash
docker compose exec backend python -m scripts.seed_data
```

---

## 📊 ¿POR QUÉ OCURRE ESTE ERROR?

1. **Migración 20260817**: Crea el ENUM `payoutstatus_fase7` con valores en inglés (`PENDING`, `APPROVED`, etc.)
2. **Migración 20260818**: 
   - Crea nuevo ENUM `payoutstatus` con valores en español
   - Migra las columnas para usar el nuevo ENUM
   - Elimina el ENUM antiguo `payoutstatus_fase7`
3. **Problema**: Si la migración 20260818 falló a mitad de camino, puedes quedar con:
   - Tablas creadas pero apuntando al ENUM antiguo
   - O el ENUM nuevo no fue creado correctamente

---

## 🛠️ VERIFICACIÓN POST-CORRECCIÓN

Después de aplicar la solución, verifica que todo esté correcto:

```bash
# 1. Verificar ENUM
docker compose exec db psql -U admin -d delivery360 -c "SELECT unnest(enum_range(NULL::payoutstatus));"

# 2. Verificar estructura de tabla
docker compose exec db psql -U admin -d delivery360 -c "\d payout_requests"

# 3. Ejecutar seed data
docker compose exec backend python -m scripts.seed_data

# 4. Verificar datos insertados
docker compose exec db psql -U admin -d delivery360 << 'EOF'
SELECT 
    pr.id,
    pr.rider_id,
    r.name AS rider_name,
    pr.amount_cents,
    pr.status,
    pr.created_at
FROM payout_requests pr
JOIN riders r ON r.id = pr.rider_id
ORDER BY pr.created_at DESC
LIMIT 5;
EOF
```

---

## 📝 ARCHIVOS DE SOPORTE CREADOS

| Archivo | Propósito |
|---------|-----------|
| `scripts/fix_enum_payoutstatus.sh` | Script bash automatizado |
| `scripts/fix_payoutstatus_enum.sql` | Script SQL manual |
| `docs/FIX_ENUM_PAYOUTSTATUS.md` | Esta documentación |

---

## ⚠️ NOTAS IMPORTANTES

1. **No modificar la migración 20260818**: Ya está correcta con los valores en español.
2. **El problema es la BD, no el código**: La migración no se aplicó completamente.
3. **Seed data usa `PayoutRequestStatus.APROBADO`**: Este valor debe existir en la BD.
4. **Si usas Docker Desktop**: Asegúrate de que los contenedores estén corriendo antes de ejecutar los scripts.

---

## 🎯 ESTADO ESPERADO DESPUÉS DE LA CORRECCIÓN

- ✅ ENUM `payoutstatus` existe con 6 valores en español
- ✅ Tabla `payout_requests` usa el ENUM `payoutstatus`
- ✅ Seed data ejecuta sin errores
- ✅ Retiros demo se crean con estados: `PENDIENTE`, `APROBADO`, `RECHAZADO`

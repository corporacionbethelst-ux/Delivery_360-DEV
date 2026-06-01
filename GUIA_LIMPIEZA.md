# 🧹 GUÍA DE LIMPIEZA Y REINICIO COMPLETO - DELIVERY360

## Problema Detectado
La API devuelve `null` en `customer_name` y `rider.first_name` debido a **datos inconsistentes o faltantes** en la base de datos, NO por errores en el código.

## Diferencia entre seed.py y seed_data.py

| Archivo | Propósito | ¿Usar? |
|---------|-----------|--------|
| `app/core/seed.py` | Seeds básicos internos, posiblemente incompletos | ❌ NO USAR |
| `scripts/seed_data.py` | Script completo con datos relacionales reales (riders, orders, deliveries vinculados) | ✅ USAR ESTE |

## Paso a Paso para Eliminar TODA Inconsistencia

### Opción A: Ejecutar Script Automatizado (RECOMENDADO)

```bash
cd /workspace
./CLEAN_AND_SEED.sh
```

Este script hace TODO automáticamente:
1. Detiene contenedores
2. Elimina volúmenes de PostgreSQL (borra TODOS los datos)
3. Reinicia contenedores desde cero
4. Ejecuta migraciones
5. Ejecuta `seed_data.py` (el script correcto)
6. Valida integridad de datos
7. Prueba el endpoint `/api/v1/deliveries`

### Opción B: Pasos Manuales (Si prefieres control total)

#### 1. Detener contenedores
```bash
cd /workspace/backend
docker compose down
```

#### 2. Eliminar volúmenes de base de datos
```bash
docker volume rm backend_postgres_data
```

#### 3. Limpiar contenedores huérfanos
```bash
docker container prune -f
docker network prune -f
```

#### 4. Iniciar contenedores
```bash
docker compose up -d --build
```

#### 5. Esperar 30 segundos (PostgreSQL necesita tiempo)
```bash
sleep 30
```

#### 6. Verificar estado
```bash
docker compose ps
```

#### 7. Ejecutar migraciones
```bash
docker compose exec backend alembic upgrade head
```

#### 8. Ejecutar seed_data.py (CRÍTICO)
```bash
docker compose exec backend python scripts/seed_data.py
```

#### 9. Validar datos
```bash
# Verificar usuarios
docker compose exec postgres psql -U delivery_user -d delivery_db \
  -c "SELECT role, COUNT(*) FROM users GROUP BY role;"

# Verificar riders
docker compose exec postgres psql -U delivery_user -d delivery_db \
  -c "SELECT COUNT(*) FROM riders;"

# Verificar entregas con datos enriquecidos
docker compose exec postgres psql -U delivery_user -d delivery_db \
  -c "SELECT d.id, o.customer_name, u.first_name as rider_name 
      FROM deliveries d 
      JOIN orders o ON d.order_id = o.id 
      JOIN riders r ON d.rider_id = r.id 
      JOIN users u ON r.user_id = u.id 
      LIMIT 5;"
```

#### 10. Probar endpoint
```bash
# Obtener token
TOKEN=$(curl -s -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=super@delivery360.com&password=Admin123!" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Probar deliveries
curl -s -X GET "http://localhost:8000/api/v1/deliveries" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool | head -50
```

## Credenciales de Acceso

| Rol | Email | Contraseña |
|-----|-------|------------|
| Superadmin | super@delivery360.com | Admin123! |
| Repartidor | rider1@delivery360.com | Rider123! |

## ¿Qué Datos se Generan?

El script `seed_data.py` crea:
- ✅ 3 usuarios administrativos + 10 clientes test
- ✅ 15 repartidores con ubicaciones GPS realistas (Bogotá)
- ✅ 50 órdenes con items reales (hamburguesas, sushi, etc.)
- ✅ Entregas vinculadas correctamente a orders y riders
- ✅ Rutas GPS simuladas para entregas completadas
- ✅ Registros financieros y de productividad

## Verificación Final

Después de ejecutar el script, verifica en tu frontend Next.js:
1. Inicia sesión con `super@delivery360.com` / `Admin123!`
2. Navega a la lista de entregas
3. **Debes ver:**
   - ✅ `customer_name`: Nombres reales (ej. "Juan Pérez")
   - ✅ `rider.first_name`: Nombres reales (ej. "Repartidor 1")
   - ✅ No más "Cliente Desconocido" o "Sin asignar"

## Solución de Problemas Comunes

### Error: "No se pudo conectar a la base de datos"
```bash
# Verifica que PostgreSQL esté listo
docker compose logs postgres | tail -20
# Busca: "database system is ready to accept connections"
```

### Error: "Credenciales inválidas" al hacer login
```bash
# Verifica que el usuario exista
docker compose exec postgres psql -U delivery_user -d delivery_db \
  -c "SELECT email, role FROM users WHERE email='super@delivery360.com';"
```

### Error: "Token expirado" rápidamente
```bash
# Revisa la configuración de JWT en .env
# TOKEN_EXPIRE_MINUTES debería ser >= 30
```

### El endpoint devuelve lista vacía
```bash
# Verifica que seed_data.py se ejecutó correctamente
docker compose exec postgres psql -U delivery_user -d delivery_db \
  -c "SELECT COUNT(*) FROM deliveries;"
# Debería retornar ~30-40 entregas
```

## Notas Importantes

⚠️ **ADVERTENCIA**: Este proceso **ELIMINA TODOS LOS DATOS** existentes. Solo úsalo en desarrollo.

📝 **Para producción**: Usa migraciones incrementales y backups, nunca este script.

🔄 **Frecuencia recomendada**: Ejecuta este proceso cada vez que:
- Cambies el esquema de la base de datos
- Los datos de prueba se vuelvan inconsistentes
- Después de clonar el repositorio en una nueva máquina

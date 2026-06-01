# 📁 Diferencia entre seed.py y seed_data.py

## RESUMEN RÁPIDO

| Característica | `app/core/seed.py` | `scripts/seed_data.py` |
|----------------|-------------------|------------------------|
| **Propósito** | Seed MÍNIMO de inicialización | Seed COMPLETO con datos realistas |
| **Cuándo usar** | Primera vez que instalas el sistema | Cada vez que quieres datos de prueba |
| **Datos que crea** | Solo superusuario y estructura básica | Usuarios, riders, órdenes, entregas, rutas, finanzas |
| **Tamaño** | ~266 líneas | ~470 líneas |
| **Complejidad** | Baja | Alta (datos mock realistas) |

---

## 1. `app/core/seed.py` - Seed Básico de Inicialización

### Propósito:
Crear **únicamente** lo esencial para que el sistema pueda arrancar por primera vez:
- Superusuario administrador
- Verificar que las tablas existan

### Qué crea:
```python
# Solo esto:
- Usuario: super@delivery360.com / Admin123!
- Rol: SUPERADMIN
- Is_active: True
```

### Cuándo ejecutarlo:
- ✅ La PRIMERA vez que instalas Delivery360
- ✅ Cuando haces un deploy desde cero
- ❌ NO lo uses para tener datos de prueba

### Código clave:
```python
async def seed_database():
    # 1. Crear tablas si no existen
    # 2. Crear superusuario SI NO EXISTE
    admin_email = settings.FIRST_SUPERUSER_EMAIL
    # ... solo crea el admin básico
```

---

## 2. `scripts/seed_data.py` - Seed Completo de Datos de Prueba

### Propósito:
Generar un **entorno de prueba realista** con todos los datos necesarios para desarrollar y testear:
- Múltiples usuarios (admins, operadores, clientes)
- Riders con perfiles completos
- Órdenes con items reales (hamburguesas, sushi, etc.)
- Entregas vinculadas a órdenes y riders
- Rutas GPS simuladas
- Finanzas y productividad

### Qué crea:
```python
# Datos completos:
- 3 admins (superadmin, gerente, operador)
- 10 clientes test
- 15 riders con ubicaciones en Bogotá
- 50-60 órdenes con estados variados
- Entregas asociadas
- Rutas con puntos GPS
- Transacciones financieras
- Records de productividad
```

### Datos mock realistas:
```python
RESTAURANTS = [
    {"name": "Burger King Zona G", "address": "Cra 4 #85-10, Chapinero"},
    {"name": "Pizza Hut Parque 93", "address": "Cll 93B #13-30"},
    # ...
]

CUSTOMER_NAMES = [
    "Juan Pérez", "María Rodríguez", "Carlos López", 
    # ... 15 nombres realistas
]

MENUS = {
    "BURGER": [{"name": "Whopper Doble", "price": 28000}, ...],
    "PIZZA": [{"name": "Pizza Pepperoni Familiar", "price": 45000}, ...],
    # ...
}
```

### Cuándo ejecutarlo:
- ✅ Cuando necesitas datos de prueba para desarrollar
- ✅ Después de resetear la base de datos
- ✅ Para demos o presentaciones
- ❌ NO en producción

### Credenciales que crea:
```
Superadmin: super@delivery360.com / Admin123!
Repartidor: rider1@delivery360.com / Rider123!
            rider2@delivery360.com / Rider123!
            ...
```

---

## FLUJO RECOMENDADO

### Instalación Inicial (Producción):
```bash
# Solo una vez
python app/core/seed.py
```

### Desarrollo/Pruebas:
```bash
# Primero el seed básico (opcional, ya puede estar hecho)
python app/core/seed.py

# Luego el seed completo con datos
python scripts/seed_data.py
```

### Reset Completo de BD:
```bash
# Borrar todas las tablas
psql -U admin -d delivery360 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# Recrear todo
python app/core/seed.py
python scripts/seed_data.py
```

---

## ¿POR QUÉ DOS ARCHIVOS?

1. **Separación de responsabilidades:**
   - `seed.py`: Infraestructura mínima
   - `seed_data.py`: Datos de negocio para testing

2. **Seguridad:**
   - En producción SOLO ejecutas `seed.py` (sin datos falsos)
   - En desarrollo ejecutas ambos

3. **Mantenibilidad:**
   - Es más fácil actualizar datos mock en un archivo separado
   - El seed básico cambia poco, el seed de datos cambia frecuentemente

---

## EN TU CASO ESPECÍFICO

Para solucionar los problemas de null en `customer_name` y `rider.first_name`:

```bash
cd /workspace/backend

# Ejecutar SOLO el seed_data.py (ya que el básico probablemente ya existe)
python scripts/seed_data.py

# Esto va a:
# 1. Crear riders con user_id válido
# 2. Crear órdenes con customer_name
# 3. Vincular entregas correctamente
# 4. Los joins del endpoint funcionarán
```


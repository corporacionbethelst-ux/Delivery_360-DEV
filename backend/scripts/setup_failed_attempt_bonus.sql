-- Script SQL para configurar el bono por intento fallido de entrega
-- Este script asegura que el setting 'rider_failed_attempt_bonus' exista en la BD
-- con un valor por defecto de 1500 COP (pesos colombianos).

-- Insertar o actualizar el setting rider_failed_attempt_bonus
INSERT INTO platform_settings (key, value, description, is_active, created_at, updated_at)
VALUES (
    'rider_failed_attempt_bonus',
    '1500.00',
    'Bono pagado al repartidor cuando la entrega falla por causa externa (cliente no estaba, dirección incorrecta, comercio cerrado, etc.). Valor en COP.',
    TRUE,
    NOW(),
    NOW()
)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();

-- Verificar que el setting se haya insertado/actualizado correctamente
SELECT key, value, description, is_active 
FROM platform_settings 
WHERE key = 'rider_failed_attempt_bonus';

-- Opcional: Otros settings relacionados que podrían ser útiles
-- INSERT INTO platform_settings (key, value, description, is_active, created_at, updated_at)
-- VALUES (
--     'rider_failed_attempt_max_per_day',
--     '5',
--     'Número máximo de bonos por intentos fallidos que un repartidor puede recibir por día.',
--     TRUE,
--     NOW(),
--     NOW()
-- )
-- ON CONFLICT (key) DO UPDATE SET
--     value = EXCLUDED.value,
--     description = EXCLUDED.description,
--     is_active = EXCLUDED.is_active,
--     updated_at = NOW();

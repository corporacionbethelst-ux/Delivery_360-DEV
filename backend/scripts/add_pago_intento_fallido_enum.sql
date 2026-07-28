-- Migración: Agregar valor 'PAGO_INTENTO_FALLIDO' al ENUM transactiontype
-- Ejecutar esto en la base de datos para solucionar el error de entrega fallida

-- Verificar si el valor ya existe antes de agregarlo
DO $$
BEGIN
    -- Verificar si el tipo enum existe y si el valor ya está presente
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
        WHERE pg_type.typname = 'transactiontype'
        AND pg_enum.enumlabel = 'PAGO_INTENTO_FALLIDO'
    ) THEN
        -- Agregar el nuevo valor al ENUM
        ALTER TYPE transactiontype ADD VALUE 'PAGO_INTENTO_FALLIDO';
        RAISE NOTICE 'Valor PAGO_INTENTO_FALLIDO agregado exitosamente al ENUM transactiontype';
    ELSE
        RAISE NOTICE 'El valor PAGO_INTENTO_FALLIDO ya existe en el ENUM transactiontype';
    END IF;
END
$$;

-- Verificación final
SELECT enumlabel
FROM pg_enum
JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
WHERE pg_type.typname = 'transactiontype'
ORDER BY enumsortorder;
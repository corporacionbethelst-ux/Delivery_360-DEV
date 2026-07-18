"""add finance features bonus multiplier and settings

Revision ID: 20260610_finance_features
Revises: 20260609_platform_settings
Create Date: 2026-06-10

Consolidated migration for:
1. Add bonus_multiplier column to zones table (Fase 3)
2. Seed rider delivery and failed attempt bonuses in platform_settings (Fases 1 & 2)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260610_finance_features"
down_revision: Union[str, None] = "20260609_platform_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply consolidated finance features migration."""
    
    # ==========================================================================
    # 1. AGREGAR COLUMNA bonus_multiplier A TABLA zones (FASE 3)
    # ==========================================================================
    print("📍 Adding bonus_multiplier column to zones table...")
    
    # Usamos SQL directo para mayor compatibilidad
    op.execute("""
        ALTER TABLE zones 
        ADD COLUMN IF NOT EXISTS bonus_multiplier FLOAT DEFAULT 1.0 NOT NULL
    """)
    
    # Agregar comentario descriptivo
    op.execute("""
        COMMENT ON COLUMN zones.bonus_multiplier 
        IS 'Multiplicador de bono para repartidores en esta zona (Fase 3). Ej: 1.5 = 50% extra.'
    """)
    
    # Actualizar zonas específicas con multiplicadores de ejemplo
    # Zona NORTE: alta dificultad, paga 1.5x
    op.execute("""
        UPDATE zones 
        SET bonus_multiplier = 1.5 
        WHERE code IN ('NORTE', 'NRT', 'ZONA_NORTE')
    """)
    
    # Zona SUR: dificultad media, paga 1.2x
    op.execute("""
        UPDATE zones 
        SET bonus_multiplier = 1.2 
        WHERE code IN ('SUR', 'ZONA_SUR')
    """)
    
    # Zona CENTRO: estándar, paga 1.0x (valor por defecto)
    op.execute("""
        UPDATE zones 
        SET bonus_multiplier = 1.0 
        WHERE code IN ('CENTRO', 'CTR', 'ZONA_CENTRO')
    """)
    
    print("✅ bonus_multiplier column added and configured")
    
    # ==========================================================================
    # 2. CONFIGURACIÓN DE BONOS EN platform_settings (FASES 1 & 2)
    # ==========================================================================
    print("⚙️ Seeding platform settings for rider bonuses...")
    
    # Fase 1: Bono por entrega exitosa (2500 COP)
    op.execute("""
        INSERT INTO platform_settings (key, value, description, updated_at)
        VALUES (
            'rider_delivery_bonus', 
            '2500', 
            'Bono en COP por cada entrega completada exitosamente (Fase 1).',
            NOW()
        )
        ON CONFLICT (key) DO UPDATE SET 
            value = '2500',
            description = 'Bono en COP por cada entrega completada exitosamente (Fase 1).',
            updated_at = NOW()
    """)
    
    # Fase 2: Bono por intento fallido (culpa del cliente) (1500 COP)
    op.execute("""
        INSERT INTO platform_settings (key, value, description, updated_at)
        VALUES (
            'rider_failed_attempt_bonus', 
            '1500', 
            'Bono en COP por intento de entrega fallido por causa del cliente (Fase 2).',
            NOW()
        )
        ON CONFLICT (key) DO UPDATE SET 
            value = '1500',
            description = 'Bono en COP por intento de entrega fallido por causa del cliente (Fase 2).',
            updated_at = NOW()
    """)
    
    print("✅ Platform settings for bonuses seeded")
    
    # ==========================================================================
    # 3. VERIFICACIÓN RÁPIDA (LOGS)
    # ==========================================================================
    print("\n📊 Migration Summary:")
    print("   - Zones: bonus_multiplier column added (default 1.0)")
    print("   - Platform Settings:")
    print("     * rider_delivery_bonus = 2500 COP")
    print("     * rider_failed_attempt_bonus = 1500 COP")
    print("\n💡 Testing Tips:")
    print("   - Assign rider to zone with bonus_multiplier > 1.0 (e.g., NORTE = 1.5)")
    print("   - Complete delivery: amount should be 2500 * multiplier")
    print("   - Failed attempt (direccion_incorrecta): amount should be 1500 COP")


def downgrade() -> None:
    """Remove consolidated finance features."""
    
    # Eliminar configuraciones de bonos
    op.execute("""
        DELETE FROM platform_settings 
        WHERE key IN ('rider_delivery_bonus', 'rider_failed_attempt_bonus')
    """)
    
    # Eliminar columna bonus_multiplier (si es posible)
    # Nota: Esto puede fallar si hay dependencias, pero es parte del downgrade completo
    op.execute("""
        ALTER TABLE zones 
        DROP COLUMN IF EXISTS bonus_multiplier
    """)
    
    print("🔄 Downgrade completed: removed finance features")

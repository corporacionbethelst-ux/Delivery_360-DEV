"""add delivery_failure_cause enum to deliveries

Revision ID: 20260613
Revises: 20260612
Create Date: 2026-07-28

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260613'
down_revision = '20260612'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear el tipo ENUM deliveryfailurecause en PostgreSQL
    delivery_failure_cause_enum = sa.Enum(
        'CLIENTE_NO_ESTA',
        'CLIENTE_NO_CONTESTA',
        'DIRECCION_INCORRECTA',
        'DIRECCION_NO_EXISTE',
        'COMERCIO_CERRADO',
        'CLIENTE_RECHAZA',
        'ZONA_INSEGURA',
        'FUERZA_MAYOR',
        'EDIFICIO_RESTRINGIDO',
        'REPARTIDOR_NO_QUIERE_ENTREGAR',
        'REPARTIDOR_LLEGO_TARDE',
        'REPARTIDOR_ERROR_PROPIO',
        'REPARTIDOR_VEHICULO_FALLA',
        'REPARTIDOR_SIN_BATERIA',
        'OTRO_REPARTIDOR',
        name='deliveryfailurecause'
    )
    delivery_failure_cause_enum.create(op.get_bind())
    
    # Agregar la columna failure_cause a la tabla deliveries
    op.add_column(
        'deliveries',
        sa.Column(
            'failure_cause',
            delivery_failure_cause_enum,
            nullable=True
        )
    )


def downgrade() -> None:
    # Eliminar la columna failure_cause
    op.drop_column('deliveries', 'failure_cause')
    
    # Eliminar el tipo ENUM
    op.execute('DROP TYPE IF EXISTS deliveryfailurecause')

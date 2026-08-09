"""add financial snapshot columns to deliveries for immutable bonus locking

Revision ID: 20260614
Revises: 20260613
Create Date: 2026-07-29

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260614'
down_revision = '20260613'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar columna locked_bonus_amount: valor exacto congelado en el momento del cierre
    op.add_column(
        'deliveries',
        sa.Column(
            'locked_bonus_amount',
            sa.Numeric(10, 2),
            nullable=True,
            comment='Monto del bono congelado en el momento de finalizar la entrega. Inmutable.'
        )
    )

    # Agregar columna locked_bonus_type: tipo de bono aplicado (SUCCESS o FAILED_ATTEMPT)
    op.add_column(
        'deliveries',
        sa.Column(
            'locked_bonus_type',
            sa.String(50),
            nullable=True,
            comment='Tipo de bono congelado: SUCCESS (entrega completada) o FAILED_ATTEMPT (entrega fallida bonificable). Inmutable.'
        )
    )

    # Agregar columna bonus_snapshot_date: timestamp exacto del congelamiento
    op.add_column(
        'deliveries',
        sa.Column(
            'bonus_snapshot_date',
            sa.DateTime(),
            nullable=True,
            comment='Fecha y hora exacta en que se congeló el bono. Inmutable.'
        )
    ) 

    # Agregar columna bonus_config_warning_snapshot: alerta de configuración en el momento del snapshot
    op.add_column(
        'deliveries',
        sa.Column(
            'bonus_config_warning_snapshot',
            sa.Text(),
            nullable=True,
            comment='Mensaje de alerta sobre configuración faltante en el momento del snapshot. Para auditoría.'
        )
    )


def downgrade() -> None:
    # Eliminar columnas en orden inverso
    op.drop_column('deliveries', 'bonus_config_warning_snapshot')
    op.drop_column('deliveries', 'bonus_snapshot_date')
    op.drop_column('deliveries', 'locked_bonus_type')
    op.drop_column('deliveries', 'locked_bonus_amount')
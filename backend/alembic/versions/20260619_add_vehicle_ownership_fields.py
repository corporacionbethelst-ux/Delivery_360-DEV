"""add_vehicle_ownership_fields_to_riders

Revision ID: 20260619
Revises: 20260618
Create Date: 2026-06-19 10:00:00.000000

Agrega campos vehicle_ownership_type y assigned_vehicle_id a la tabla riders
para soportar la funcionalidad de vehículos de empresa asignados a repartidores.

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260619'
down_revision = '20260618'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear el ENUM type para vehicle_ownership_type si no existe
    vehicle_ownership_type = postgresql.ENUM('PROPIO', 'EMPRESA', name='vehicleownershiptype', create_type=True)
    vehicle_ownership_type.create(op.get_bind(), checkfirst=True)
    
    # Agregar columna vehicle_ownership_type con valor por defecto 'PROPIO'
    op.add_column('riders', 
        sa.Column('vehicle_ownership_type', vehicle_ownership_type, nullable=False, server_default='PROPIO')
    )
    
    # Agregar columna assigned_vehicle_id como foreign key a vehicles.id
    op.add_column('riders',
        sa.Column('assigned_vehicle_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    
    # Crear índice para assigned_vehicle_id
    op.create_index(
        op.f('ix_riders_assigned_vehicle_id'),
        'riders',
        ['assigned_vehicle_id'],
        unique=False
    )
    
    # Agregar foreign key constraint
    op.create_foreign_key(
        op.f('fk_riders_assigned_vehicle_id_vehicles'),
        'riders',
        'vehicles',
        ['assigned_vehicle_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Eliminar foreign key constraint
    op.drop_constraint(
        op.f('fk_riders_assigned_vehicle_id_vehicles'),
        'riders',
        type_='foreignkey'
    )
    
    # Eliminar índice
    op.drop_index(
        op.f('ix_riders_assigned_vehicle_id'),
        table_name='riders'
    )
    
    # Eliminar columna assigned_vehicle_id
    op.drop_column('riders', 'assigned_vehicle_id')
    
    # Eliminar columna vehicle_ownership_type
    op.drop_column('riders', 'vehicle_ownership_type')
    
    # Eliminar el ENUM type (solo si no hay otras columnas que lo usen)
    vehicle_ownership_type = postgresql.ENUM(name='vehicleownershiptype')
    vehicle_ownership_type.drop(op.get_bind(), checkfirst=True)

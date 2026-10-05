"""
Fase 8 - Mapas & Tracking: migración de esquemas.

Crea:
    - rider_live_locations      (historial GPS de alta frecuencia, índices B-tree)
    - delivery_route_snapshots  (resultados VRP con TTL)

Nota de diseño: PostGIS ya está habilitado en el proyecto (riders.last_location usa
Geometry POINT SRID 4326), por lo que además se crea un índice GiST funcional sobre
ST_MakePoint. El bloque es tolerante a fallos: si la extensión no existe en el
entorno, la migración continúa usando los índices B-tree como fallback.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260901'
down_revision: Union[str, None] = '20260818'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) Tabla de posiciones en vivo
    # ------------------------------------------------------------------
    op.create_table(
        "rider_live_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "rider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("riders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("accuracy_meters", sa.Float, nullable=True),
        sa.Column("speed_kmh", sa.Float, nullable=True),
        sa.Column("heading_degrees", sa.Float, nullable=True),
        sa.Column("recorded_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_rider_live_locations_rider_id", "rider_live_locations", ["rider_id"])
    op.create_index("idx_rider_live_locations_recorded_at", "rider_live_locations", ["recorded_at"])
    # Índice compuesto: "última posición por rider" (consulta más caliente del dashboard)
    op.execute(
        "CREATE INDEX idx_rider_locations_recent "
        "ON rider_live_locations (rider_id, recorded_at DESC)"
    )

    # ------------------------------------------------------------------
    # 2) Snapshots de rutas optimizadas (VRP)
    # ------------------------------------------------------------------
    op.create_table(
        "delivery_route_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "delivery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("deliveries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("optimized_sequence_json", sa.String, nullable=False),
        sa.Column("original_distance_km", sa.Float, nullable=False),
        sa.Column("optimized_distance_km", sa.Float, nullable=False),
        sa.Column("savings_percentage", sa.Float, nullable=False, server_default="0"),
        sa.Column("calculated_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime, nullable=True),
    )
    op.create_index("idx_route_snapshots_delivery", "delivery_route_snapshots", ["delivery_id"])
    op.create_index("idx_route_snapshots_expires", "delivery_route_snapshots", ["expires_at"])

    # ------------------------------------------------------------------
    # 3) PostGIS / índice espacial (tolerante a fallos)
    #    Se usa SAVEPOINT para que un fallo aquí no aborte toda la migración.
    # ------------------------------------------------------------------
    bind = op.get_bind()
    try:
        bind.execute(sa.text("SAVEPOINT fase8_postgis"))
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
        bind.execute(
            sa.text(
                "CREATE INDEX idx_rider_locations_gist ON rider_live_locations "
                "USING gist(ST_MakePoint(longitude, latitude))"
            )
        )
        bind.execute(sa.text("RELEASE SAVEPOINT fase8_postgis"))
    except Exception:
        # Fallback deliberado: sin PostGIS seguimos con bounding-box SQL + B-tree.
        try:
            bind.execute(sa.text("ROLLBACK TO SAVEPOINT fase8_postgis"))
        except Exception:
            pass
        print(
            "[FASE8 WARN] No se pudo crear el índice GiST (PostGIS ausente). "
            "Continuando con índices B-tree como fallback."
        )


def downgrade() -> None:
    op.drop_index("idx_route_snapshots_expires", table_name="delivery_route_snapshots")
    op.drop_index("idx_route_snapshots_delivery", table_name="delivery_route_snapshots")
    op.drop_table("delivery_route_snapshots")

    op.execute("DROP INDEX IF EXISTS idx_rider_locations_gist")
    op.execute("DROP INDEX IF EXISTS idx_rider_locations_recent")
    op.drop_index("idx_rider_live_locations_recorded_at", table_name="rider_live_locations")
    op.drop_index("idx_rider_live_locations_rider_id", table_name="rider_live_locations")
    op.drop_table("rider_live_locations")

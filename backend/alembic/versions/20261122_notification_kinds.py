"""Align the legacy notification vocabulary without rewriting existing rows."""

from alembic import op

revision = "20261122_notification_kinds"
down_revision = "20261121_zone_bonus_factors"
branch_labels = None
depends_on = None

KINDS = (
    "ENTREGA_COMPLETADA",
    "RETIRO_SOLICITADO",
    "RETIRO_APROBADO",
    "RETIRO_RECHAZADO",
    "SLA_WARNING",
    "PAGO_RECIBIDO",
)


def upgrade():
    # Values are constants. They become usable after this migration commits.
    for kind in KINDS:
        op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '" + kind + "'")


def downgrade():
    # PostgreSQL cannot remove enum labels without replacing their type and
    # potentially losing rows. Older application models already know these
    # labels, so keep the additive vocabulary on application rollback.
    pass

"""Complete mapped runtime tables and the existing AUDITOR role.

Revision ID: 20261113_runtime_schema
Revises: 20261030_delivery_cancel
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261113_runtime_schema"
down_revision = "20261030_delivery_cancel"
branch_labels = None
depends_on = None

EXPECTED_COLUMNS = {
    "productivity_metrics": {
        "id",
        "rider_id",
        "shift_id",
        "total_deliveries",
        "on_time_deliveries",
        "late_deliveries",
        "avg_delivery_time_minutes",
        "total_distance_km",
        "total_earnings",
        "customer_rating_avg",
        "customer_rating_count",
        "sla_compliance_rate",
        "period_start",
        "period_end",
        "created_at",
        "updated_at",
    },
    "sla_records": {
        "id",
        "rider_id",
        "delivery_id",
        "order_id",
        "promised_delivery_minutes",
        "actual_delivery_minutes",
        "sla_met",
        "delay_minutes",
        "promised_at",
        "completed_at",
        "created_at",
    },
    "webhook_events": {
        "id",
        "integration_id",
        "event_type",
        "payload",
        "headers",
        "success",
        "response_code",
        "response_body",
        "error_message",
        "triggered_at",
        "retry_count",
        "next_retry_at",
        "created_at",
    },
}


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table, columns in EXPECTED_COLUMNS.items():
        if table in existing and not columns <= {
            column["name"] for column in sa.inspect(bind).get_columns(table)
        }:
            raise RuntimeError(
                "Existing runtime table has an unexpected shape; review schema before upgrading"
            )
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'AUDITOR'")
    if "productivity_metrics" not in existing:
        op.create_table(
            "productivity_metrics",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "rider_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("riders.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "shift_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("shifts.id", ondelete="SET NULL"),
            ),
            *[
                sa.Column(name, sa.Integer)
                for name in (
                    "total_deliveries",
                    "on_time_deliveries",
                    "late_deliveries",
                    "customer_rating_count",
                )
            ],
            *[
                sa.Column(name, sa.Float)
                for name in (
                    "avg_delivery_time_minutes",
                    "total_distance_km",
                    "total_earnings",
                    "customer_rating_avg",
                    "sla_compliance_rate",
                )
            ],
            sa.Column("period_start", sa.DateTime, nullable=False),
            sa.Column("period_end", sa.DateTime, nullable=False),
            sa.Column("created_at", sa.DateTime),
            sa.Column("updated_at", sa.DateTime),
        )
        for column in ("id", "rider_id", "shift_id"):
            op.create_index(
                "ix_productivity_metrics_" + column, "productivity_metrics", [column]
            )
        op.create_index(
            "idx_productivity_metrics_rider_period",
            "productivity_metrics",
            ["rider_id", "period_start", "period_end"],
        )
    if "sla_records" not in existing:
        op.create_table(
            "sla_records",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "rider_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("riders.id", ondelete="SET NULL"),
            ),
            sa.Column(
                "delivery_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("deliveries.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "order_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("orders.id", ondelete="CASCADE"),
            ),
            sa.Column("promised_delivery_minutes", sa.Integer, nullable=False),
            sa.Column("actual_delivery_minutes", sa.Integer),
            sa.Column("sla_met", sa.Boolean),
            sa.Column("delay_minutes", sa.Integer),
            sa.Column("promised_at", sa.DateTime, nullable=False),
            sa.Column("completed_at", sa.DateTime),
            sa.Column("created_at", sa.DateTime),
        )
        for column in ("id", "rider_id", "delivery_id", "order_id"):
            op.create_index("ix_sla_records_" + column, "sla_records", [column])
        op.create_index(
            "idx_sla_records_rider_date", "sla_records", ["rider_id", "created_at"]
        )
        op.create_index("idx_sla_records_met", "sla_records", ["sla_met"])
    if "webhook_events" not in existing:
        event_type = postgresql.ENUM(
            "ORDER_CREATED",
            "ORDER_UPDATED",
            "DELIVERY_COMPLETED",
            "RIDER_ASSIGNED",
            "PAYMENT_RECEIVED",
            "ALERT_TRIGGERED",
            name="webhookeventtype",
            create_type=False,
        )
        event_type.create(bind, checkfirst=True)
        op.create_table(
            "webhook_events",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                primary_key=True,
            ),
            sa.Column(
                "integration_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("integrations.id"),
                nullable=False,
            ),
            sa.Column("event_type", event_type, nullable=False),
            sa.Column("payload", sa.JSON),
            sa.Column("headers", sa.JSON),
            sa.Column("success", sa.Boolean),
            sa.Column("response_code", sa.Integer),
            sa.Column("response_body", sa.Text),
            sa.Column("error_message", sa.Text),
            sa.Column("triggered_at", sa.DateTime),
            sa.Column("retry_count", sa.Integer),
            sa.Column("next_retry_at", sa.DateTime),
            sa.Column("created_at", sa.DateTime),
        )
        for column in ("id", "integration_id"):
            op.create_index("ix_webhook_events_" + column, "webhook_events", [column])
        op.create_index(
            "idx_webhook_events_integration_date",
            "webhook_events",
            ["integration_id", "triggered_at"],
        )
        op.create_index("idx_webhook_events_type", "webhook_events", ["event_type"])


def downgrade():
    # Never discard operational history automatically. AUDITOR is deliberately retained.
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in sorted(existing & EXPECTED_COLUMNS.keys()):
        op.execute(sa.text("LOCK TABLE " + table + " IN ACCESS EXCLUSIVE MODE"))
    for table in ("webhook_events", "sla_records", "productivity_metrics"):
        if (
            table in existing
            and bind.execute(
                sa.text("SELECT EXISTS (SELECT 1 FROM " + table + ")")
            ).scalar()
        ):
            raise RuntimeError(
                "Downgrade refused: preserve/export runtime history first"
            )
    for table in ("webhook_events", "sla_records", "productivity_metrics"):
        if table in existing:
            op.drop_table(table)
    # Keep enum labels/types so existing schemas and roles cannot lose their meaning.

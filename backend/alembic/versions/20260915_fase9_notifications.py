"""
Fase 9 - Notificaciones & Comunicación Omnicanal: migración de esquemas.

Crea:
    - notification_templates   (plantillas renderizables {{var}})
    - notification_logs        (bitácora omnicanal con reintentos + dedupe)
    - user_device_tokens       (tokens FCM/APNs con auto-disable tras 3 fallos)
    - notification_preferences (preferencias evento x canal por usuario)

Tipos ENUM PG nuevos, tolerantes a fallos (patrón savepoint de Fase 8):
    - notificationchannel      (PUSH, SMS, EMAIL, IN_APP)
    - notificationstatus_fase9 (PENDIENTE, ENVIADO, ENTREGADO, FALLIDO, LEIDO)

DECISIÓN SOBRE LA TABLA LEGACY `notifications`:
    La tabla `notifications` preexistente (NotificationType/NotificationPriority,
    usada por alertas operacionales en app/api/v1/alerts.py y alert_service.py)
    NO se renombra ni se migra: su esquema es incompatible con el modelo
    omnicanal de Fase 9 y rompería consumidores activos. En su lugar se crean
    4 tablas NUEVAS con prefijo consistente (notification_*). El inbox legacy
    sigue funcionando; el nuevo inbox lee de notification_logs.

Seed de plantillas dentro de la migración (op.bulk_insert, idempotente vía
ON NOT EXISTS no aplicable en bulk_insert → se usa INSERT ... ON CONFLICT DO
NOTHING raw para tolerar re-ejecuciones parciales).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260915_fase9'
down_revision: Union[str, None] = '20260901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_enum_tolerant(name: str, values: list) -> None:
    """CREATE TYPE ... IF NOT EXISTS vía savepoint (patrón PostGIS Fase 8)."""
    bind = op.get_bind()
    bind.execute(sa.text(f"SAVEPOINT sp_enum_{name}"))
    try:
        value_list = ", ".join(f"'{v}'" for v in values)
        bind.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({value_list})"))
        bind.execute(sa.text(f"RELEASE SAVEPOINT sp_enum_{name}"))
    except Exception:
        bind.execute(sa.text(f"ROLLBACK TO SAVEPOINT sp_enum_{name}"))


TEMPLATES_SEED = [
    # (code, channel, subject, body_template)
    ("payout_aprobado", "PUSH", None,
     "Tu retiro de ${{amount_cents}} fue APROBADO. Se procesará a tu cuenta ****{{bank_last4}}."),
    ("payout_rechazado", "PUSH", None,
     "Tu solicitud de retiro de ${{amount_cents}} fue RECHAZADA. Motivo: {{reason}}"),
    ("payout_fallido", "PUSH", None,
     "El pago de tu retiro de ${{amount_cents}} FALLÓ. Motivo: {{reason}}. Soporte te contactará."),
    ("nuevo_pedido_asignado", "PUSH", None,
     "Nuevo pedido asignado: entrega {{delivery_code}} de {{customer_name}}. Pago estimado: ${{payment_cents}}."),
    ("alerta_desviacion_ruta", "EMAIL", "Alerta de desviación de ruta - Delivery360",
     "El rider {{rider_name}} se desvió {{deviation_km}} km de la ruta planificada. "
     "Posición actual: ({{lat}}, {{lng}}). Última actualización: {{last_seen}}."),
    ("resumen_diario_manager", "EMAIL", "Resumen diario de operaciones - Delivery360",
     "Buen día {{manager_name}}. Resumen de ayer: {{total_deliveries}} entregas, "
     "{{completed_count}} completadas, {{failed_count}} falladas, "
     "{{on_time_pct}}% a tiempo."),
]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) Tipos ENUM tolerantes a fallos
    # ------------------------------------------------------------------
    _create_enum_tolerant("notificationchannel", ["PUSH", "SMS", "EMAIL", "IN_APP"])
    _create_enum_tolerant("notificationstatus_fase9",
                          ["PENDIENTE", "ENVIADO", "ENTREGADO", "FALLIDO", "LEIDO"])

    ch = postgresql.ENUM("PUSH", "SMS", "EMAIL", "IN_APP",
                         name="notificationchannel", create_type=False)
    st = postgresql.ENUM("PENDIENTE", "ENVIADO", "ENTREGADO", "FALLIDO", "LEIDO",
                         name="notificationstatus_fase9", create_type=False)

    # ------------------------------------------------------------------
    # 2) notification_templates
    # ------------------------------------------------------------------
    op.create_table(
        "notification_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("channel", ch, nullable=False),
        sa.Column("subject", sa.String(200), nullable=True),
        sa.Column("body_template", sa.Text, nullable=False),
        sa.Column("language", sa.String(5), nullable=False, server_default="es"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime, nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("code", name="uq_notiftemplates_code"),
    )
    op.create_index("idx_notiftemplates_code", "notification_templates", ["code"], unique=True)

    # ------------------------------------------------------------------
    # 3) notification_logs
    # ------------------------------------------------------------------
    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_code", sa.String(50), nullable=True),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("deliveries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payout_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("payouts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", ch, nullable=False),
        sa.Column("status", st, nullable=False, server_default="PENDIENTE"),
        sa.Column("payload_json", sa.Text, nullable=True),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime, nullable=True),
        sa.Column("dedupe_key", sa.String(120), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("read_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime, nullable=True),
        sa.Column("delivered_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("dedupe_key", name="uq_notiflogs_dedupe_key"),
    )
    # Campana O(log n): (user_id, created_at DESC)
    op.create_index("idx_notiflogs_user_created", "notification_logs",
                    ["user_id", sa.text("created_at DESC")])
    # Cola de reintentos: (status, next_retry_at)
    op.create_index("idx_notiflogs_status_retry", "notification_logs",
                    ["status", "next_retry_at"])
    op.create_index("idx_notiflogs_user_id", "notification_logs", ["user_id"])

    # ------------------------------------------------------------------
    # 4) user_device_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "user_device_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_token", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(10), nullable=False, server_default="web"),
        sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime, nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("device_token", name="uq_device_tokens_token"),
    )
    op.create_index("idx_device_tokens_user", "user_device_tokens", ["user_id"])

    # ------------------------------------------------------------------
    # 5) notification_preferences
    # ------------------------------------------------------------------
    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_code", sa.String(50), nullable=False),
        sa.Column("channel", ch, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime, nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "event_code", "channel",
                            name="uq_notifpref_user_event_channel"),
    )

    # ------------------------------------------------------------------
    # 6) Seed de plantillas (INSERT ... ON CONFLICT DO NOTHING → idempotente)
    # ------------------------------------------------------------------
    bind = op.get_bind()
    for code, channel, subject, body in TEMPLATES_SEED:
        bind.execute(
            sa.text(
                "INSERT INTO notification_templates (code, channel, subject, body_template, language) "
                "VALUES (:code, CAST(:channel AS notificationchannel), :subject, :body, 'es') "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "channel": channel, "subject": subject, "body": body},
        )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_index("idx_device_tokens_user", table_name="user_device_tokens")
    op.drop_table("user_device_tokens")
    op.drop_index("idx_notiflogs_user_id", table_name="notification_logs")
    op.drop_index("idx_notiflogs_status_retry", table_name="notification_logs")
    op.drop_index("idx_notiflogs_user_created", table_name="notification_logs")
    op.drop_table("notification_logs")
    op.drop_index("idx_notiftemplates_code", table_name="notification_templates")
    op.drop_table("notification_templates")
    op.execute("DROP TYPE IF EXISTS notificationstatus_fase9")
    op.execute("DROP TYPE IF EXISTS notificationchannel")

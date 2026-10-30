"""Add a truthful cancelled delivery outcome, without rewriting historical rows."""

from alembic import op
import sqlalchemy as sa

revision = "20261030_delivery_cancel"
down_revision = "20261029_fiscal_integrity"
branch_labels = None
depends_on = None

BEFORE = [
    "PENDIENTE",
    "INICIADA",
    "EN_PICKUP",
    "EN_ROUTE",
    "EN_DESTINO",
    "COMPLETADA",
    "FALLIDA",
]
AFTER = BEFORE + ["CANCELADA"]


def _target(bind):
    row = bind.execute(sa.text("""
        SELECT tn.nspname AS type_schema,t.typname,c.oid AS table_oid,t.oid AS type_oid,
               cn.nspname AS table_schema
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace cn ON cn.oid=c.relnamespace
        JOIN pg_type t ON t.oid=a.atttypid JOIN pg_namespace tn ON tn.oid=t.typnamespace
        WHERE c.oid=to_regclass('deliveries') AND a.attname='status'
          AND NOT a.attisdropped AND t.typtype='e'
    """)).mappings().one_or_none()
    if row is None or row["typname"] != "deliverystatus":
        raise RuntimeError("Expected the deliveries.status PostgreSQL enum")
    labels = list(
        bind.execute(
            sa.text(
                "SELECT enumlabel FROM pg_enum WHERE enumtypid=:oid ORDER BY enumsortorder"
            ),
            {"oid": row["type_oid"]},
        ).scalars()
    )
    q = bind.dialect.identifier_preparer.quote
    return (
        row,
        labels,
        q(row["type_schema"]) + "." + q(row["typname"]),
        q(row["table_schema"]) + "." + q("deliveries"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    _, labels, enum, _ = _target(bind)
    if labels not in (BEFORE, AFTER):
        raise RuntimeError("Unexpected delivery enum labels; review before migrating")
    if labels == BEFORE:
        op.execute(sa.text(f"ALTER TYPE {enum} ADD VALUE 'CANCELADA'"))
    # PostgreSQL requires this transaction to commit before writing the new value.


def downgrade() -> None:
    bind = op.get_bind()
    row, labels, enum, table = _target(bind)
    if labels == BEFORE:
        return
    if labels != AFTER:
        raise RuntimeError("Unexpected delivery enum labels; downgrade refused")
    op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    if bind.execute(
        sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE status::text='CANCELADA')")
    ).scalar():
        raise RuntimeError(
            "Cancelled deliveries exist; downgrade would lose their meaning"
        )
    users = list(
        bind.execute(
            sa.text(
                "SELECT attrelid,attname FROM pg_attribute WHERE atttypid=:oid AND NOT attisdropped AND attnum>0"
            ),
            {"oid": row["type_oid"]},
        )
    )
    if len(users) != 1 or users[0][0] != row["table_oid"] or users[0][1] != "status":
        raise RuntimeError("The delivery enum has other consumers; downgrade refused")
    default = bind.execute(
        sa.text(
            "SELECT pg_get_expr(adbin,adrelid) FROM pg_attrdef d JOIN pg_attribute a ON a.attrelid=d.adrelid AND a.attnum=d.adnum WHERE d.adrelid=:oid AND a.attname='status'"
        ),
        {"oid": row["table_oid"]},
    ).scalar()
    q = bind.dialect.identifier_preparer.quote
    old_name = "deliverystatus_before_cancel58"
    old = q(row["type_schema"]) + "." + q(old_name)
    if (
        bind.execute(sa.text("SELECT to_regtype(:name)"), {"name": old}).scalar()
        is not None
    ):
        raise RuntimeError("Temporary enum name already exists; downgrade refused")
    op.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN status DROP DEFAULT"))
    op.execute(sa.text(f"ALTER TYPE {enum} RENAME TO {q(old_name)}"))
    sa.Enum(*BEFORE, name="deliverystatus", schema=row["type_schema"]).create(
        bind, checkfirst=False
    )
    op.execute(
        sa.text(
            f"ALTER TABLE {table} ALTER COLUMN status TYPE {enum} USING status::text::{enum}"
        )
    )
    if default is not None:
        op.execute(
            sa.text(f"ALTER TABLE {table} ALTER COLUMN status SET DEFAULT {default}")
        )
    op.execute(sa.text(f"DROP TYPE {old} RESTRICT"))

"""Explicit future USD operations, preserving unverified historical amounts.

Revision ID: 20261114_explicit_usd
Revises: 20261114_bcv_currency
"""

from alembic import op
import sqlalchemy as sa

revision = "20261114_explicit_usd"
down_revision = "20261114_bcv_currency"
branch_labels = None
depends_on = None

UNITS = (
    ("orders", "currency_code"),
    ("financials", "currency_code"),
    ("payouts", "currency_code"),
    ("payout_status_history", "currency_code"),
    ("riders", "wallet_currency"),
)


def upgrade():
    for table, column in UNITS:
        # No database default and no UPDATE: pre-existing rows remain unknown.
        op.add_column(table, sa.Column(column, sa.String(3), nullable=True))
        op.create_check_constraint(
            "ck_" + table + "_declared_usd",
            table,
            f"{column} IS NULL OR {column} = 'USD'",
        )
    op.execute("""CREATE FUNCTION preserve_declared_currency() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF to_jsonb(OLD)->TG_ARGV[0] IS DISTINCT FROM to_jsonb(NEW)->TG_ARGV[0] THEN
            RAISE EXCEPTION 'A recorded monetary unit cannot be relabelled';
        END IF;
        RETURN NEW; END; $$""")
    for table, column in UNITS:
        op.execute(
            f"CREATE TRIGGER preserve_unit_{table} BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION preserve_declared_currency('{column}')"
        )


def downgrade():
    for table, _ in UNITS:
        op.execute("LOCK TABLE " + table + " IN ACCESS EXCLUSIVE MODE NOWAIT")
    for table, column in UNITS:
        if (
            op.get_bind()
            .execute(
                sa.text(
                    f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {column} IS NOT NULL)"
                )
            )
            .scalar()
        ):
            raise RuntimeError("Downgrade refused: preserve declared currency history")
    for table, column in reversed(UNITS):
        op.execute("DROP TRIGGER preserve_unit_" + table + " ON " + table)
        op.drop_constraint("ck_" + table + "_declared_usd", table, type_="check")
        op.drop_column(table, column)
    op.execute("DROP FUNCTION preserve_declared_currency()")

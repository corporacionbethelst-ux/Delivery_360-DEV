"""Freeze prospective bonus units without labelling historical deliveries."""

from alembic import op
import sqlalchemy as sa

revision = "20261117_bonus_currency"
down_revision = "20261115_cashbook_indexes"
branch_labels = None
depends_on = None

SNAPSHOT_FIELDS = (
    "locked_bonus_amount",
    "locked_bonus_currency",
    "locked_bonus_type",
    "bonus_snapshot_date",
    "bonus_config_warning_snapshot",
    "locked_bonus_base",
    "locked_bonus_zone_multiplier",
    "locked_bonus_tier_multiplier",
    "locked_bonus_tier_level",
)


def install_guards():
    op.create_check_constraint(
        "ck_deliveries_bonus_currency",
        "deliveries",
        "locked_bonus_currency IS NULL OR locked_bonus_currency = 'USD'",
    )
    old_frozen = " OR ".join("OLD." + c + " IS NOT NULL" for c in SNAPSHOT_FIELDS)
    new_present = " OR ".join("NEW." + c + " IS NOT NULL" for c in SNAPSHOT_FIELDS)
    unchanged = " AND ".join(
        "NEW." + c + " IS NOT DISTINCT FROM OLD." + c for c in SNAPSHOT_FIELDS
    )
    op.execute(
        f"""CREATE FUNCTION preserve_bonus_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            IF OLD.status::text IN ('COMPLETADA','FALLIDA','CANCELADA') OR {old_frozen} THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='P0105', MESSAGE='Frozen delivery bonus history cannot be deleted';
                END IF;
                IF NOT ({unchanged}) OR NEW.order_id IS DISTINCT FROM OLD.order_id
                    OR NEW.rider_id IS DISTINCT FROM OLD.rider_id OR NEW.status IS DISTINCT FROM OLD.status THEN
                    RAISE EXCEPTION USING ERRCODE='P0105', MESSAGE='Frozen delivery bonus identity, amount and currency cannot change';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        END IF;
        IF {new_present} THEN
            IF NEW.locked_bonus_currency IS DISTINCT FROM 'USD'
                OR NEW.locked_bonus_amount IS NULL
                OR NEW.locked_bonus_amount::text IN ('NaN','Infinity','-Infinity')
                OR NEW.locked_bonus_amount < 0 OR NEW.locked_bonus_amount > 99999999.99
                OR NEW.bonus_snapshot_date IS NULL
                OR NOT ((NEW.status::text = 'COMPLETADA' AND NEW.locked_bonus_type::text = 'SUCCESS')
                    OR (NEW.status::text = 'FALLIDA' AND NEW.locked_bonus_type::text = 'FAILED_ATTEMPT'))
                OR NEW.status IS NULL OR NEW.locked_bonus_type IS NULL THEN
                RAISE EXCEPTION USING ERRCODE='P0105', MESSAGE='A new bonus requires a complete terminal USD snapshot';
            END IF;
        END IF;
        RETURN NEW;
    END; $$"""
    )
    op.execute(
        """CREATE TRIGGER preserve_delivery_bonus BEFORE INSERT OR UPDATE OR DELETE ON deliveries
        FOR EACH ROW EXECUTE FUNCTION preserve_bonus_snapshot()"""
    )
    predicate = " OR ".join(c + " IS NOT NULL" for c in SNAPSHOT_FIELDS)
    op.execute(
        f"""CREATE FUNCTION preserve_bonus_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE frozen boolean;
    BEGIN
        EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.%I WHERE status::text IN (''COMPLETADA'',''FALLIDA'',''CANCELADA'') OR {predicate})', TG_TABLE_SCHEMA, TG_TABLE_NAME) INTO frozen;
        IF frozen THEN
            RAISE EXCEPTION USING ERRCODE='P0105', MESSAGE='Frozen delivery bonus history cannot be truncated';
        END IF;
        RETURN NULL;
    END; $$"""
    )
    op.execute(
        """CREATE TRIGGER preserve_delivery_bonus_truncate BEFORE TRUNCATE ON deliveries
        FOR EACH STATEMENT EXECUTE FUNCTION preserve_bonus_truncate()"""
    )


def upgrade():
    # No ORM/server default and no UPDATE: every pre-existing unit remains NULL.
    op.add_column(
        "deliveries", sa.Column("locked_bonus_currency", sa.String(3), nullable=True)
    )
    install_guards()


def downgrade():
    op.execute("LOCK TABLE deliveries IN ACCESS EXCLUSIVE MODE NOWAIT")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM deliveries WHERE locked_bonus_currency IS NOT NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Downgrade refused: preserve declared bonus units")
    op.execute("DROP TRIGGER preserve_delivery_bonus_truncate ON deliveries")
    op.execute("DROP TRIGGER preserve_delivery_bonus ON deliveries")
    op.execute("DROP FUNCTION preserve_bonus_truncate()")
    op.execute("DROP FUNCTION preserve_bonus_snapshot()")
    op.drop_constraint("ck_deliveries_bonus_currency", "deliveries", type_="check")
    op.drop_column("deliveries", "locked_bonus_currency")

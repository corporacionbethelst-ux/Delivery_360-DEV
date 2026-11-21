"""Explicit factors and immutable factor provenance; no historical backfill."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261121_zone_bonus_factors"
down_revision = "20261121_zone_tariffs"
branch_labels = None
depends_on = None


def install_factor_guard():
    op.execute(
        """CREATE FUNCTION preserve_bonus_factors() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE f jsonb; z numeric; t numeric;
    BEGIN
      IF TG_OP = 'DELETE' THEN
        IF OLD.locked_bonus_factors IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='Frozen bonus factors cannot be deleted'; END IF;
        RETURN OLD;
      END IF;
      IF TG_OP = 'UPDATE' THEN
        IF (OLD.status::text IN ('COMPLETADA','FALLIDA','CANCELADA') OR OLD.locked_bonus_amount IS NOT NULL OR OLD.locked_bonus_currency IS NOT NULL OR OLD.bonus_snapshot_date IS NOT NULL OR OLD.locked_bonus_type IS NOT NULL OR OLD.locked_bonus_base IS NOT NULL OR OLD.locked_bonus_zone_multiplier IS NOT NULL OR OLD.locked_bonus_tier_multiplier IS NOT NULL OR OLD.locked_bonus_tier_level IS NOT NULL OR OLD.bonus_config_warning_snapshot IS NOT NULL OR OLD.locked_bonus_factors IS NOT NULL)
          AND NEW.locked_bonus_factors::jsonb IS DISTINCT FROM OLD.locked_bonus_factors::jsonb THEN
          RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='Frozen bonus factors cannot change';
        END IF;
      END IF;
      IF NEW.locked_bonus_factors IS NOT NULL THEN
        f := NEW.locked_bonus_factors::jsonb;
        IF jsonb_typeof(f) IS DISTINCT FROM 'object' OR jsonb_typeof(f->'version') IS DISTINCT FROM 'number' OR f->>'version' IS DISTINCT FROM '1' OR f->>'unit' IS DISTINCT FROM 'dimensionless'
          OR (SELECT count(*) FROM jsonb_object_keys(f))<>7 OR NOT(f ?& ARRAY['version','unit','zone_id','zone_revision','zone_factor','tier_factor','basis'])
          OR jsonb_typeof(f->'zone_factor') IS DISTINCT FROM 'string' OR jsonb_typeof(f->'tier_factor') IS DISTINCT FROM 'string'
          OR length(split_part(f->>'zone_factor','.',2))>324 OR (f->>'zone_factor') !~ '^(0|[1-9][0-9]{0,7})(\.[0-9]+)?$' OR (f->>'tier_factor') NOT IN ('1','1.05','1.1','1.15')
          OR NEW.locked_bonus_currency IS DISTINCT FROM 'USD' OR NEW.locked_bonus_amount IS NULL OR NEW.bonus_snapshot_date IS NULL
          OR NOT ((NEW.status::text='COMPLETADA' AND NEW.locked_bonus_type::text='SUCCESS') OR (NEW.status::text='FALLIDA' AND NEW.locked_bonus_type::text='FAILED_ATTEMPT')) OR NEW.status IS NULL OR NEW.locked_bonus_type IS NULL THEN
          RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='A new factor snapshot requires a complete terminal USD bonus';
        END IF;
        z := (f->>'zone_factor')::numeric;
        IF z<0 OR z>99999999.99 THEN RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='Invalid frozen factor'; END IF;
        IF f->>'basis'='no_zone_default' THEN
          IF f->'zone_id' IS DISTINCT FROM 'null'::jsonb OR f->'zone_revision' IS DISTINCT FROM 'null'::jsonb OR f->>'zone_factor'<>'1' THEN RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='Contradictory default factor'; END IF;
        ELSIF f->>'basis' IN ('declared_exact','legacy_decimal_representation') THEN
          IF jsonb_typeof(f->'zone_id') IS DISTINCT FROM 'string' OR (f->>'zone_id') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='Invalid factor zone identity'; END IF;
          IF f->>'basis'='declared_exact' THEN
            IF jsonb_typeof(f->'zone_revision') IS DISTINCT FROM 'number' OR (f->>'zone_revision') !~ '^[1-9][0-9]{0,9}$' OR z<0.1 OR z>5 OR (position('.' in f->>'zone_factor')>0 AND right(f->>'zone_factor',1)='0') OR (f->>'zone_factor') !~ '^(0|[1-5])(\.[0-9]{1,18})?$' THEN RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='Invalid declared factor revision or precision'; END IF;
            IF (f->>'zone_revision')::numeric>2147483647 THEN RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='Invalid factor revision'; END IF;
          ELSIF f->'zone_revision' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='Legacy factor cannot claim a revision'; END IF;
        ELSE RAISE EXCEPTION USING ERRCODE='P0110',MESSAGE='Unknown factor basis'; END IF;
      END IF;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        "CREATE TRIGGER preserve_delivery_bonus_factors BEFORE INSERT OR UPDATE OR DELETE ON deliveries FOR EACH ROW EXECUTE FUNCTION preserve_bonus_factors()"
    )


def upgrade():
    op.add_column(
        "zones", sa.Column("bonus_factor_exact", sa.Numeric(20, 18), nullable=True)
    )
    op.add_column(
        "zones",
        sa.Column(
            "bonus_factor_revision", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "zones",
        sa.Column("bonus_factor_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "zones",
        sa.Column(
            "bonus_factor_updated_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_check_constraint(
        "ck_zones_exact_bonus_factor",
        "zones",
        "(bonus_factor_revision = 0 AND bonus_factor_exact IS NULL AND bonus_factor_updated_at IS NULL AND bonus_factor_updated_by IS NULL) OR (bonus_factor_revision > 0 AND bonus_factor_exact IS NOT NULL AND bonus_factor_exact BETWEEN 0.1 AND 5 AND bonus_factor_updated_at IS NOT NULL AND bonus_factor_updated_by IS NOT NULL)",
    )
    op.add_column(
        "deliveries", sa.Column("locked_bonus_factors", sa.JSON(), nullable=True)
    )
    install_factor_guard()


def downgrade():
    op.execute("LOCK TABLE zones,deliveries IN ACCESS EXCLUSIVE MODE NOWAIT")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM zones WHERE bonus_factor_revision>0) OR EXISTS(SELECT 1 FROM deliveries WHERE locked_bonus_factors IS NOT NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Downgrade refused: preserve explicit bonus factors")
    op.execute("DROP TRIGGER preserve_delivery_bonus_factors ON deliveries")
    op.execute("DROP FUNCTION preserve_bonus_factors()")
    op.drop_column("deliveries", "locked_bonus_factors")
    op.drop_constraint("ck_zones_exact_bonus_factor", "zones", type_="check")
    for column in (
        "bonus_factor_updated_by",
        "bonus_factor_updated_at",
        "bonus_factor_revision",
        "bonus_factor_exact",
    ):
        op.drop_column("zones", column)

"""Recorded delivery bonus components from one authorized, bounded SQL statement."""

from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, func
from app.core.operation_permissions import ensure_operation_role
from app.core.serialization import optional_enum_value
from app.models.delivery import Delivery
from app.models.order import Order
from app.models.rider import Rider
from app.models.user import UserRole
from app.services.bonus_settings_exact import finish
from app.services.customer_cashbook import utc
from app.services.payout_records_exact import currency
from app.services.transaction_records_exact import row_money


async def report(db, actor, requested):
    ensure_operation_role(actor)
    try:
        ids = [UUID(value) for value in requested.split(",")]
    except (ValueError, AttributeError):
        raise HTTPException(422, "Identidades de orden no válidas") from None
    if not 1 <= len(ids) <= 10 or len(ids) != len(set(ids)):
        raise HTTPException(422, "Consulta entre una y diez órdenes únicas")
    query = (
        select(
            Order.id.label("order_id"),
            Order.assigned_rider_id,
            Delivery,
            func.timezone("UTC", func.statement_timestamp()).label("at"),
        )
        .outerjoin(Delivery, Delivery.order_id == Order.id)
        .where(Order.id.in_(ids))
    )
    if actor.role == UserRole.REPARTIDOR:
        query = query.where(
            Order.assigned_rider_id.in_(
                select(Rider.id).where(Rider.user_id == actor.id)
            )
        )
    rows = (await db.execute(query.limit(101))).all()
    selected = {}
    for row in rows:
        if row.order_id in selected:
            raise HTTPException(
                409, "La orden tiene entregas contradictorias; requiere revisión"
            )
        delivery = row.Delivery
        if delivery and delivery.rider_id != row.assigned_rider_id:
            raise HTTPException(409, "Las identidades del bono requieren revisión")
        issues = []

        def amount(field):
            value = getattr(delivery, field) if delivery else None
            if value is None:
                return None
            result = row_money(value, field, issues)
            if result and result.startswith("-"):
                issues.append({"field": field, "reason": "IMPORTE_NO_VALIDO"})
                return None
            return result

        selected[row.order_id] = dict(
            order_id=str(row.order_id),
            delivery_id=str(delivery.id) if delivery else None,
            rider_id=str(delivery.rider_id) if delivery and delivery.rider_id else None,
            source="delivery_snapshot" if delivery else "order_without_delivery",
            status=optional_enum_value(delivery.status) if delivery else None,
            amount=amount("locked_bonus_amount"),
            base=amount("locked_bonus_base"),
            zone_multiplier=amount("locked_bonus_zone_multiplier"),
            tier_multiplier=amount("locked_bonus_tier_multiplier"),
            tier_level=delivery.locked_bonus_tier_level if delivery else None,
            bonus_type=(
                optional_enum_value(delivery.locked_bonus_type) if delivery else None
            ),
            snapshot_date=(
                utc(delivery.bonus_snapshot_date)
                if delivery and delivery.bonus_snapshot_date
                else None
            ),
            config_warning=delivery.bonus_config_warning_snapshot if delivery else None,
            **currency(
                {"currency_code": delivery.locked_bonus_currency if delivery else None}
            ),
            state_review=bool(
                delivery
                and any(
                    getattr(delivery, f) is not None
                    for f in (
                        "locked_bonus_amount",
                        "locked_bonus_currency",
                        "locked_bonus_type",
                        "bonus_snapshot_date",
                        "locked_bonus_base",
                        "locked_bonus_zone_multiplier",
                        "locked_bonus_tier_multiplier",
                        "locked_bonus_tier_level",
                    )
                )
                and (
                    delivery.locked_bonus_amount is None
                    or delivery.bonus_snapshot_date is None
                    or (
                        optional_enum_value(delivery.status),
                        optional_enum_value(delivery.locked_bonus_type),
                    )
                    not in (("COMPLETADA", "SUCCESS"), ("FALLIDA", "FAILED_ATTEMPT"))
                )
            ),
            money_review=issues,
        )
        if delivery and delivery.locked_bonus_factors is not None:
            from app.services.zone_bonus_factors import validate_factor_snapshot

            try:
                factor_snapshot = validate_factor_snapshot(
                    delivery.locked_bonus_factors
                )
                if (
                    delivery.locked_bonus_currency != "USD"
                    or delivery.locked_bonus_amount is None
                    or delivery.bonus_snapshot_date is None
                    or (
                        optional_enum_value(delivery.status),
                        optional_enum_value(delivery.locked_bonus_type),
                    )
                    not in (("COMPLETADA", "SUCCESS"), ("FALLIDA", "FAILED_ATTEMPT"))
                ):
                    raise ValueError("Estado del snapshot de factores inválido")
                from app.services.financial_service import money
                from decimal import Decimal

                for field, key in (
                    ("locked_bonus_zone_multiplier", "zone_factor"),
                    ("locked_bonus_tier_multiplier", "tier_factor"),
                ):
                    stored = getattr(delivery, field)
                    if stored is not None and stored != money(
                        Decimal(factor_snapshot[key])
                    ):
                        raise ValueError("Componentes de factores contradictorios")
            except (ValueError, TypeError, ArithmeticError):
                raise HTTPException(
                    409, "Los factores conservados requieren revisión"
                ) from None
            selected[row.order_id]["factor_snapshot"] = factor_snapshot
    if set(selected) != set(ids):
        raise HTTPException(
            403 if actor.role == UserRole.REPARTIDOR else 404,
            "No se pudo acceder a todas las órdenes solicitadas",
        )
    return finish(
        dict(
            version=1,
            scope="recorded_delivery_bonus_snapshots",
            snapshot_basis="single_statement_visibility",
            units_basis="stored_snapshot_only",
            actor={"user_id": str(actor.id), "role": actor.role.value},
            order_ids=[str(value) for value in ids],
            records=[selected[value] for value in ids],
            generated_at=utc(rows[0].at),
            bank_verified=False,
            available_balance_included=False,
            ledger_credit_included=False,
        )
    )

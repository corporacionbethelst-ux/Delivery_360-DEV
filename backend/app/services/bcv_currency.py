"""Exact, dated quotations. No demo FX, historical relabelling or bank calls."""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog, ActionType
from app.models.currency import BcvRate, UsdVesQuote
from app.models.user import User, UserRole

BCV_URL = "https://www.bcv.org.ve/"
READ_ROLES = {
    UserRole.SUPERADMIN,
    UserRole.GERENTE,
    UserRole.OPERADOR,
    UserRole.AUDITOR,
}
RATE_ROLES = {UserRole.SUPERADMIN, UserRole.GERENTE}
QUOTE_ROLES = RATE_ROLES | {UserRole.OPERADOR}


def utc_now():
    return datetime.now(timezone.utc)


def current_day() -> date:
    return utc_now().astimezone(ZoneInfo("America/Caracas")).date()


def converted_amount(amount: Decimal, rate: Decimal) -> Decimal:
    if (
        not amount.is_finite()
        or not rate.is_finite()
        or not 0 <= amount < Decimal("1000000000000")
        or not 0 < rate < Decimal("1000000000")
    ):
        raise ValueError("Importe o tasa fuera de rango")
    if int(amount.as_tuple().exponent) < -2 or int(rate.as_tuple().exponent) < -8:
        raise ValueError("Precisión no admitida")
    with localcontext() as context:
        context.prec = 40
        return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rate_view(row: BcvRate) -> dict:
    return {
        "id": str(row.id),
        "previous_rate_id": str(row.previous_rate_id) if row.previous_rate_id else None,
        "valid_on": row.valid_on.isoformat(),
        "reference_date": row.reference_date.isoformat(),
        "revision": row.revision,
        "ves_per_usd": format(row.ves_per_usd, ".8f"),
        "note": row.note,
        "recorded_at": row.recorded_at.isoformat() + "Z",
        "recorded_by": str(row.recorded_by),
        "source": "MANUAL_BCV",
        "source_url": BCV_URL,
        "automatically_verified": False,
    }


def quote_view(row: UsdVesQuote, rate: BcvRate) -> dict:
    return {
        "id": str(row.id),
        "amount_usd": format(row.amount_usd, ".2f"),
        "amount_ves": format(row.amount_ves, ".2f"),
        "reference": row.reference,
        "created_at": row.created_at.isoformat() + "Z",
        "created_by": str(row.created_by),
        "rate": rate_view(rate),
        "base_currency": "USD",
        "quote_currency": "VES",
        "country": "VE",
        "quotation_only": True,
        "payment_confirmed": False,
    }


async def receipt_view(db: AsyncSession, row: UsdVesQuote) -> dict:
    rate = await db.get(BcvRate, row.rate_id)
    if rate is None:
        raise HTTPException(409, "La referencia histórica requiere revisión")
    return quote_view(row, rate)


async def advisory(db: AsyncSession, key: str):
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"), {"key": key}
    )


async def actor_lock(
    db: AsyncSession, actor: User, roles: set[UserRole], *, expected_version=None
):
    identity, version = actor.id, (
        actor.token_version if expected_version is None else expected_version
    )
    live = await db.scalar(
        select(User)
        .where(User.id == identity)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if live is None or not live.is_active or live.token_version != version:
        raise HTTPException(401, "La sesión cambió; vuelve a identificarte")
    if live.role not in roles:
        raise HTTPException(403, "Acceso no permitido")


async def latest_for(db: AsyncSession, day: date) -> BcvRate | None:
    return await db.scalar(
        select(BcvRate)
        .where(BcvRate.valid_on == day)
        .order_by(BcvRate.revision.desc())
        .limit(1)
    )


async def context_view(db: AsyncSession) -> dict:
    day = current_day()
    current = await latest_for(db, day)
    history = list(
        (
            await db.scalars(
                select(BcvRate)
                .order_by(BcvRate.valid_on.desc(), BcvRate.revision.desc())
                .limit(20)
            )
        ).all()
    )
    return {
        "country": "VE",
        "base_currency": "USD",
        "quote_currency": "VES",
        "today": day.isoformat(),
        "scope": "quotation_only",
        "timezone": "America/Caracas",
        "current_rate": rate_view(current) if current else None,
        "rates": [rate_view(row) for row in history],
        "automatic_bcv_available": False,
        "historical_balances_relabelled": False,
    }


async def record_rate(db: AsyncSession, actor: User, body) -> dict:
    await actor_lock(db, actor, RATE_ROLES)
    await advisory(db, "bcv:request:" + str(body.request_key))
    prior = await db.scalar(
        select(BcvRate).where(BcvRate.request_key == body.request_key)
    )
    value = Decimal(body.ves_per_usd)
    if prior is not None:
        if (
            prior.recorded_by,
            prior.valid_on,
            prior.reference_date,
            prior.ves_per_usd,
            prior.note,
            prior.previous_rate_id,
        ) != (
            actor.id,
            body.valid_on,
            body.reference_date,
            value,
            body.note,
            body.previous_rate_id,
        ):
            raise HTTPException(409, "La clave identifica otro registro de tasa")
        return rate_view(prior)
    day = current_day()
    if body.valid_on != day or body.reference_date > day:
        raise HTTPException(409, "Registra la tasa para el día actual de Caracas")
    if body.reference_date < day and len(body.note.strip()) < 10:
        raise HTTPException(
            422, "Explica por qué la referencia anterior sigue vigente hoy"
        )
    await advisory(db, "bcv:day:" + day.isoformat())
    if current_day() != day:
        raise HTTPException(409, "Cambió el día de operación; recarga")
    previous = await latest_for(db, day)
    if (previous.id if previous else None) != body.previous_rate_id:
        raise HTTPException(412, "La tasa cambió; recarga antes de guardar")
    row = BcvRate(
        request_key=body.request_key,
        previous_rate_id=body.previous_rate_id,
        valid_on=day,
        reference_date=body.reference_date,
        revision=previous.revision + 1 if previous else 1,
        ves_per_usd=value,
        note=body.note,
        recorded_by=actor.id,
        recorded_at=utc_now().replace(tzinfo=None),
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            user_id=actor.id,
            user_email=actor.email,
            user_role=actor.role.value if actor.role else None,
            action_type=ActionType.CONFIG_CHANGE,
            resource_type="BCV_RATE",
            resource_id=str(row.id),
            description="Referencia BCV registrada manualmente",
            old_values={"rate_id": str(previous.id) if previous else None},
            new_values=rate_view(row),
            success=True,
        )
    )
    await db.commit()
    return rate_view(row)


async def create_quote(db: AsyncSession, actor: User, body) -> dict:
    await actor_lock(db, actor, QUOTE_ROLES)
    await advisory(db, "bcv:quote:" + str(body.request_key))
    prior = await db.scalar(
        select(UsdVesQuote).where(UsdVesQuote.request_key == body.request_key)
    )
    amount = Decimal(body.amount_usd)
    if prior is not None:
        if (prior.created_by, prior.rate_id, prior.amount_usd, prior.reference) != (
            actor.id,
            body.rate_id,
            amount,
            body.reference,
        ):
            raise HTTPException(409, "La clave identifica otra cotización")
        return await receipt_view(db, prior)
    day = current_day()
    await advisory(db, "bcv:day:" + day.isoformat())
    if current_day() != day:
        raise HTTPException(409, "Cambió el día de operación; recarga")
    rate = await latest_for(db, day)
    if rate is None:
        raise HTTPException(409, "Falta una referencia BCV registrada para hoy")
    if rate.id != body.rate_id:
        raise HTTPException(412, "La tasa cambió; recarga antes de cotizar")
    row = UsdVesQuote(
        request_key=body.request_key,
        rate_id=rate.id,
        amount_usd=amount,
        amount_ves=converted_amount(amount, rate.ves_per_usd),
        reference=body.reference,
        created_by=actor.id,
        created_at=utc_now().replace(tzinfo=None),
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            user_id=actor.id,
            user_email=actor.email,
            user_role=actor.role.value if actor.role else None,
            action_type=ActionType.CREATE,
            resource_type="USD_VES_QUOTE",
            resource_id=str(row.id),
            description="Cotización USD/VES conservada; no confirma pago",
            new_values={
                "rate_id": str(rate.id),
                "amount_usd": format(amount, ".2f"),
                "amount_ves": format(row.amount_ves, ".2f"),
            },
            success=True,
        )
    )
    await db.commit()
    return quote_view(row, rate)

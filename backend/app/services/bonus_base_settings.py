"""Read terminal bonus inputs from stored JSON without a binary float decoder."""

from decimal import Decimal
import json

from sqlalchemy import Text, cast, select

from app.core.exceptions import ValidationError
from app.models.platform_setting import PlatformSetting

BONUS_KEYS = frozenset(("rider_delivery_bonus", "rider_failed_attempt_bonus"))


async def load_bonus_bases(db, keys):
    """Hold shared row locks through the caller's terminal transaction.

    Settings writers take exclusive locks in key order. Missing rows and JSON
    null stay absent; each caller retains its own fallback and validation policy.
    This function never commits or writes settings and ignores cached ORM values.
    """
    keys = tuple(sorted(set(keys)))
    if not keys or not set(keys) <= BONUS_KEYS:
        raise ValueError("Unsupported bonus setting keys")
    rows = (
        await db.execute(
            select(
                PlatformSetting.key,
                cast(PlatformSetting.value, Text).label("raw_value"),
            )
            .where(PlatformSetting.key.in_(keys))
            .order_by(PlatformSetting.key)
            .with_for_update(read=True)
        )
    ).fetchall()
    values = {}
    for row in rows:
        try:
            values[row.key] = (
                None
                if row.raw_value is None
                else json.loads(
                    row.raw_value,
                    parse_float=Decimal,
                    parse_int=Decimal,
                    parse_constant=Decimal,
                )
            )
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise ValidationError("Configuración JSON de bono inválida") from exc
    return values

"""Split Payments / Reparto de Ingresos — Fase 10 (Hito 4).

Regla de negocio (alcance acordado, sin modelo Vendor):
- El split real es plataforma ↔ rider sobre la TARIFA DE ENVÍO (delivery_fee).
- restaurant_share_cents queda en 0 (columna reservada para futura Fase Vendor).
- Rider ya cobra su bono PAGO_ENTREGA en Fase 7; el snapshot documenta la
  distribución bruta neta del fee: platform = fee*PCT%, rider = residuo.
- Redondeo: centavos exactos con HALF_UP; el RESIDUO va a la plataforma
  (nunca se pierden centavos: platform + rider == fee_cents siempre).
- Idempotencia: UNIQUE(order_id) → re-ejecución no duplica snapshots.
- Atomicidad: todo dentro de UNA transacción AsyncSession; si algo falla,
  rollback completo y logger.exception, jamás rompe el flujo padre
  (se invoca post-commit vía create_task, patrón Fase 9).
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.delivery import Delivery
from app.models.fiscal import PaymentDistributionSnapshot
from app.models.order import Order
from app.models.platform_setting import PlatformSetting

logger = logging.getLogger("delivery360.split")


@dataclass
class RevenueShareRule:
    """División porcentual de la tarifa de envío."""
    platform_pct: Decimal          # 0-100
    rider_pct: Decimal             # 0-100 (=100 - platform_pct)
    source: str = "global"         # global | platform_setting | zone_override

    @classmethod
    def from_pct(cls, platform_pct: float, source: str = "global") -> "RevenueShareRule":
        p = Decimal(str(platform_pct)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if not (0 <= p <= 100):
            p = Decimal("20.00")
        return cls(platform_pct=p, rider_pct=Decimal("100") - p, source=source)

    def to_dict(self) -> dict:
        return {
            "platform_pct": float(self.platform_pct),
            "rider_pct": float(self.rider_pct),
            "source": self.source,
        }


async def resolve_share_rule(db: AsyncSession,
                             zone_id: Optional[uuid.UUID] = None) -> RevenueShareRule:
    """Override por clave platform_settings 'revenue_share_rule' > default config.

    Valor esperado JSON: {"platform_pct": 20} o número simple "20".
    Cualquier valor inválido → default settings.PLATFORM_COMMISSION_PCT.
    """
    try:
        res = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == "revenue_share_rule")
        )
        setting = res.scalar_one_or_none()
        if setting is not None and setting.value is not None:
            raw = str(setting.value).strip()
            pct: Optional[float] = None
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    pct = float(parsed.get("platform_pct", parsed.get("platform_percentage", "")))
                else:
                    pct = float(parsed)
            except (ValueError, TypeError):
                try:
                    pct = float(raw)
                except ValueError:
                    pct = None
            if pct is not None and 0 <= pct <= 100:
                return RevenueShareRule.from_pct(pct, source="platform_setting")
            logger.warning("revenue_share_rule inválida (%s); uso default", raw[:80])
    except Exception as exc:
        logger.warning("Fallo leyendo revenue_share_rule: %s", exc)
    return RevenueShareRule.from_pct(settings.PLATFORM_COMMISSION_PCT, source="global")


def compute_split(fee_cents: int, rule: RevenueShareRule) -> tuple[int, int]:
    """Centavos exactos: platform HALF_UP, rider = residuo. Suma == fee siempre."""
    fee = max(int(fee_cents), 0)
    platform = int((Decimal(fee) * rule.platform_pct / Decimal(100))
                   .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    platform = min(platform, fee)
    rider = fee - platform
    return platform, rider


async def process_order_settlement(db: AsyncSession, order_id: uuid.UUID,
                                   force: bool = False) -> Optional[PaymentDistributionSnapshot]:
    """Calcula y persiste el snapshot de distribución para una orden.

    Retorna None si no aplica (sin fee, orden inexistente o ya liquidado).
    Nunca lanza por fallos de datos: loggea y retorna None. Lanza solo errores
    de DB irrecuperables (el caller-safe los atrapa).
    """
    order = await db.get(Order, order_id)
    if order is None:
        logger.warning("split: orden %s inexistente", order_id)
        return None

    existing = await db.execute(
        select(PaymentDistributionSnapshot).where(
            PaymentDistributionSnapshot.order_id == order_id)
    )
    if existing.scalar_one_or_none() is not None and not force:
        logger.info("split: orden %s ya liquidada (idempotencia)", order_id)
        return None

    fee_cents = int(round(float(order.delivery_fee or 0) * 100))
    gross_cents = int(round(float(order.total or 0) * 100))
    if fee_cents <= 0:
        logger.info("split: orden %s sin fee de envío; nada que repartir", order_id)
        return None

    rule = await resolve_share_rule(db)
    platform_cents, rider_cents = compute_split(fee_cents, rule)

    snapshot = PaymentDistributionSnapshot(
        id=uuid.uuid4(),
        order_id=order_id,
        gross_amount_cents=gross_cents,
        platform_share_cents=platform_cents,
        restaurant_share_cents=0,  # reservado — no existe modelo Vendor aún
        rider_share_cents=rider_cents,
        applied_rule_json=json.dumps(rule.to_dict(), ensure_ascii=False),
        tax_allocation_json=None,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    logger.info("split orden %s: fee=%d¢ → plataforma=%d¢ rider=%d¢ (%s)",
                order_id, fee_cents, platform_cents, rider_cents, rule.source)
    return snapshot


async def settle_order_safe(order_id: uuid.UUID) -> None:
    """Wrapper fire-and-forget post-commit (así lo llaman los hooks).

    Uso: asyncio.create_task(settle_order_safe(delivery.order_id))
    Un fallo de reparto NUNCA revierte la entrega ni propagan excepciones.
    """
    if not settings.ENABLE_ELECTRONIC_INVOICING:
        # La liquidación de splits comparte flag maestro Fase 10
        logger.info("split: facturación/liquidación deshabilitada; skip %s", order_id)
        return
    try:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await process_order_settlement(db, order_id)
    except Exception:
        logger.exception("split orden %s falló (no bloqueante)", order_id)

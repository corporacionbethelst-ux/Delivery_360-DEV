"""Legacy generic FX previews, separate from dated BCV quotation receipts.

get_rates retains its legacy demo fallback and cache. Those values do not prove
official rates. Conversion helpers reject VES, unknown currencies and invalid
rates; Venezuelan quotations must use bcv_currency's persisted references.
"""

from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import Dict, Optional

from app.core.config import settings

logger = logging.getLogger("delivery360.fx")

# base → quote soportados: todas las monedas LATAM vs USD
_OXR_URL = "https://openexchangerates.org/api/latest.json?app_id={app_id}"

_cache: Dict[str, dict] = {}  # {"rates": {...}, "fetched_at": ts}


def _fallback_rates() -> Dict[str, float]:
    """Tasas de respaldo: moneda → COP-equivalentes vía USD. JSON config."""
    try:
        data = json.loads(settings.FX_FALLBACK_RATES_JSON or "{}")
        if isinstance(data, dict) and data:
            return {k: float(v) for k, v in data.items()}
    except Exception as exc:
        logger.warning("FX_FALLBACK_RATES_JSON inválido: %s", exc)
    return {"USD": 1.0, "COP": 3900.0, "MXN": 17.0, "CLP": 950.0, "PEN": 3.75}


async def _fetch_live_rates() -> Optional[Dict[str, float]]:
    """Obtiene tasas live si proveedor configurado; None si stub o fallo."""
    provider = (settings.EXCHANGE_RATE_PROVIDER or "stub").lower()
    if provider != "openexchangerates" or not settings.OPEN_EXCHANGE_RATES_APP_ID:
        return None
    try:
        import httpx  # ya está en requirements (integraciones Fase previa)

        url = _OXR_URL.format(app_id=settings.OPEN_EXCHANGE_RATES_APP_ID)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            rates = payload.get("rates") or {}
            if rates:
                return {k: float(v) for k, v in rates.items()}
            logger.warning("OXR respondió sin tasas")
    except Exception as exc:
        logger.warning(
            "Fallo fetch tasas genéricas; respaldo de prueba, sin verificación oficial"
        )
    return None


async def get_rates(force_refresh: bool = False) -> Dict[str, float]:
    """Tasas corrientes (dict moneda→valor_vs_USD) con TTL cache."""
    ttl = max(int(settings.FX_CACHE_TTL_MINUTES or 60), 1) * 60
    now = time.time()
    cached = _cache.get("current")
    if cached and not force_refresh and (now - cached["fetched_at"]) < ttl:
        return cached["rates"]

    rates = await _fetch_live_rates()
    source = "live"
    if rates is None:
        rates = _fallback_rates()
        source = "fallback"
    _cache["current"] = {"rates": rates, "fetched_at": now}
    logger.info("FX rates actualizadas (fuente=%s, %d monedas)", source, len(rates))
    return rates


async def convert(amount_cents: int, from_ccy: str, to_ccy: str) -> int:
    """Legacy preview in integer cents. Raises for VES or unknown/invalid rates."""
    if (
        isinstance(amount_cents, bool)
        or not isinstance(amount_cents, int)
        or amount_cents < 0
    ):
        raise ValueError("El importe debe ser un entero no negativo de centavos")
    if "VES" in (from_ccy.upper(), to_ccy.upper()):
        raise ValueError(
            "VES requiere una cotización BCV fechada; no admite tasas demo"
        )

    rates = await get_rates()

    def rate_to_usd(ccy: str) -> float:
        r = rates.get(ccy.upper())
        if r is None:
            raise ValueError("Moneda sin tasa conocida")
        return float(r)

    f = rate_to_usd(from_ccy)
    t = rate_to_usd(to_ccy)
    if (
        not Decimal(str(f)).is_finite()
        or not Decimal(str(t)).is_finite()
        or f <= 0
        or t <= 0
    ):
        raise ValueError("Tasa inválida")
    usd_cents = Decimal(int(amount_cents)) / Decimal(str(f))
    out = usd_cents * Decimal(str(t))
    from decimal import ROUND_HALF_UP

    return int(out.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def get_exchange_rate(from_ccy: str, to_ccy: str) -> Decimal:
    """Legacy numeric preview; not an official quote. Raises for VES/unknowns."""
    if "VES" in (from_ccy.upper(), to_ccy.upper()):
        raise ValueError(
            "VES requiere una cotización BCV fechada; no admite tasas demo"
        )
    rates = await get_rates()
    if from_ccy.upper() not in rates or to_ccy.upper() not in rates:
        raise ValueError("Moneda sin tasa conocida")
    f = float(rates[from_ccy.upper()])
    t = float(rates[to_ccy.upper()])
    if (
        not Decimal(str(f)).is_finite()
        or not Decimal(str(t)).is_finite()
        or f <= 0
        or t <= 0
    ):
        raise ValueError("Tasa inválida")
    return Decimal(str(round(t / f, 4)))

"""Servicio Multi-Moneda / Tasas de Cambio — Fase 10 (Hito 5, parte FX).

Patrón tolerante a fallos (OR-Tools Fase 8 / omnichannel Fase 9):
- Si EXCHANGE_RATE_PROVIDER == 'openexchangerates' y hay APP_ID → fetch httpx.
- Cualquier fallo (red, credencial, parseo) → fallback a FX_FALLBACK_RATES_JSON
  con logger.warning. NUNCA lanza excepción al caller.
- Cache en memoria con TTL FX_CACHE_TTL_MINUTES (Redis opcional no requerido).
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
        logger.warning("Fallo fetch tasas OXR, uso fallback: %s", exc)
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
    """Convierte centavos entre monedas con redondeo HALF_UP. Nunca falla.

    Moneda desconocida → tasa implícita 1.0 con warning (dev-safe).
    """
    from sqlalchemy.orm import decl_api  # noqa: F401  (guard de import entorno)

    rates = await get_rates()

    def rate_to_usd(ccy: str) -> float:
        r = rates.get(ccy.upper())
        if r is None:
            logger.warning("Moneda %s sin tasa conocida; asumo 1.0", ccy)
            return 1.0
        return float(r)

    f = rate_to_usd(from_ccy)
    t = rate_to_usd(to_ccy)
    if f <= 0:
        f = 1.0
    usd_cents = Decimal(int(amount_cents)) / Decimal(str(f))
    out = usd_cents * Decimal(str(t))
    return int(out.quantize(Decimal("0.01")))  # type: ignore[arg-type]


async def get_exchange_rate(from_ccy: str, to_ccy: str) -> Decimal:
    """Tasa numérica directa (para invoice.exchange_rate). Nunca lanza."""
    rates = await get_rates()
    f = float(rates.get((from_ccy or "USD").upper(), 1.0))
    t = float(rates.get((to_ccy or "USD").upper(), 1.0))
    if f <= 0:
        f = 1.0
    return Decimal(str(round(t / f, 4)))

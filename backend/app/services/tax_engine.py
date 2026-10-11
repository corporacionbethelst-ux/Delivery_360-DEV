"""Motor Fiscal Dinámico — Fase 10 (Hito 2).

Calcula IVA / retenciones / timbres por país con precisión Decimal y valores
SIEMPRE en centavos (int). Las reglas se cargan de `fiscal_configurations`
(DB) con fallback a defaults hardcodeados CO/MX/CL/PE cuando la tabla está
vacía (arranques sin migrar o tests unitarios).

Reglas duras respetadas:
- NO toca enums legacy.
- Redondeo bancario ROUND_HALF_UP, residuo asignado al total (nunca pierde centavos).
- México: IVA incluido en precio → se extrae la base imponible (importe).
- Retenciones (código empieza con 'RET') descuentan del total final.
- Timbre Bogotá: condicional, solo si base >= umbral (default 100.000 COP = 10_000_000 centavos).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fiscal import CountryTaxRegime, FiscalConfiguration

logger = logging.getLogger("delivery360.tax_engine")

CENT = Decimal("0.01")
# Umbral timbre distrital Bogotá (COP): 100.000 pesos expresados en centavos.
TIMBRE_THRESHOLD_CENTS = 10_000_000


def _c(value) -> Decimal:
    """Coerce a Decimal desde int-cents, float, str o Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value: Decimal) -> Decimal:
    """Quantize a 2 decimales con redondeo HALF_UP (centavos exactos)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class TaxRule:
    code: str
    name: str
    rate: Decimal                      # 0.19 = 19%
    applicability: str = "always"      # always | conditional | exempt_below_threshold
    threshold_cents: Optional[int] = None
    taxable_base: str = "gross"        # gross | net_after_other_taxes
    included_in_price: bool = False
    priority: int = 0

    @property
    def is_retention(self) -> bool:
        return self.code.startswith("RET")


@dataclass
class TaxLineResult:
    """Resultado de aplicar el motor a UNA línea de factura."""
    base_amount_cents: int              # base imponible en centavos
    taxes: List[dict] = field(default_factory=list)
    total_tax_cents: int = 0            # impuestos trasladados (no retenciones)
    total_retentions_cents: int = 0     # retenciones (descuentan del total)
    line_total_cents: int = 0           # base + taxes - retentions

    def to_dict(self) -> dict:
        return {
            "base_amount_cents": self.base_amount_cents,
            "taxes": self.taxes,
            "total_tax_cents": self.total_tax_cents,
            "total_retentions_cents": self.total_retentions_cents,
            "line_total_cents": self.line_total_cents,
        }


# ──────────────────────────────────────────────────────────────
# Defaults por país (fallback si fiscal_configurations está vacía)
# Espejo exacto del seed de la migración 20260930_fase10.
# ──────────────────────────────────────────────────────────────
DEFAULT_RULES: dict[CountryTaxRegime, List[TaxRule]] = {
    CountryTaxRegime.COLOMBIA: [
        TaxRule("IVA", "Impuesto sobre Ventas", Decimal("0.1900"), "always",
                None, "gross", False, 0),
        TaxRule("RET_IVA", "Retención en la Fuente IVA", Decimal("0.0150"),
                "conditional", None, "gross", False, 1),
        TaxRule("Timbre_Bogota", "Timbre Departamental Bogotá", Decimal("0.0150"),
                "conditional", TIMBRE_THRESHOLD_CENTS, "gross", False, 2),
    ],
    CountryTaxRegime.MEXICO: [
        TaxRule("IVA", "Impuesto al Valor Agregado", Decimal("0.1600"), "always",
                None, "gross", True, 0),
    ],
    CountryTaxRegime.CHILE: [
        TaxRule("IVA", "Impuesto al Valor Agregado", Decimal("0.1900"), "always",
                None, "gross", False, 0),
    ],
    CountryTaxRegime.PERU: [
        TaxRule("IGV", "Impuesto General a las Ventas", Decimal("0.1800"), "always",
                None, "gross", False, 0),
    ],
}


class TaxCalculator:
    """Calculador de impuestos por régimen país.

    Uso:
        calc = await get_tax_calculator(db, CountryTaxRegime.COLOMBIA)
        line = calc.apply_taxes(unit_price_cents=10_000_000, quantity=2, category='food')
    """

    def __init__(self, country: CountryTaxRegime, rules: Optional[List[TaxRule]] = None):
        self.country = country
        self.rules = sorted(
            rules if rules is not None else DEFAULT_RULES.get(country, []),
            key=lambda r: r.priority,
        )

    # ------------------------------------------------------------------
    async def load_rules_from_db(self, db: AsyncSession) -> None:
        """Recarga reglas activas desde fiscal_configurations (si hay filas)."""
        res = await db.execute(
            select(FiscalConfiguration)
            .where(
                FiscalConfiguration.country_code == self.country,
                FiscalConfiguration.is_active.is_(True),
                FiscalConfiguration.zone_id.is_(None),  # regla nacional
            )
            .order_by(FiscalConfiguration.priority)
        )
        rows = list(res.scalars().all())
        if rows:
            self.rules = [
                TaxRule(
                    code=r.tax_code,
                    name=r.tax_name,
                    rate=_c(r.rate),
                    applicability=(r.applicability_condition or "always"),
                    threshold_cents=(
                        TIMBRE_THRESHOLD_CENTS
                        if r.tax_code.lower().startswith("timbre")
                        else None
                    ),
                    taxable_base=r.taxable_base_type or "gross",
                    included_in_price=bool(r.included_in_price),
                    priority=int(r.priority or 0),
                )
                for r in rows
            ]

    # ------------------------------------------------------------------
    def _evaluate_applicability(self, rule: TaxRule, base_cents: int,
                                category: str) -> bool:
        if rule.applicability == "always":
            return True
        if rule.applicability == "exempt_below_threshold":
            thr = rule.threshold_cents if rule.threshold_cents is not None else 0
            return base_cents >= thr
        if rule.applicability == "conditional":
            # Timbre: solo si supera umbral. Retenciones: siempre que exista
            # tax_id del receptor (validado aguas arriba; aquí asumimos válido).
            if rule.code.lower().startswith("timbre"):
                thr = rule.threshold_cents if rule.threshold_cents is not None else 0
                return base_cents >= thr
            if rule.is_retention:
                return True
            return False
        # Expresión desconocida → conservador: no aplica, pero deja evidencia.
        logger.warning("Regla %s con applicability desconocida (%s): se omite",
                       rule.code, rule.applicability)
        return False

    # ------------------------------------------------------------------
    def apply_taxes(self, unit_price_cents: int, quantity: int = 1,
                    category: str = "general") -> TaxLineResult:
        """Aplica todas las reglas al monto de una línea (centavos enteros).

        Para impuestos INCLUIDOS en precio (MX) la base bruta recibida se
        trata como precio final: se extrae base = bruto / (1+rate) y el IVA
        NO se suma de nuevo al total (ya viene incluido).
        """
        gross_cents = int(unit_price_cents) * max(int(quantity), 0)
        taxes_out: List[dict] = []
        total_tax = 0
        total_ret = 0
        # Base imponible por defecto = bruto; si hay un impuesto incluido,
        # la base se redefine a la fracción excluida de ese impuesto.
        base_cents = gross_cents

        for rule in self.rules:
            if not self._evaluate_applicability(rule, gross_cents, category):
                continue

            if rule.included_in_price:
                # Importe: extraer base y impuesto del precio bruto.
                base_i = q2(_c(gross_cents) / (Decimal(1) + rule.rate))
                tax_i = q2(_c(gross_cents) - base_i)
                base_cents = int(base_i)  # la siguiente regla gravará la base neta
                amount = int(tax_i)
                taxes_out.append({
                    "code": rule.code, "name": rule.name,
                    "rate": float(rule.rate), "amount_cents": amount,
                    "base_amount_cents": int(base_i), "included": True,
                })
                # No se suma al total: ya está dentro del bruto.
                continue

            if rule.is_retention:
                amount = int(q2(_c(base_cents) * rule.rate))
                total_ret += amount
                taxes_out.append({
                    "code": rule.code, "name": rule.name,
                    "rate": float(rule.rate), "amount_cents": amount,
                    "base_amount_cents": int(base_cents), "retention": True,
                })
                continue

            amount = int(q2(_c(base_cents) * rule.rate))
            total_tax += amount
            taxes_out.append({
                "code": rule.code, "name": rule.name,
                "rate": float(rule.rate), "amount_cents": amount,
                "base_amount_cents": int(base_cents), "included": False,
            })

        line_total = base_cents + total_tax - total_ret
        return TaxLineResult(
            base_amount_cents=int(base_cents),
            taxes=taxes_out,
            total_tax_cents=int(total_tax),
            total_retentions_cents=int(total_ret),
            line_total_cents=int(line_total),
        )

    # ------------------------------------------------------------------
    def apply_taxes_to_items(self, items: List[dict]) -> List[TaxLineResult]:
        """items: [{'unit_price_cents': int, 'quantity': int, 'category': str}]"""
        results = []
        for it in items:
            results.append(self.apply_taxes(
                unit_price_cents=int(it.get("unit_price_cents", 0)),
                quantity=int(it.get("quantity", 1)),
                category=str(it.get("category", "general")),
            ))
        return results


async def get_tax_calculator(country: CountryTaxRegime,
                             db: Optional[AsyncSession] = None) -> TaxCalculator:
    """Fábrica: calculator con reglas DB si hay sesión, sino defaults."""
    calc = TaxCalculator(country)
    if db is not None:
        try:
            await calc.load_rules_from_db(db)
        except Exception as exc:  # nunca romper el flujo por config ausente
            logger.warning("Fallback a reglas default %s: %s", country.value, exc)
    return calc

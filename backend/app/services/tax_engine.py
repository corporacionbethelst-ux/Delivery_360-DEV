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
    rate: Decimal  # 0.19 = 19%
    applicability: str = "always"  # always | conditional | exempt_below_threshold
    threshold_cents: Optional[int] = None
    taxable_base: str = "gross"  # gross | net_after_other_taxes
    included_in_price: bool = False
    priority: int = 0

    @property
    def is_retention(self) -> bool:
        return self.code.startswith("RET")


@dataclass
class TaxLineResult:
    """Resultado de aplicar el motor a UNA línea de factura."""

    base_amount_cents: int  # base imponible en centavos
    taxes: List[dict] = field(default_factory=list)
    total_tax_cents: int = 0  # impuestos trasladados (no retenciones)
    total_retentions_cents: int = 0  # retenciones (descuentan del total)
    line_total_cents: int = 0  # bruto + impuestos externos - retenciones
    included_tax_cents: int = 0

    def to_dict(self) -> dict:
        return {
            "base_amount_cents": self.base_amount_cents,
            "taxes": self.taxes,
            "total_tax_cents": self.total_tax_cents,
            "total_retentions_cents": self.total_retentions_cents,
            "line_total_cents": self.line_total_cents,
            "included_tax_cents": self.included_tax_cents,
        }


# ──────────────────────────────────────────────────────────────
# Defaults por país (fallback si fiscal_configurations está vacía)
# Espejo exacto del seed de la migración 20260930_fase10.
# ──────────────────────────────────────────────────────────────
DEFAULT_RULES: dict[CountryTaxRegime, List[TaxRule]] = {
    CountryTaxRegime.COLOMBIA: [
        TaxRule(
            "IVA",
            "Impuesto sobre Ventas",
            Decimal("0.1900"),
            "always",
            None,
            "gross",
            False,
            0,
        ),
        TaxRule(
            "RET_IVA",
            "Retención en la Fuente IVA",
            Decimal("0.0150"),
            "conditional",
            None,
            "gross",
            False,
            1,
        ),
        TaxRule(
            "Timbre_Bogota",
            "Timbre Departamental Bogotá",
            Decimal("0.0150"),
            "conditional",
            TIMBRE_THRESHOLD_CENTS,
            "gross",
            False,
            2,
        ),
    ],
    CountryTaxRegime.MEXICO: [
        TaxRule(
            "IVA",
            "Impuesto al Valor Agregado",
            Decimal("0.1600"),
            "always",
            None,
            "gross",
            True,
            0,
        ),
    ],
    CountryTaxRegime.CHILE: [
        TaxRule(
            "IVA",
            "Impuesto al Valor Agregado",
            Decimal("0.1900"),
            "always",
            None,
            "gross",
            False,
            0,
        ),
    ],
    CountryTaxRegime.PERU: [
        TaxRule(
            "IGV",
            "Impuesto General a las Ventas",
            Decimal("0.1800"),
            "always",
            None,
            "gross",
            False,
            0,
        ),
    ],
}


class TaxCalculator:
    """Calculador de impuestos por régimen país.

    Uso:
        calc = await get_tax_calculator(db, CountryTaxRegime.COLOMBIA)
        line = calc.apply_taxes(unit_price_cents=10_000_000, quantity=2, category='food')
    """

    def __init__(
        self, country: CountryTaxRegime, rules: Optional[List[TaxRule]] = None
    ):
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
    def _evaluate_applicability(
        self, rule: TaxRule, base_cents: int, category: str
    ) -> bool:
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
        logger.warning(
            "Regla %s con applicability desconocida (%s): se omite",
            rule.code,
            rule.applicability,
        )
        return False

    # ------------------------------------------------------------------
    def apply_taxes(
        self, unit_price_cents: int, quantity: int = 1, category: str = "general"
    ) -> TaxLineResult:
        """Aplica todas las reglas al monto de una línea (centavos enteros).

        Para impuestos INCLUIDOS en precio (MX) la base bruta recibida se
        trata como precio final: se extrae base = bruto / (1+rate) y el IVA
        NO se suma de nuevo al total (ya viene incluido).
        """
        from app.services.fiscal_integrity import checked_cents

        checked_cents(unit_price_cents)
        if type(quantity) is not int or not 1 <= quantity <= 1000:
            raise ValueError("Cantidad de línea inválida")
        gross_cents = checked_cents(unit_price_cents * quantity)
        applicable = []
        for rule in self.rules:
            if not self._evaluate_applicability(rule, gross_cents, category):
                continue
            rate = _c(rule.rate)
            if not rate.is_finite() or not 0 <= rate <= 1:
                raise ValueError("Tasa fiscal inválida")
            if rule.included_in_price and rule.is_retention:
                raise ValueError("Una retención no puede ser un impuesto incluido")
            applicable.append((rule, rate))
        included = [(rule, rate) for rule, rate in applicable if rule.included_in_price]
        combined_rate = sum((rate for _, rate in included), Decimal(0))

        def cents(value: Decimal) -> int:
            return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

        base_cents = (
            cents(_c(gross_cents) / (1 + combined_rate)) if included else gross_cents
        )
        included_total = gross_cents - base_cents
        included_left = included_total
        included_count = 0
        taxes_out: List[dict] = []
        total_tax = total_ret = 0
        for rule, rate in applicable:
            entry = {
                "code": rule.code,
                "name": rule.name,
                "rate": float(rate),
                "base_amount_cents": base_cents,
            }
            if rule.included_in_price:
                included_count += 1
                share = (
                    cents(_c(included_total) * rate / combined_rate)
                    if combined_rate
                    else 0
                )
                amount = (
                    included_left
                    if included_count == len(included)
                    else min(included_left, share)
                )
                included_left -= amount
                entry.update(amount_cents=amount, included=True)
            else:
                amount = cents(_c(base_cents) * rate)
                entry["amount_cents"] = amount
                if rule.is_retention:
                    total_ret += amount
                    entry["retention"] = True
                else:
                    total_tax += amount
            taxes_out.append(entry)
        line_total = gross_cents + total_tax - total_ret
        if abs(line_total) > (1 << 63) - 1:
            raise ValueError("Total fiscal fuera de rango")
        return TaxLineResult(
            base_amount_cents=base_cents,
            taxes=taxes_out,
            total_tax_cents=total_tax,
            total_retentions_cents=total_ret,
            line_total_cents=line_total,
            included_tax_cents=included_total,
        )

    # ------------------------------------------------------------------
    def apply_taxes_to_items(self, items: List[dict]) -> List[TaxLineResult]:
        """items: [{'unit_price_cents': int, 'quantity': int, 'category': str}]"""
        results = []
        for it in items:
            results.append(
                self.apply_taxes(
                    unit_price_cents=it.get("unit_price_cents", 0),
                    quantity=it.get("quantity", 1),
                    category=str(it.get("category", "general")),
                )
            )
        return results


async def get_tax_calculator(
    country: CountryTaxRegime, db: Optional[AsyncSession] = None
) -> TaxCalculator:
    """Fábrica: calculator con reglas DB si hay sesión, sino defaults."""
    calc = TaxCalculator(country)
    if db is not None:
        try:
            await calc.load_rules_from_db(db)
        except Exception as exc:  # nunca romper el flujo por config ausente
            logger.warning("Fallback a reglas default %s: %s", country.value, exc)
    return calc

"""Tests unitarios Fase 10 — Motor fiscal, split payments y reconciliación.

Sin DB: cubren la lógica pura (centavos exactos, redondeo, reglas, parser CSV).
Correr: pytest tests/test_fase10_fiscal.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from decimal import Decimal

from app.services.tax_engine import TaxCalculator, TIMBRE_THRESHOLD_CENTS
from app.models.fiscal import CountryTaxRegime
from app.services.split_payment_service import RevenueShareRule, compute_split
from app.services.bank_reconciliation_service import parse_statement_csv


# ──────────────────────────────────────────────────────────────
# TAX ENGINE — Colombia
# ──────────────────────────────────────────────────────────────
class TestColombiaTaxes:
    def setup_method(self):
        self.calc = TaxCalculator(CountryTaxRegime.COLOMBIA)

    def test_iva_below_timbre_threshold(self):
        """50.000 COP × 2 = 100.000¢ base... bajo umbral timbre? No:
        50.000 pesos = 5_000_000 centavos; x2 = 10_000_000 → EXACTO al umbral."""
        r = self.calc.apply_taxes(unit_price_cents=5_000_000, quantity=1)  # 50k COP
        assert r.base_amount_cents == 5_000_000
        # IVA 19% = 950.000¢ ; RET_IVA 1.5% = 75.000¢ ; timbre NO aplica (<umbral)
        assert r.total_tax_cents == 950_000
        assert r.total_retentions_cents == 75_000
        assert r.line_total_cents == 5_000_000 + 950_000 - 75_000

    def test_iva_and_retention_on_200k(self):
        """Espec del plan: 100.000 COP × 2 → IVA 38.000 pesos = 3.800.000¢."""
        r = self.calc.apply_taxes(unit_price_cents=10_000_000, quantity=2)
        iva = next(t for t in r.taxes if t["code"] == "IVA")
        assert iva["amount_cents"] == 3_800_000  # 19% de 200k pesos (espec)
        # Timbre aplica (base 20M >= umbral 10M): 1.5% de 20M = 300.000¢
        codes = {t["code"] for t in r.taxes}
        assert "Timbre_Bogota" in codes
        timbre = next(t for t in r.taxes if t["code"] == "Timbre_Bogota")
        assert timbre["amount_cents"] == 300_000
        assert r.total_tax_cents == 3_800_000 + 300_000  # IVA + timbre gravados
        assert r.total_retentions_cents == 300_000       # RET_IVA 1.5% de 20M

    def test_no_cent_loss_exact_integers(self):
        """Impares feos: nunca se pierden ni duplican centavos."""
        r = self.calc.apply_taxes(unit_price_cents=999_999, quantity=7)
        base = 999_999 * 7
        assert isinstance(r.base_amount_cents, int)
        assert isinstance(r.line_total_cents, int)
        recomputed = (r.base_amount_cents + r.total_tax_cents
                      - r.total_retentions_cents)
        assert recomputed == r.line_total_cents


# ──────────────────────────────────────────────────────────────
# TAX ENGINE — México (IVA incluido en precio)
# ──────────────────────────────────────────────────────────────
class TestMexicoTaxes:
    def setup_method(self):
        self.calc = TaxCalculator(CountryTaxRegime.MEXICO)

    def test_inclusive_iva_extraction(self):
        """1160.00 MXN con IVA 16% incluido → base 1000.00, IVA retenido en desglose."""
        r = self.calc.apply_taxes(unit_price_cents=116_000, quantity=1)
        assert abs(r.base_amount_cents - 100_000) <= 1
        iva = next(t for t in r.taxes if t["code"] == "IVA")
        assert abs(iva["amount_cents"] - 16_000) <= 1
        # Diseño documentado: impuestos INCLUIDOS se desglosan pero NO se
        # suman a total_tax_cents (ya van dentro del precio); el total pagado
        # al cliente sigue siendo bruto = base + impuesto incluido.
        assert r.total_tax_cents == 0
        assert r.base_amount_cents + iva["amount_cents"] == 116_000


# ──────────────────────────────────────────────────────────────
# SPLIT PAYMENTS
# ──────────────────────────────────────────────────────────────
class TestSplitPayments:
    def test_standard_20_percent(self):
        rule = RevenueShareRule.from_pct(20.0)
        platform, rider = compute_split(10_000, rule)  # 100.00 COP fee
        assert platform == 2_000
        assert rider == 8_000
        assert platform + rider == 10_000

    def test_odd_cents_residual_to_platform(self):
        """Fee impar: residuo nunca se pierde, suma exacta garantizada."""
        rule = RevenueShareRule.from_pct(20.0)
        for fee in (1, 3, 999, 10_001, 12_345):
            p, r = compute_split(fee, rule)
            assert p + r == fee
            assert 0 <= p <= fee

    def test_invalid_pct_falls_back(self):
        rule = RevenueShareRule.from_pct(150.0)  # inválido → default 20
        assert rule.platform_pct == Decimal("20.00")

    def test_rule_sums_100(self):
        rule = RevenueShareRule.from_pct(33.33)
        assert rule.platform_pct + rule.rider_pct == Decimal("100")


# ──────────────────────────────────────────────────────────────
# RECONCILIACIÓN — parser CSV
# ──────────────────────────────────────────────────────────────
class TestStatementParser:
    def test_us_format(self):
        csv_text = "date,reference,amount\n2026-10-01,TRX-001,1500.50\n2026-10-02,TRX-002,-200.00\n"
        lines = parse_statement_csv(csv_text)
        assert len(lines) == 2
        assert lines[0].amount_cents == 150_050
        assert lines[1].amount_cents == -20_000
        assert lines[0].bank_reference == "TRX-001"

    def test_latino_format_quoted(self):
        """Formato real LATAM: monto '1.234,56' entre comillas CSV."""
        csv_text = 'fecha,concepto,monto\n01/10/2026,PAGO D360,"1.234,56"\n'
        lines = parse_statement_csv(csv_text)
        assert len(lines) == 1
        assert lines[0].amount_cents == 123_456

    def test_latino_format_unquoted_single_sep(self):
        """Sin comillas pero solo coma decimal: 1234,56."""
        csv_text = "fecha,concepto,monto\n01/10/2026,PAGO D360,1234,56\n".replace(
            "PAGO D360,1234,56", "PAGO D360;1234,56").replace(";", ",") if False else \
            "fecha,monto\n01/10/2026,1234,56\n"
        lines = parse_statement_csv(csv_text)
        assert len(lines) == 1
        assert lines[0].amount_cents == 123_456

    def test_garbage_rows_skipped(self):
        csv_text = "date,amount\nnot-a-date,abc\n2026-10-01,10.00\n"
        lines = parse_statement_csv(csv_text)
        assert len(lines) == 1

    def test_empty_or_headerless(self):
        assert parse_statement_csv("") == []
        assert parse_statement_csv("foo,bar\n1,2\n") == []

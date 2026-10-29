"""Offline arithmetic, preview serialization and fail-closed signing contracts."""

import json
from decimal import Decimal
from xml.etree import ElementTree as ET
import pytest
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, ec, padding
from app.core.config import settings
from app.models.fiscal import CountryTaxRegime
from app.services.fiscal_integrity import (
    money_to_cents,
    decimal_amount,
    sandbox_allowed,
    MAX_CENTS,
)
from app.services.invoicing_engine import (
    sign_document,
    InvoiceSubmissionError,
    DianColombiaAdapter,
    SatMexicoAdapter,
    InvoicingEngine,
)
from app.services.tax_engine import TaxCalculator, TaxRule


@pytest.mark.parametrize("gross", [0, 1, 2, 3, 99, 101, 9999, 116001, 99999999])
def test_mexican_included_iva_preserves_every_input_cent(gross):
    result = TaxCalculator(CountryTaxRegime.MEXICO).apply_taxes(gross)
    assert result.base_amount_cents + result.included_tax_cents == gross
    assert result.line_total_cents == gross and result.total_tax_cents == 0
    assert (
        sum(t["amount_cents"] for t in result.taxes if t.get("included"))
        == result.included_tax_cents
    )


@pytest.mark.parametrize("gross", [1, 2, 3, 99, 9999])
def test_multiple_included_rules_allocate_exactly_without_negative_residual(gross):
    rules = [
        TaxRule(str(i), str(i), Decimal("0.5"), included_in_price=True)
        for i in range(5)
    ]
    result = TaxCalculator(CountryTaxRegime.MEXICO, rules=rules).apply_taxes(gross)
    assert result.line_total_cents == gross
    assert (
        result.base_amount_cents + sum(t["amount_cents"] for t in result.taxes) == gross
    )
    assert all(t["amount_cents"] >= 0 for t in result.taxes)


def test_external_tax_and_retention_round_to_whole_minor_units():
    rules = [
        TaxRule("VAT", "VAT", Decimal("0.19")),
        TaxRule("RET_X", "Retention", Decimal("0.015")),
    ]
    result = TaxCalculator(CountryTaxRegime.COLOMBIA, rules=rules).apply_taxes(999999)
    assert result.total_tax_cents == 190000 and result.total_retentions_cents == 15000
    assert result.line_total_cents == 1174999


@pytest.mark.parametrize(
    "rate", [Decimal("-0.1"), Decimal("1.01"), Decimal("NaN"), Decimal("Infinity")]
)
def test_invalid_tax_rates_do_not_produce_totals(rate):
    with pytest.raises(ValueError):
        TaxCalculator(
            CountryTaxRegime.MEXICO, rules=[TaxRule("IVA", "IVA", rate)]
        ).apply_taxes(100)


@pytest.mark.parametrize("value", [True, False, -1, 1.1, "1", None, MAX_CENTS + 1])
def test_minor_units_are_strict_integers(value):
    with pytest.raises(ValueError):
        TaxCalculator(CountryTaxRegime.COLOMBIA).apply_taxes(value)


@pytest.mark.parametrize("value", [0, True, 1.1, "2", 1001])
def test_quantity_cannot_be_silently_coerced(value):
    with pytest.raises(ValueError):
        TaxCalculator(CountryTaxRegime.COLOMBIA).apply_taxes(100, value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("1.005"), 101),
        ("0.015", 2),
        ("90071992547409.91", 9007199254740991),
        (None, 0),
    ],
)
def test_order_money_conversion_avoids_float_and_bankers_rounding(value, expected):
    assert money_to_cents(value) == expected


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1e100", "bad"])
def test_invalid_money_is_rejected(value):
    with pytest.raises(ValueError):
        money_to_cents(value)


@pytest.mark.parametrize("env", ["production", "prod", "unknown", "", "Production "])
def test_sandbox_opt_in_never_overrides_production_or_unknown_environment(
    monkeypatch, env
):
    monkeypatch.setattr(settings, "FISCAL_SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ENVIRONMENT", env)
    assert not sandbox_allowed()


@pytest.fixture(scope="session")
def rsa_key(tmp_path_factory):
    path = tmp_path_factory.mktemp("fiscal-signing") / "test-only-private.pem"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path, key


def test_configured_rsa_signature_verifies_against_exact_content(rsa_key):
    path, key = rsa_key
    signature = sign_document("Factura & <contenido>", str(path))
    key.public_key().verify(
        signature, "Factura & <contenido>".encode(), padding.PKCS1v15(), hashes.SHA256()
    )


@pytest.mark.parametrize("kind", ["missing", "invalid", "ec", "weak"])
def test_signing_failure_never_falls_back_or_exposes_key_path(tmp_path, kind, capsys):
    path = tmp_path / "private-key-sensitive.pem"
    if kind == "invalid":
        path.write_text("invalid private material")
    elif kind == "ec":
        key = ec.generate_private_key(ec.SECP256R1())
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    elif kind == "weak":
        key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    with pytest.raises(InvoiceSubmissionError) as e:
        sign_document("document", str(path))
    assert str(path) not in str(e.value) and "invalid private material" not in str(
        e.value
    )
    assert "sensitive" not in capsys.readouterr().out


def test_unconfigured_or_unavailable_crypto_does_not_simulate(monkeypatch, rsa_key):
    from app.services import invoicing_engine as engine

    with pytest.raises(InvoiceSubmissionError):
        sign_document("document")
    monkeypatch.setattr(engine, "_HAVE_CRYPTO", False)
    with pytest.raises(InvoiceSubmissionError):
        sign_document("document", str(rsa_key[0]))


@pytest.fixture
def document_data():
    return {
        "resolution_number": 100,
        "sequence": 100,
        "issue_date": "2026-10-29",
        "issue_time": "01:00:00",
        "currency": "MXN",
        "subtotal_cents": 100001,
        "grand_total_cents": 116001,
        "tax_total_cents": 16000,
        "customer": {"name": "A < B & C", "tax_id": "X&1"},
        "items": [
            {"name": "Entrega <rápida>", "quantity": 3, "base_amount_cents": 100001}
        ],
    }


@pytest.mark.asyncio
async def test_colombia_xml_supports_attributes_and_escapes_values(document_data):
    document = await DianColombiaAdapter().generate_document(document_data)
    root = ET.fromstring(document)
    ids = root.findall(".//{*}ID")
    assert any(node.attrib.get("schemeID") == "9" for node in ids)
    assert any(node.text == "X&1" for node in ids)
    assert "A &lt; B &amp; C" in document


@pytest.mark.asyncio
async def test_mexican_preview_keeps_exact_amount_strings_and_quantity(document_data):
    data = json.loads(await SatMexicoAdapter().generate_document(document_data))
    assert data["Total"] == "1160.01" and data["SubTotal"] == "1000.01"
    assert (
        data["Moneda"] == "MXN"
        and data["Conceptos"][0]["ValorUnitario"] == "333.336667"
    )
    assert data["Conceptos"][0]["Importe"] == "1000.01"
    assert decimal_amount(9007199254740991) == "90071992547409.91"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [DianColombiaAdapter, SatMexicoAdapter])
async def test_default_adapters_never_fabricate_authority_acceptance(adapter):
    provider = adapter()
    assert not provider.supports_real_submission()
    with pytest.raises(InvoiceSubmissionError):
        await provider.submit_to_authority("document", b"signature")


@pytest.mark.parametrize("country", [CountryTaxRegime.CHILE, CountryTaxRegime.PERU])
def test_country_without_adapter_never_falls_back_to_colombia(country):
    with pytest.raises(InvoiceSubmissionError):
        InvoicingEngine(None).provider_for(country)

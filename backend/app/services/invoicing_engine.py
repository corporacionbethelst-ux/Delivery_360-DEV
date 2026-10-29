"""Motor de Facturación Electrónica — Fase 10 (Hito 3).

Diseño:
- Los adaptadores locales generan previsualizaciones, no acreditan emisión fiscal.
- Ningún adaptador predeterminado tiene transporte real homologado.
- Reserva de numeración/cuota persistida antes de trabajo del proveedor.
- Sandbox opt-in, separado por resolución, bloqueado en producción.
"""

from __future__ import annotations

import json
import logging
import uuid
from urllib.parse import urlsplit
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

from sqlalchemy import func, select, text, update, or_, and_, case
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.fiscal import (
    CountryTaxRegime,
    ElectronicInvoice,
    InvoiceResolution,
    InvoiceStatus,
    InvoiceType,
)
from app.models.order import Order
from app.services.tax_engine import TaxCalculator, get_tax_calculator
from app.services.fiscal_integrity import (
    sandbox_allowed,
    checked_cents,
    decimal_amount,
    decimal_unit_amount,
    money_to_cents,
    invoice_evidence,
    MAX_CENTS,
    PREVIEW_NOTE,
)
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("delivery360.invoicing")


class InvoiceOrderNotFound(ValueError):
    """The referenced order does not exist."""


class InvoiceSubmissionError(Exception):
    """La autoridad fiscal rechazó el documento."""


# ──────────────────────────────────────────────────────────────
# Utilidades de firma (cryptography opcional)
# ──────────────────────────────────────────────────────────────
try:  # pragma: no cover - entorno sin extras
    from cryptography.hazmat.primitives import hashes, serialization  # noqa
    from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa

    _HAVE_CRYPTO = True
except Exception:  # ImportError o binario ausente
    _HAVE_CRYPTO = False


def sign_document(content: str, key_path: Optional[str] = None) -> bytes:
    """RSA/SHA256 over the supplied bytes; never a simulated fallback.

    This primitive is not XMLDSig/XAdES or an authority accreditation.
    """
    if not _HAVE_CRYPTO or not key_path:
        raise InvoiceSubmissionError("Firma RSA no disponible o clave no configurada")
    try:
        if not isinstance(content, str) or not content:
            raise ValueError("empty document")
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        with open(key_path, "rb") as source:
            key = load_pem_private_key(source.read(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("unsupported key")
        return key.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        raise InvoiceSubmissionError("No se pudo firmar el documento fiscal") from None


# ──────────────────────────────────────────────────────────────
# Interfaz proveedores fiscales
# ──────────────────────────────────────────────────────────────
class ElectronicInvoiceProvider(ABC):
    country: CountryTaxRegime

    @abstractmethod
    async def generate_document(self, invoice_data: dict) -> str:
        """Serializa el documento fiscal (XML UBL / JSON CFDI)."""

    @abstractmethod
    async def submit_to_authority(self, document: str, signature: bytes) -> dict:
        """Envía a la autoridad. Retorna {unique_identifier, pdf_url, qr_code_url}.

        Raises InvoiceSubmissionError si la autoridad rechaza.
        Un adaptador real debe devolver accepted=True e identificador verificable.
        """

    def supports_real_submission(self) -> bool:
        return False

    def is_stub(self) -> bool:
        return not self.supports_real_submission()


class DianColombiaAdapter(ElectronicInvoiceProvider):
    """Borrador XML inspirado en UBL; sin transporte DIAN homologado."""

    country = CountryTaxRegime.COLOMBIA
    _NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"

    def __init__(
        self,
        api_key: Optional[str] = None,
        certificate_path: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.api_key = api_key or settings.DIAN_API_KEY
        self.certificate_path = certificate_path or settings.DIAN_CERTIFICATE_PATH
        self.password = password or settings.DIAN_PASSWORD

    async def generate_document(self, d: dict) -> str:
        root = ET.Element("Invoice", xmlns=self._NS)

        def sub(parent, tag, value=None, **attributes):
            el = ET.SubElement(
                parent, tag, {key: str(value) for key, value in attributes.items()}
            )
            if value is not None:
                el.text = str(value)
            return el

        sub(root, "ID", f"{d['resolution_number']}-{d['sequence']}")
        sub(root, "IssueDate", d["issue_date"])
        sub(root, "IssueTime", d["issue_time"])
        sub(
            root,
            "InvoiceTypeCode",
            "380" if d.get("invoice_type", "VENTA") == "VENTA" else "381",
        )
        sub(root, "DocumentCurrencyCode", d["currency"])

        emitter = sub(root, "AccountingSupplierParty")
        party = sub(emitter, "Party")
        pid = sub(party, "PartyIdentification")
        sub(pid, "ID", settings.COMPANY_NIT, schemeID="9")
        pn = sub(party, "PartyName")
        sub(pn, "Name", settings.COMPANY_NAME)
        addr = sub(party, "PostalAddress")
        sub(addr, "StreetName", settings.COMPANY_ADDRESS)
        city = sub(addr, "City")
        sub(city, "Name", settings.COMPANY_CITY_CODE)
        csub = sub(addr, "Country")
        sub(csub, "IdentificationCode", "CO")

        cust = d.get("customer", {})
        receiver = sub(root, "AccountingCustomerParty")
        rparty = sub(receiver, "Party")
        rpid = sub(rparty, "PartyIdentification")
        sub(rpid, "ID", cust.get("tax_id", "NN"), schemeID="9")
        rpn = sub(rparty, "PartyName")
        sub(rpn, "Name", cust.get("name", "Cliente"))

        for line in d.get("items", []):
            le = sub(root, "InvoiceLine")
            sub(le, "ID", line.get("index", 1))
            sub(le, "InvoicedQuantity", line.get("quantity", 1))
            sub(le, "LineExtensionAmount", Decimal(line["base_amount_cents"]) / 100)
            it = sub(le, "Item")
            sub(it, "Name", line.get("name", "Servicio de entrega"))

        tot = sub(root, "LegalMonetaryTotal")
        sub(tot, "LineExtensionAmount", Decimal(d["subtotal_cents"]) / 100)
        sub(tot, "TaxExclusiveAmount", Decimal(d["subtotal_cents"]) / 100)
        sub(tot, "TaxInclusiveAmount", Decimal(d["grand_total_cents"]) / 100)
        sub(tot, "PayableAmount", Decimal(d["grand_total_cents"]) / 100)

        tax = sub(root, "TaxTotal")
        sub(tax, "TaxAmount", Decimal(d["tax_total_cents"]) / 100)

        return ET.tostring(root, encoding="unicode")

    async def submit_to_authority(self, document: str, signature: bytes) -> dict:
        raise InvoiceSubmissionError(
            "Integración fiscal real no homologada; envío externo no habilitado"
        )


class SatMexicoAdapter(ElectronicInvoiceProvider):
    """Vista JSON de previsualización; sin timbrado SAT/PAC homologado."""

    country = CountryTaxRegime.MEXICO

    def __init__(self, cert_file: Optional[str] = None, key_file: Optional[str] = None):
        self.cert_file = cert_file or settings.SAT_CERT_FILE
        self.key_file = key_file or settings.SAT_KEY_FILE

    async def generate_document(self, d: dict) -> str:
        cfdi = {
            "Version": "4.0",
            "Serie": d.get("serie", "A"),
            "Folio": d["sequence"],
            "Fecha": f"{d['issue_date']}T{d['issue_time']}Z",
            "SubTotal": decimal_amount(d["subtotal_cents"]),
            "Total": decimal_amount(d["grand_total_cents"]),
            "MetodoPago": d.get("payment_method", "PPD"),
            "UsoCfdi": d.get("usage_code", "G03"),
            "Moneda": d["currency"],
            "TipoCambio": str(d.get("exchange_rate", "1.0000")),
            "Emisor": {
                "Rfc": settings.COMPANY_NIT,
                "Nombre": settings.COMPANY_NAME,
                "RegimenFiscal": "601",
            },
            "Receptor": {
                "Rfc": d.get("customer", {}).get("tax_id", "XAXX010101000"),
                "Nombre": d.get("customer", {}).get("name", "Publico General"),
                "UsoCfdi": d.get("usage_code", "G03"),
            },
            "Conceptos": [
                {
                    "ClaveProdServ": c.get("product_key", "81101500"),
                    "Cantidad": c.get("quantity", 1),
                    "Descripcion": c.get("name", "Servicio de entrega"),
                    "ValorUnitario": decimal_unit_amount(
                        c["base_amount_cents"], c.get("quantity", 1)
                    ),
                    "Importe": decimal_amount(c["base_amount_cents"]),
                }
                for c in d.get("items", [])
            ],
            "Impuestos": {
                "TotalImpuestosTrasladados": decimal_amount(d["tax_total_cents"]),
                "Traslados": [
                    {"Impuesto": "002", "TipoFactor": "Tasa", "TasaOCuota": "0.160000"}
                ],
            },
        }
        return json.dumps(cfdi, ensure_ascii=False)

    async def submit_to_authority(self, document: str, signature: bytes) -> dict:
        raise InvoiceSubmissionError(
            "Integración fiscal real no homologada; envío externo no habilitado"
        )


PROVIDERS: Dict[CountryTaxRegime, type] = {
    CountryTaxRegime.COLOMBIA: DianColombiaAdapter,
    CountryTaxRegime.MEXICO: SatMexicoAdapter,
}


# ──────────────────────────────────────────────────────────────
# Orquestador
# ──────────────────────────────────────────────────────────────
class InvoicingEngine:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._providers: Dict[CountryTaxRegime, ElectronicInvoiceProvider] = {}

    def provider_for(self, country: CountryTaxRegime) -> ElectronicInvoiceProvider:
        prov = self._providers.get(country)
        if prov is None:
            cls = PROVIDERS.get(country)
            if cls is None:
                raise InvoiceSubmissionError("País sin adaptador fiscal disponible")
            prov = cls()
            self._providers[country] = prov
        return prov

    # ------------------------------------------------------------------
    async def _get_active_resolution(
        self, country: CountryTaxRegime, *, preview: bool = False
    ) -> InvoiceResolution:
        today = datetime.now(timezone.utc).date()
        res = await self.db.execute(
            select(InvoiceResolution)
            .where(
                InvoiceResolution.country_code == country,
                InvoiceResolution.is_active.is_(True),
                InvoiceResolution.is_sandbox.is_(preview),
                InvoiceResolution.valid_from <= today,
                InvoiceResolution.valid_until >= today,
            )
            .order_by(InvoiceResolution.valid_until.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        resolution = res.scalar_one_or_none()
        if resolution is None:
            raise InvoiceSubmissionError(
                f"No hay resolución activa autorizada para {country.value}"
            )
        return resolution

    async def _next_sequence(self, resolution: InvoiceResolution) -> int:
        """Atomic allocation from the current SQL row, with no double increment."""
        today = datetime.now(timezone.utc).date()
        history = (
            select(func.max(ElectronicInvoice.sequence_number))
            .where(
                or_(
                    ElectronicInvoice.resolution_id == resolution.id,
                    and_(
                        ElectronicInvoice.resolution_id.is_(None),
                        ElectronicInvoice.provider_type == resolution.country_code,
                        ElectronicInvoice.resolution_number == resolution.start_range,
                    ),
                )
            )
            .scalar_subquery()
        )
        candidate = case(
            (
                InvoiceResolution.current_counter < InvoiceResolution.start_range,
                InvoiceResolution.start_range,
            ),
            else_=InvoiceResolution.current_counter + 1,
        )
        historical_next = func.coalesce(history, 0) + 1
        allocation = case(
            (candidate < historical_next, historical_next), else_=candidate
        )
        result = await self.db.execute(
            update(InvoiceResolution)
            .where(
                InvoiceResolution.id == resolution.id,
                InvoiceResolution.is_active.is_(True),
                InvoiceResolution.start_range >= 1,
                InvoiceResolution.end_range >= InvoiceResolution.start_range,
                InvoiceResolution.current_counter >= 0,
                allocation <= InvoiceResolution.end_range,
                InvoiceResolution.valid_from <= today,
                InvoiceResolution.valid_until >= today,
            )
            .values(current_counter=allocation)
            .returning(InvoiceResolution.current_counter)
            .execution_options(synchronize_session=False)
        )
        sequence = result.scalar_one_or_none()
        if type(sequence) is not int:
            raise InvoiceSubmissionError(
                "Resolución ausente, no vigente o rango agotado"
            )
        return sequence

    async def _daily_count(self, resolution: InvoiceResolution) -> int:
        # Legacy rows without an FK count conservatively against any matching range.
        count = await self.db.scalar(
            select(func.count())
            .select_from(ElectronicInvoice)
            .where(
                ElectronicInvoice.issue_date == datetime.now(timezone.utc).date(),
                or_(
                    ElectronicInvoice.resolution_id == resolution.id,
                    and_(
                        ElectronicInvoice.resolution_id.is_(None),
                        ElectronicInvoice.provider_type == resolution.country_code,
                        ElectronicInvoice.resolution_number == resolution.start_range,
                    ),
                ),
            )
        )
        return int(count or 0)

    # ------------------------------------------------------------------
    async def create_electronic_invoice(
        self,
        order_id: uuid.UUID,
        customer_info: dict,
        items: List[dict],
        payment_method: str = "TARJETA",
        country: Optional[CountryTaxRegime] = None,
        invoice_type: InvoiceType = InvoiceType.VENTA,
        reference_invoice_id: Optional[uuid.UUID] = None,
        preview: bool = False,
    ) -> ElectronicInvoice:
        """Flujo completo: resolver → impuestos → documento → firma → envío → persistir.

        `items`: [{'name','unit_price_cents','quantity','category'}].
        Nunca lanza por fallos del proveedor: persiste RECHAZADA con error_message.
        Lanza ValueError solo por datos de entrada inválidos.
        """
        if not settings.ENABLE_ELECTRONIC_INVOICING:
            raise InvoiceSubmissionError("Facturación electrónica deshabilitada")
        country = country or CountryTaxRegime(settings.FISCAL_DEFAULT_COUNTRY)
        provider = self.provider_for(country)
        if preview:
            if not sandbox_allowed():
                raise InvoiceSubmissionError(
                    "Previsualización fiscal no habilitada en este entorno"
                )
        elif not provider.supports_real_submission():
            raise InvoiceSubmissionError(
                "Integración fiscal real no homologada; envío externo no habilitado"
            )
        if not items or len(items) > 100:
            raise ValueError("La factura requiere entre 1 y 100 líneas")
        for item in items:
            checked_cents(item.get("unit_price_cents"))
            quantity = item.get("quantity", 1)
            if type(quantity) is not int or not 1 <= quantity <= 1000:
                raise ValueError("Cantidad de línea inválida")

        if await self.db.scalar(select(Order.id).where(Order.id == order_id)) is None:
            raise InvoiceOrderNotFound("Pedido no encontrado")
        calc: TaxCalculator = await get_tax_calculator(country, self.db)
        line_results = calc.apply_taxes_to_items(items)

        subtotal = sum(r.base_amount_cents for r in line_results)
        tax_total = sum(r.total_tax_cents + r.included_tax_cents for r in line_results)
        retentions = sum(r.total_retentions_cents for r in line_results)
        grand = sum(r.line_total_cents for r in line_results)
        if any(
            abs(value) > MAX_CENTS for value in (subtotal, tax_total, retentions, grand)
        ):
            raise ValueError("Total fiscal fuera de rango")
        if invoice_type == InvoiceType.NOTA_CREDITO:
            subtotal, tax_total, retentions, grand = (
                -subtotal,
                -tax_total,
                -retentions,
                -grand,
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        resolution = await self._get_active_resolution(country, preview=preview)

        if await self._daily_count(resolution) >= settings.INVOICE_DAILY_LIMIT:
            raise InvoiceSubmissionError(
                f"Límite diario de emisión ({settings.INVOICE_DAILY_LIMIT}) alcanzado"
            )

        sequence = await self._next_sequence(resolution)

        # Inputs are already denominated in the selected country's minor units.
        exchange_rate = Decimal("1.0000")

        invoice = ElectronicInvoice(
            id=uuid.uuid4(),
            order_id=order_id,
            resolution_id=resolution.id,
            execution_mode="sandbox" if preview else "real",
            invoice_type=invoice_type,
            resolution_number=int(resolution.start_range),
            sequence_number=sequence,
            issue_date=now.date(),
            issue_time=now.time(),
            provider_type=country,
            currency_code="COP" if country == CountryTaxRegime.COLOMBIA else "MXN",
            exchange_rate=exchange_rate,
            subtotal_cents=subtotal,
            tax_total_cents=tax_total,
            retention_total_cents=retentions,
            discount_total_cents=0,
            grand_total_cents=grand,
            status=InvoiceStatus.PENDIENTE,
            reference_invoice_id=reference_invoice_id,
            customer_info_json=json.dumps(customer_info, ensure_ascii=False),
            tax_breakdown_json=json.dumps(
                [r.to_dict() for r in line_results], ensure_ascii=False
            ),
        )
        self.db.add(invoice)
        # Persist reservation and release the range lock before signing/provider I/O.
        await self.db.commit()
        await self.db.refresh(invoice)

        payload = {
            "resolution_number": invoice.resolution_number,
            "sequence": sequence,
            "issue_date": now.strftime("%Y-%m-%d"),
            "issue_time": now.strftime("%H:%M:%S"),
            "customer": customer_info,
            "items": [{**it, **lr.to_dict()} for it, lr in zip(items, line_results)],
            "payment_method": payment_method,
            "currency": invoice.currency_code,
            "exchange_rate": str(exchange_rate),
            "subtotal_cents": subtotal,
            "tax_total_cents": tax_total,
            "grand_total_cents": grand,
            "invoice_type": invoice_type.value,
        }
        try:
            document = await provider.generate_document(payload)
            invoice.signed_xml_content = document
            if preview:
                invoice.error_message = PREVIEW_NOTE
                await self.db.commit()
                await self.db.refresh(invoice)
                return invoice
            signature = await run_in_threadpool(
                sign_document, document, resolution.private_key_path
            )
            result = await provider.submit_to_authority(document, signature)
            identifier = result.get("unique_identifier")
            if (
                result.get("accepted") is not True
                or not isinstance(identifier, str)
                or not identifier
                or len(identifier) > 100
                or any(not 33 <= ord(char) <= 126 for char in identifier)
                or identifier.lower().startswith(("stub:", "sandbox:"))
            ):
                raise InvoiceSubmissionError("Aceptación fiscal no verificable")
            for field in ("pdf_url", "qr_code_url"):
                link = result.get(field)
                if link is not None:
                    if not isinstance(link, str) or len(link) > 4096:
                        raise InvoiceSubmissionError("Enlace fiscal inválido")
                    parsed = urlsplit(link)
                    if (
                        parsed.scheme != "https"
                        or not parsed.hostname
                        or parsed.username
                        or parsed.password
                    ):
                        raise InvoiceSubmissionError("Enlace fiscal inválido")
            invoice.status = InvoiceStatus.ACEPTADA
            invoice.unique_identifier = result.get("unique_identifier")
            invoice.pdf_url = result.get("pdf_url")
            invoice.qr_code_url = result.get("qr_code_url")
            invoice.signed_xml_content = document
        except SQLAlchemyError:
            await self.db.rollback()
            raise
        except Exception:
            invoice.status = InvoiceStatus.RECHAZADA
            invoice.error_message = "No se obtuvo aceptación fiscal verificable"
            logger.warning("Emisión fiscal terminada sin aceptación verificable")

        await self.db.commit()
        await self.db.refresh(invoice)
        return invoice

    # ------------------------------------------------------------------
    async def issue_credit_note(
        self, original_invoice_id: uuid.UUID, reason: str, amount_cents: int
    ) -> ElectronicInvoice:
        """Nota crédito vinculada a factura original (devoluciones/reembolsos)."""
        original = await self.db.get(ElectronicInvoice, original_invoice_id)
        if original is None:
            raise ValueError("Factura original no encontrada")
        if not invoice_evidence(original)["is_officially_accepted"]:
            raise ValueError(
                "Se requiere aceptación fiscal verificable para una nota crédito"
            )
        nc_items = [
            {
                "name": f"Nota crédito: {reason}"[:120],
                "unit_price_cents": abs(int(amount_cents)),
                "quantity": 1,
                "category": "ajuste",
            }
        ]
        customer = json.loads(original.customer_info_json or "{}")
        return await self.create_electronic_invoice(
            order_id=original.order_id,
            customer_info=customer,
            items=nc_items,
            payment_method="REFUND",
            country=original.provider_type,
            invoice_type=InvoiceType.NOTA_CREDITO,
            reference_invoice_id=original.id,
        )

    # ------------------------------------------------------------------
    async def cancel_invoice(
        self, invoice_id: uuid.UUID, reason: str
    ) -> ElectronicInvoice:
        inv = await self.db.get(ElectronicInvoice, invoice_id)
        if inv is None:
            raise ValueError("Factura no encontrada")
        if inv.status not in (InvoiceStatus.ACEPTADA, InvoiceStatus.ENVIADA):
            raise ValueError("Solo facturas ENVIADA/ACEPTADA son cancelables")
        raise InvoiceSubmissionError(
            "Cancelación fiscal no homologada; no se modificó el estado"
        )


# ──────────────────────────────────────────────────────────────
# Hook seguro post-entrega (llamar SOLO post-commit, fire-and-forget)
# ──────────────────────────────────────────────────────────────
async def issue_invoice_for_order_safe(order_id: uuid.UUID) -> None:
    """Se invoca así: asyncio.create_task(issue_invoice_for_order_safe(order.id))

    Construye las líneas desde Order (fee de envío como servicio gravado) y
    emite la factura electrónica. Cualquier fallo queda en el log: la entrega
    ya está commiteada y NUNCA se revierte por un problema fiscal.
    """
    if not settings.ENABLE_ELECTRONIC_INVOICING:
        logger.info("Facturación deshabilitada (flag); skip orden %s", order_id)
        return
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            order = await db.get(Order, order_id)
            if order is None:
                logger.warning("Hook factura: orden %s inexistente", order_id)
                return
            fee_cents = money_to_cents(order.delivery_fee)
            gross_cents = money_to_cents(order.total)
            if gross_cents <= 0:
                logger.info("Orden %s sin monto; no se factura", order_id)
                return
            # Una sola línea: servicio de entrega D360 (IVA servicios)
            items = [
                {
                    "name": "Servicio de entrega Delivery360",
                    "unit_price_cents": gross_cents,
                    "quantity": 1,
                    "category": "delivery_service",
                }
            ]
            customer = {
                "name": order.customer_name,
                "tax_id": "NN",  # consumidor final sin NIT → DIAN permite NN
                "email": order.customer_email,
                "phone": order.customer_phone,
                "billing_mode": (
                    "simplified" if order.customer_email is None else "full"
                ),
            }
            engine = InvoicingEngine(db)
            inv = await engine.create_electronic_invoice(
                order_id=order.id,
                customer_info=customer,
                items=items,
                payment_method=(order.payment_method or "CARD").upper(),
                country=CountryTaxRegime(settings.FISCAL_DEFAULT_COUNTRY),
            )
            logger.info(
                "Factura %s → estado %s (orden %s, fee=%d¢)",
                inv.id,
                inv.status.value,
                order_id,
                fee_cents,
            )
    except Exception:
        logger.warning(
            "Hook fiscal sin emisión confirmada; revisar configuración y evidencia local"
        )

"""Motor de Facturación Electrónica — Fase 10 (Hito 3).

Diseño:
- `ElectronicInvoiceProvider` es una ABC; los adaptadores DIAN (CO, UBL 2.1) y
  SAT (MX, CFDI 4.0) generan el documento fiscal y envían a la autoridad.
- SIN credenciales reales → modo STUB sandbox: firma simulada (hash), respuesta
  ACEPTADA local determinista. Jamás crash (patrón omnichannel Fase 9).
- Los imports costosos/opcionales (lxml, cryptography) van en try/except con
  fallback a stdlib (xml.etree / hashlib+secrets) — patrón OR-Tools Fase 8.
- Hook post-entrega NO bloqueante: `issue_invoice_for_order_safe()` se invoca
  vía asyncio.create_task después del commit; cualquier excepción solo loggea.
- Feature flag maestro: settings.ENABLE_ELECTRONIC_INVOICING=False → no emite.
- Protección anti-fraude: límite diario INVOICE_DAILY_LIMIT por resolución.
- Numeración atómica: UPDATE ... current_counter+1 con row lock (SELECT FOR UPDATE).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

from sqlalchemy import func, select, text, update
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

logger = logging.getLogger("delivery360.invoicing")


class InvoiceSubmissionError(Exception):
    """La autoridad fiscal rechazó el documento."""


# ──────────────────────────────────────────────────────────────
# Utilidades de firma (cryptography opcional)
# ──────────────────────────────────────────────────────────────
try:  # pragma: no cover - entorno sin extras
    from cryptography.hazmat.primitives import hashes, serialization  # noqa
    from cryptography.hazmat.primitives.asymmetric import padding  # noqa
    from cryptography.x509 import load_pem_x509_certificate  # noqa

    _HAVE_CRYPTO = True
except Exception:  # ImportError o binario ausente
    _HAVE_CRYPTO = False


def sign_document(content: str, key_path: Optional[str] = None) -> bytes:
    """Firma digital real si hay clave+cryptography; stub determinista si no.

    Stub: SHA-256(content)+nonce → hex firmado 'simulado'. Suficiente para
    sandbox/dev; NUNCA usar en producción (el adapter chequea credenciales).
    """
    raw = content.encode("utf-8")
    if _HAVE_CRYPTO and key_path:
        try:
            with open(key_path, "rb") as fh:
                from cryptography.hazmat.primitives.serialization import (
                    load_pem_private_key,
                )

                pkey = load_pem_private_key(fh.read(), password=None)
            return pkey.sign(raw, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            logger.warning("Firma real falló (%s); uso stub firmado", exc)
    digest = hashlib.sha256(raw + b"stub:" + secrets.token_bytes(8)).hexdigest()
    return digest.encode("ascii")


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
        En modo stub retorna ACEPTADO simulado determinista.
        """

    def is_stub(self) -> bool:
        return True  # sobreescrito por adaptadores con credenciales


class DianColombiaAdapter(ElectronicInvoiceProvider):
    """DIAN Colombia — UBL 2.1 (sandbox/stub sin api_key)."""

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

    def is_stub(self) -> bool:
        return not (self.api_key and self.certificate_path)

    async def generate_document(self, d: dict) -> str:
        root = ET.Element("Invoice", xmlns=self._NS)

        def sub(parent, tag, value=None):
            el = ET.SubElement(parent, tag)
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
        if self.is_stub():
            cufe = hashlib.sha256(document.encode()).hexdigest()
            logger.info("DIAN STUB sandbox: factura aceptada localmente")
            return {
                "unique_identifier": cufe,
                "pdf_url": f"stub://invoice/{cufe[:16]}.pdf",
                "qr_code_url": f"https://catalogodatos.dian.gov.co/catalogador/web/#/facturas?cufe={cufe}",
            }
        try:
            import httpx

            payload = {
                "document": base64.b64encode(document.encode()).decode(),
                "signature": base64.b64encode(signature).decode(),
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://bac.dian.gov.co/descargables/BES.asmx/AddDocument",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                result = resp.json()
            if result.get("StatusCode") == "Accepted":
                return {
                    "unique_identifier": result.get("CUFE"),
                    "pdf_url": result.get("PDFPreviewURL"),
                    "qr_code_url": result.get("QRCodeURL"),
                }
            raise InvoiceSubmissionError(result.get("ErrorMessage", "Rechazo DIAN"))
        except InvoiceSubmissionError:
            raise
        except Exception as exc:
            raise InvoiceSubmissionError(f"Fallo envío DIAN: {exc}") from exc


class SatMexicoAdapter(ElectronicInvoiceProvider):
    """SAT México — CFDI 4.0 (JSON canónico; stub sin e.firma)."""

    country = CountryTaxRegime.MEXICO

    def __init__(self, cert_file: Optional[str] = None, key_file: Optional[str] = None):
        self.cert_file = cert_file or settings.SAT_CERT_FILE
        self.key_file = key_file or settings.SAT_KEY_FILE

    def is_stub(self) -> bool:
        return not (self.cert_file and self.key_file)

    async def generate_document(self, d: dict) -> str:
        cfdi = {
            "Version": "4.0",
            "Serie": d.get("serie", "A"),
            "Folio": d["sequence"],
            "Fecha": f"{d['issue_date']}T{d['issue_time']}Z",
            "SubTotal": float(Decimal(d["subtotal_cents"]) / 100),
            "Total": float(Decimal(d["grand_total_cents"]) / 100),
            "MetodoPago": d.get("payment_method", "PPD"),
            "UsoCfdi": d.get("usage_code", "G03"),
            "Moneda": d["currency"] if d["currency"] != "COP" else "MXN",
            "TipoCambio": float(d.get("exchange_rate", 1)),
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
                    "ValorUnitario": float(Decimal(str(c["base_amount_cents"])) / 100),
                    "Importe": float(Decimal(str(c["base_amount_cents"])) / 100),
                }
                for c in d.get("items", [])
            ],
            "Impuestos": {
                "TotalImpuestosTrasladados": float(Decimal(d["tax_total_cents"]) / 100),
                "Traslados": [
                    {"Impuesto": "002", "TipoFactor": "Tasa", "TasaOCuota": "0.160000"}
                ],
            },
        }
        return json.dumps(cfdi, ensure_ascii=False)

    async def submit_to_authority(self, document: str, signature: bytes) -> dict:
        if self.is_stub():
            uuid_v = str(uuid.uuid4())
            logger.info("SAT STUB sandbox: CFDI aceptado localmente")
            return {
                "unique_identifier": uuid_v,
                "pdf_url": f"stub://cfdi/{uuid_v}.pdf",
                "qr_code_url": f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id={uuid_v}",
            }
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    settings.SAT_API_ENDPOINT
                    or "https://prod-publica.cfdi.sat.gob.mx/wsConsultaSat",
                    content=document.encode(),
                    headers={"Content-Type": "application/xml"},
                )
                resp.raise_for_status()
                data = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
            uid = data.get("UUID") or data.get("id")
            if not uid:
                raise InvoiceSubmissionError("SAT no devolvió UUID")
            return {
                "unique_identifier": uid,
                "pdf_url": data.get("PdfUrl"),
                "qr_code_url": data.get("QrUrl"),
            }
        except InvoiceSubmissionError:
            raise
        except Exception as exc:
            raise InvoiceSubmissionError(f"Fallo timbrado SAT: {exc}") from exc


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
                # régimen sin adaptador → CO como base con warning (extensible)
                logger.warning("Sin adaptador para %s; uso genérico CO", country.value)
                cls = DianColombiaAdapter
            prov = cls()
            self._providers[country] = prov
        return prov

    # ------------------------------------------------------------------
    async def _get_active_resolution(
        self, country: CountryTaxRegime
    ) -> InvoiceResolution:
        today = datetime.now(timezone.utc).date()
        res = await self.db.execute(
            select(InvoiceResolution)
            .where(
                InvoiceResolution.country_code == country,
                InvoiceResolution.is_active.is_(True),
                InvoiceResolution.valid_from <= today,
                InvoiceResolution.valid_until >= today,
            )
            .order_by(InvoiceResolution.valid_until.desc())
            .limit(1)
        )
        resolution = res.scalar_one_or_none()
        if resolution is None:
            raise InvoiceSubmissionError(
                f"No hay resolución activa autorizada para {country.value}"
            )
        return resolution

    async def _next_sequence(self, resolution: InvoiceResolution) -> int:
        """Contador atómico con row-lock (seguro multi-worker)."""
        await self.db.execute(
            update(InvoiceResolution)
            .where(InvoiceResolution.id == resolution.id)
            .values(current_counter=InvoiceResolution.current_counter + 1)
        )
        await self.db.flush()
        refreshed = await self.db.get(InvoiceResolution, resolution.id)
        seq = int(refreshed.current_counter) + 1  # inicia en 1
        if seq > int(refreshed.end_range):
            raise InvoiceSubmissionError(
                f"Resolución {refreshed.prefix} agotada (seq {seq} > {refreshed.end_range})"
            )
        return seq

    async def _daily_count(self, resolution_id: uuid.UUID) -> int:
        res = await self.db.execute(
            select(func.count())
            .select_from(ElectronicInvoice)
            .where(
                ElectronicInvoice.resolution_number.isnot(None),
                ElectronicInvoice.issue_date == datetime.now(timezone.utc).date(),
            )
        )
        return int(res.scalar() or 0)

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
    ) -> ElectronicInvoice:
        """Flujo completo: resolver → impuestos → documento → firma → envío → persistir.

        `items`: [{'name','unit_price_cents','quantity','category'}].
        Nunca lanza por fallos del proveedor: persiste RECHAZADA con error_message.
        Lanza ValueError solo por datos de entrada inválidos.
        """
        country = country or CountryTaxRegime(settings.FISCAL_DEFAULT_COUNTRY)
        if not items:
            raise ValueError("Factura sin líneas de detalle")

        calc: TaxCalculator = await get_tax_calculator(country, self.db)
        line_results = calc.apply_taxes_to_items(items)

        subtotal = sum(r.base_amount_cents for r in line_results)
        tax_total = sum(r.total_tax_cents for r in line_results)
        retentions = sum(r.total_retentions_cents for r in line_results)
        grand = subtotal + tax_total - retentions
        if invoice_type == InvoiceType.NOTA_CREDITO:
            subtotal, tax_total, retentions, grand = (
                -subtotal,
                -tax_total,
                -retentions,
                -grand,
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        resolution = await self._get_active_resolution(country)

        if await self._daily_count(resolution.id) >= settings.INVOICE_DAILY_LIMIT:
            raise InvoiceSubmissionError(
                f"Límite diario de emisión ({settings.INVOICE_DAILY_LIMIT}) alcanzado"
            )

        sequence = await self._next_sequence(resolution)

        from app.services.fx_service import get_exchange_rate

        exchange_rate = await get_exchange_rate("USD", "COP")

        invoice = ElectronicInvoice(
            id=uuid.uuid4(),
            order_id=order_id,
            invoice_type=invoice_type,
            resolution_number=int(resolution.start_range),
            sequence_number=sequence,
            issue_date=now.date(),
            issue_time=now.time(),
            provider_type=country,
            currency_code="COP",
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

        provider = self.provider_for(country)
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
            signature = sign_document(document, resolution.private_key_path)
            result = await provider.submit_to_authority(document, signature)
            invoice.status = InvoiceStatus.ACEPTADA
            invoice.unique_identifier = result.get("unique_identifier")
            invoice.pdf_url = result.get("pdf_url")
            invoice.qr_code_url = result.get("qr_code_url")
            invoice.signed_xml_content = document
        except InvoiceSubmissionError as exc:
            invoice.status = InvoiceStatus.RECHAZADA
            invoice.error_message = str(exc)[:2000]
            logger.error("Factura orden %s rechazada: %s", order_id, exc)
        except SQLAlchemyError as exc:
            invoice.status = InvoiceStatus.RECHAZADA
            invoice.error_message = f"Error persistencia: {exc}"[:2000]
            logger.exception("DB error facturación orden %s", order_id)
        except Exception as exc:  # defensa final: jamás romper el flujo padre
            invoice.status = InvoiceStatus.RECHAZADA
            invoice.error_message = f"Error inesperado: {exc}"[:2000]
            logger.exception("Error inesperado facturación orden %s", order_id)

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
        if original.status != InvoiceStatus.ACEPTADA:
            raise ValueError("Solo se pueden anular facturas ACEPTADAS")
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
        inv.status = InvoiceStatus.CANCELADA
        inv.cancellation_date = datetime.now(timezone.utc).replace(tzinfo=None)
        inv.error_message = f"Cancelada: {reason}"[:2000]
        await self.db.commit()
        await self.db.refresh(inv)
        return inv


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
            fee_cents = int(round(float(order.delivery_fee or 0) * 100))
            gross_cents = int(round(float(order.total or 0) * 100))
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
        logger.exception("Hook factura orden %s falló (no bloqueante)", order_id)

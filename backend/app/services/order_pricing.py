"""Exact prospective USD prices; never convert historical floating-point rows."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re
from typing import Annotated

from pydantic import BeforeValidator
from sqlalchemy import func, select

from app.core.exceptions import AppException
from app.core.json_types import JsonValue, json_value
from app.models.order import Order

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("99999999.99")
MAX_REVISION = 2147483647
MONEY_FIELDS = {"items", "subtotal", "delivery_fee", "total", "declared_value"}


def decimal_value(value: object, *, quantity=False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise AppException("Importe o cantidad decimal inválida", 422)
    pattern = (
        r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,3})?"
        if quantity
        else r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?"
    )
    if not re.fullmatch(pattern, str(value)):
        raise AppException(
            "Usa importes con dos decimales y cantidades con hasta tres, sin exponentes",
            422,
        )
    result = Decimal(str(value))
    if quantity:
        if not 0 < result <= Decimal("999999.999"):
            raise AppException(
                "La cantidad debe ser positiva y estar dentro del límite", 422
            )
    elif not 0 <= result <= MAX_AMOUNT:
        raise AppException("Importe fuera del límite de la orden", 422)
    return result if quantity else result.quantize(CENT)


def money_input(value):
    try:
        return decimal_value(value)
    except AppException as exc:
        raise ValueError(exc.message) from exc


MoneyInput = Annotated[Decimal, BeforeValidator(money_input)]


def bounded(value: Decimal) -> Decimal:
    if not value.is_finite() or not 0 <= value <= MAX_AMOUNT:
        raise AppException("Los importes acumulados exceden el límite de la orden", 422)
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Pricing:
    subtotal: Decimal
    delivery_fee: Decimal
    total: Decimal
    items: list[dict]

    def view(self, revision: int) -> dict:
        return {
            "version": 1,
            "currency": "USD",
            "revision": revision,
            "subtotal": format(self.subtotal, ".2f"),
            "delivery_fee": format(self.delivery_fee, ".2f"),
            "total": format(self.total, ".2f"),
            "items": self.items,
        }


def calculate(
    items: object, subtotal=None, delivery_fee=None, total=None, declared_value=None
) -> Pricing:
    if items is None:
        items = []
    if (
        not isinstance(items, list)
        or len(items) > 200
        or any(not isinstance(x, dict) for x in items)
    ):
        raise AppException("La orden admite hasta 200 artículos válidos", 422)
    normalized = []
    with localcontext() as context:
        context.prec = 40
        for raw in items:
            if (
                raw.get("quantity") is None
                and raw.get("unit_price") is None
                and raw.get("subtotal") is not None
            ):
                quantity = price = None
                line = decimal_value(raw["subtotal"])
            else:
                quantity = decimal_value(raw.get("quantity"), quantity=True)
                price = decimal_value(raw.get("unit_price"))
                line = bounded(
                    (quantity * price).quantize(CENT, rounding=ROUND_HALF_UP)
                )
                if (
                    raw.get("subtotal") is not None
                    and decimal_value(raw["subtotal"]) != line
                ):
                    raise AppException(
                        "El subtotal de un artículo no coincide con cantidad y precio",
                        422,
                    )
            copied = {
                **raw,
                "quantity": format(quantity, "f") if quantity is not None else None,
                "unit_price": format(price, ".2f") if price is not None else None,
                "subtotal": format(line, ".2f"),
            }
            try:
                json_value(copied)
            except ValueError as exc:
                raise AppException(
                    "Los artículos contienen metadatos inválidos", 422
                ) from exc
            normalized.append(copied)
        summed = bounded(
            sum((Decimal(x["subtotal"]) for x in normalized), Decimal("0.00"))
        )
        base = decimal_value(subtotal) if subtotal is not None else summed
        if normalized and base != summed:
            raise AppException(
                "El subtotal no coincide con la suma de los artículos", 422
            )
        fee = (
            decimal_value(delivery_fee) if delivery_fee is not None else Decimal("0.00")
        )
        final = bounded(base + fee)
        if total is not None and decimal_value(total) != final:
            raise AppException("El total no coincide con subtotal y envío", 422)
        if declared_value is not None and decimal_value(declared_value) != final:
            raise AppException("El valor declarado no coincide con el total", 422)
        return Pricing(base, fee, final, normalized)


def compatibility_items(items: list[dict]) -> JsonValue:
    return json_value(
        [
            {
                **item,
                "quantity": (
                    float(item["quantity"]) if item["quantity"] is not None else None
                ),
                "unit_price": (
                    float(item["unit_price"])
                    if item["unit_price"] is not None
                    else None
                ),
                "subtotal": float(item["subtotal"]),
            }
            for item in items
        ]
    )


def apply(order: Order, price: Pricing, *, expected_revision=None) -> None:
    if order.currency_code not in (None, "USD"):
        raise AppException("La orden no está denominada en USD", 409)
    current = order.pricing_revision
    if current != expected_revision:
        raise AppException("El precio cambió; recarga la orden antes de guardar", 412)
    if current is not None and current >= MAX_REVISION:
        raise AppException(
            "La revisión del precio requiere atención administrativa", 409
        )
    same = current is not None and (
        order.subtotal_exact,
        order.delivery_fee_exact,
        order.total_exact,
        order.items_exact,
    ) == (price.subtotal, price.delivery_fee, price.total, price.items)
    order.pricing_version = 1
    order.pricing_revision = current if same else (current or 0) + 1
    order.subtotal_exact, order.delivery_fee_exact, order.total_exact = (
        price.subtotal,
        price.delivery_fee,
        price.total,
    )
    order.items_exact = json_value(price.items)
    order.items = compatibility_items(price.items)
    order.subtotal, order.delivery_fee, order.total = (
        float(price.subtotal),
        float(price.delivery_fee),
        float(price.total),
    )


def update_price(order: Order, changes: dict) -> None:
    if not MONEY_FIELDS.intersection(changes):
        return
    if order.currency_code != "USD":
        raise AppException(
            "La moneda histórica requiere revisión antes de cambiar importes", 409
        )
    expected = changes.get("expected_pricing_revision")
    if order.pricing_version != 1 and not (
        "delivery_fee" in changes and ("items" in changes or "subtotal" in changes)
    ):
        raise AppException(
            "El precio anterior no es exacto; revisa y envía el precio completo", 409
        )
    items = changes.get(
        "items", order.items_exact if order.pricing_version == 1 else []
    )
    subtotal = (
        changes.get("subtotal")
        if "items" in changes or "subtotal" in changes
        else order.subtotal_exact
    )
    fee = changes.get("delivery_fee", order.delivery_fee_exact)
    price = calculate(
        items, subtotal, fee, changes.get("total"), changes.get("declared_value")
    )
    apply(order, price, expected_revision=expected)


def view(order: Order) -> dict | None:
    if order.pricing_version is None:
        return None
    if (
        order.pricing_version != 1
        or order.currency_code != "USD"
        or not isinstance(order.pricing_revision, int)
    ):
        raise AppException("El precio guardado requiere revisión", 409)
    price = calculate(
        order.items_exact,
        order.subtotal_exact,
        order.delivery_fee_exact,
        order.total_exact,
    )
    return price.view(order.pricing_revision)


def amount(order: Order, field: str) -> Decimal:
    if field not in ("subtotal", "delivery_fee", "total"):
        raise ValueError("Unknown order amount field")
    if getattr(order, "pricing_version", None) == 1:
        result = getattr(order, field + "_exact")
        if not isinstance(result, Decimal):
            raise AppException("El precio exacto requiere revisión", 409)
        return result
    try:
        result = Decimal(str(getattr(order, field) or 0))
        if not result.is_finite():
            raise InvalidOperation
        return result
    except (ValueError, InvalidOperation) as exc:
        raise AppException("El importe anterior requiere revisión", 409) from exc


async def aggregate(db, *filters) -> dict:
    exact = (
        await db.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.subtotal_exact), 0),
                func.coalesce(func.sum(Order.delivery_fee_exact), 0),
                func.coalesce(func.sum(Order.total_exact), 0),
            ).where(Order.currency_code == "USD", Order.pricing_version == 1, *filters)
        )
    ).one()
    legacy = await db.scalar(
        select(func.count(Order.id)).where(
            Order.currency_code == "USD", Order.pricing_version.is_(None), *filters
        )
    )
    return {
        "scope": "exact_usd_only",
        "currency": "USD",
        "order_count": int(exact[0]),
        "subtotal": format(Decimal(exact[1]), ".2f"),
        "delivery_fee": format(Decimal(exact[2]), ".2f"),
        "total": format(Decimal(exact[3]), ".2f"),
        "legacy_order_count": int(legacy or 0),
    }

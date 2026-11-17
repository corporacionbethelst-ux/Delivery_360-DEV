"""Shared synthetic exact audit envelope for intercepted visual regressions."""


def money():
    return dict(
        credit_usd="0.00",
        debit_usd="0.00",
        adjustment_usd="0.00",
        net_change_usd="0.00",
        pending_usd="0.00",
        ledger_rows=0,
        ledger_included=0,
        payout_rows=0,
        payout_included=0,
        ledger_exclusions=[
            dict(reason=r, count=0)
            for r in (
                "FECHA_NO_REGISTRADA",
                "MONEDA_NO_VERIFICADA",
                "FECHA_FUTURA",
                "ESTADO_NO_PROCESADO",
                "TIPO_NO_ADMITIDO",
            )
        ],
        payout_exclusions=[
            dict(reason=r, count=0)
            for r in (
                "FECHA_NO_REGISTRADA",
                "MONEDA_NO_VERIFICADA",
                "FECHA_FUTURA",
                "ESTADO_NO_PENDIENTE",
            )
        ],
    )


def envelope(rows, query):
    return dict(
        version=1,
        scope="operational_rider_audit_usd",
        currency="USD",
        viewer_user_id="synthetic-manager",
        viewer_role="GERENTE",
        generated_at="2026-11-15T16:00:00.123456Z",
        snapshot_basis="single_statement_visibility",
        ledger_basis="processed_registered_movements",
        payout_basis="current_pending_requests",
        available_balance_included=False,
        bank_verified=False,
        wallet_cents_included=False,
        content_sha256="a" * 64,
        filters=dict(
            status=query.get("status_filter", [None])[0],
            online=query["is_online"][0] == "true" if "is_online" in query else None,
            rider_id=query.get("rider_id", [None])[0],
        ),
        items=rows,
        total=len(rows),
        limit=int(query.get("limit", ["51"])[0]),
        offset=int(query.get("offset", ["0"])[0]),
    )


def records_envelope(value, query):
    """Synthetic exact records only; not a production conversion of stored floats."""
    from datetime import datetime, timezone

    kind = query["kind"][0]
    offset = int(query.get("offset", ["0"])[0])

    def stamp(v):
        if v is None:
            return None
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return (
            (d if d.tzinfo else d.replace(tzinfo=timezone.utc))
            .astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    rows = value["items"] if kind == "deliveries" else value
    items, support = [], []
    for source in rows:
        fallback = kind == "deliveries" and source["id"].startswith("order-")
        r = dict(
            id=source["id"],
            rider_id=source.get("rider_id", source.get("assigned_rider_id")),
            external_id=source.get("external_id"),
            customer_name=source.get("customer_name"),
            status=source.get("status"),
            created_at=stamp(source.get("created_at")),
            updated_at=stamp(source.get("updated_at")),
            currency_recorded=None,
            currency=None,
            currency_review=False,
        )
        if kind == "orders":
            r.update(
                amount=(
                    format(source["total"], ".2f")
                    if source.get("total") is not None
                    else None
                ),
                price_review=(
                    None
                    if source.get("total") is not None
                    else "PRECIO_HISTORICO_NO_EXACTO"
                ),
                pricing_revision=1,
                currency="USD",
                currency_recorded="USD",
            )
        else:
            bonus = source.get("locked_bonus_amount")
            r.update(
                order_id=source["order_id"],
                locked_bonus_amount=format(bonus, ".2f") if bonus is not None else None,
                money_review=[],
                fallback=fallback,
                currency_basis="locked_bonus_snapshot",
            )
        (support if fallback else items).append(r)
    return dict(
        version=2,
        scope="rider_audit_registered_records",
        kind=kind,
        units_basis="recorded_currency_no_conversion",
        snapshot_basis="single_statement_visibility",
        amount_basis=(
            "exact_order_price_not_rider_earnings"
            if kind == "orders"
            else "locked_delivery_bonus_not_ledger"
        ),
        pagination_basis="offset_live_records_real_deliveries_only",
        available_balance_included=False,
        bank_verified=False,
        wallet_cents_included=False,
        viewer_user_id="synthetic-manager",
        viewer_role="GERENTE",
        rider_id=query["rider_id"][0],
        limit=int(query.get("limit", ["51"])[0]),
        offset=offset,
        generated_at="2026-11-16T12:00:00.000000Z",
        content_sha256="a" * 64,
        total=len(items),
        items=items,
        fallback=support,
        fallback_limit=50,
        fallback_has_more=False,
    )


def transaction_envelope(rows, query):
    from datetime import datetime, timezone

    def stamp(v):
        if v is None:
            return None
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return (
            (d if d.tzinfo else d.replace(tzinfo=timezone.utc))
            .astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    items = []
    for source in rows:
        r = dict(source)
        for k in ("amount", "balance_before", "balance_after"):
            r[k] = None if source.get(k) is None else format(source[k], ".2f")
        for k in ("created_at", "updated_at", "processed_at"):
            r[k] = stamp(source.get(k))
        unit = source.get("currency")
        r.update(
            currency=unit,
            currency_recorded=unit,
            currency_review=False,
            money_review=[],
        )
        items.append(r)
    return dict(
        version=1,
        scope="registered_financial_records",
        units_basis="recorded_currency_no_conversion",
        balance_basis="registered_snapshots_not_available_balance",
        snapshot_basis="single_statement_visibility",
        available_balance_included=False,
        bank_verified=False,
        wallet_cents_included=False,
        customer_cashbook_included=False,
        viewer_user_id="synthetic-manager",
        viewer_role="GERENTE",
        generated_at="2026-11-16T12:00:00.000000Z",
        content_sha256="a" * 64,
        filters=dict(
            transaction_id=None,
            rider_id=query["rider_id"][0],
            type=None,
            status=None,
            date_from=None,
            date_to=None,
        ),
        limit=int(query.get("limit", ["51"])[0]),
        offset=int(query.get("offset", ["0"])[0]),
        total=len(items),
        items=items,
    )

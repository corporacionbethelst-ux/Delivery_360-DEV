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

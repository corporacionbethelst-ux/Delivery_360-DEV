"""Synthetic decimal envelopes for the intercepted transaction browser tests."""

from datetime import datetime, timezone
from decimal import Decimal


def envelope(rows, query, transaction_id=None):
    items = []
    for value in rows:
        row = dict(value)
        for field in ("amount", "balance_before", "balance_after"):
            raw = row.get(field)
            row[field] = format(Decimal(str(raw)), ".2f") if raw is not None else None
        for field in ("created_at", "updated_at", "processed_at"):
            raw = row.get(field)
            if raw is None:
                row[field] = None
            else:
                date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                date = (
                    date.replace(tzinfo=timezone.utc)
                    if date.tzinfo is None
                    else date.astimezone(timezone.utc)
                )
                row[field] = date.isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                )
        row.update(
            currency_recorded=None,
            currency=None,
            currency_review=False,
            money_review=[],
        )
        items.append(row)
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
        viewer_user_id="browser-user",
        viewer_role="GERENTE",
        generated_at="2026-11-15T16:00:00.123456Z",
        content_sha256="a" * 64,
        filters=dict(
            transaction_id=transaction_id,
            type=query.get("type", [None])[0],
            status=query.get("status", [None])[0],
            rider_id=None,
            date_from=None,
            date_to=None,
        ),
        limit=1 if transaction_id else int(query.get("limit", ["51"])[0]),
        offset=0 if transaction_id else int(query.get("offset", ["0"])[0]),
        total=len(items),
        items=items,
    )

"""Structural contract for mappings changed without a database migration."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, CreateIndex
from app.core.database import Base

TABLES = (
    "users",
    "rider_wallets",
    "financial_transactions",
    "payout_requests",
    "financials",
)


def mapping_contract(tables=TABLES):
    dialect = postgresql.dialect()
    contract = {}
    for name in tables:
        table = Base.metadata.tables[name]
        defaults = {}
        for column in table.columns:
            args = []
            for value in (column.default, column.onupdate):
                if value is None:
                    args.append(None)
                elif callable(value.arg):
                    args.append(value.arg.__qualname__)
                else:
                    args.append(str(value.arg))
            defaults[column.name] = args
        contract[name] = {
            "ddl": str(CreateTable(table).compile(dialect=dialect)),
            "indexes": sorted(
                str(CreateIndex(index).compile(dialect=dialect))
                for index in table.indexes
            ),
            "defaults": defaults,
            "enums": {
                column.name: list(column.type.enums)
                for column in table.columns
                if hasattr(column.type, "enums")
            },
        }
    return contract


def detailed_mapping_contract(tables):
    contract = mapping_contract(tables)
    for name in tables:
        table = Base.metadata.tables[name]
        contract[name]["foreign_keys"] = sorted(
            (
                dict(
                    column=key.parent.name,
                    target=key.target_fullname,
                    ondelete=key.ondelete,
                    onupdate=key.onupdate,
                    use_alter=key.use_alter,
                    name=key.name,
                    deferrable=key.deferrable,
                    initially=key.initially,
                )
                for key in table.foreign_keys
            ),
            key=lambda item: (item["column"], item["target"]),
        )
        contract[name]["enum_options"] = {
            column.name: dict(
                name=column.type.name,
                schema=column.type.schema,
                native_enum=column.type.native_enum,
                create_constraint=column.type.create_constraint,
                validate_strings=column.type.validate_strings,
            )
            for column in table.columns
            if hasattr(column.type, "enums")
        }
    return contract


def cancellation_contract(expected):
    """Allow only the intentional additive DeliveryStatus enum migration."""
    from copy import deepcopy

    result = deepcopy(expected)
    if "deliveries" in result:
        labels = result["deliveries"]["enums"]["status"]
        assert labels == [
            "PENDIENTE",
            "INICIADA",
            "EN_PICKUP",
            "EN_ROUTE",
            "EN_DESTINO",
            "COMPLETADA",
            "FALLIDA",
        ]
        labels.append("CANCELADA")
    return result


def declared_usd_contract(expected):
    """Permit only the five nullable unit columns of migration 20261114_explicit_usd."""
    from copy import deepcopy

    result = deepcopy(expected)
    changes = (
        ("financials", "currency_code", "USD", "\n\tid UUID"),
        ("riders", "wallet_currency", "USD", "\n\tid UUID"),
        ("orders", "currency_code", "USD", "\n\tsubtotal FLOAT"),
        ("payouts", "currency_code", "USD", "\n\tamount NUMERIC"),
        ("payout_status_history", "currency_code", None, "\n\tid UUID"),
    )
    for table, column, default, anchor in changes:
        if table not in result:
            continue
        data = result[table]
        assert data["ddl"].count(anchor) == 1
        assert column not in data["defaults"]
        data["ddl"] = data["ddl"].replace(
            anchor, "\n\t" + column + " VARCHAR(3), " + anchor, 1
        )
        data["defaults"][column] = [default, None]
    return exact_pricing_contract(result)


def exact_pricing_contract(expected):
    from copy import deepcopy

    result = deepcopy(expected)
    if "orders" in result:
        row = result["orders"]
        fields = (
            ("pricing_version", "INTEGER"),
            ("pricing_revision", "INTEGER"),
            ("subtotal_exact", "NUMERIC(10, 2)"),
            ("delivery_fee_exact", "NUMERIC(10, 2)"),
            ("total_exact", "NUMERIC(10, 2)"),
            ("items_exact", "JSON"),
        )
        addition = "".join("\n\t" + name + " " + kind + ", " for name, kind in fields)
        assert row["ddl"].count("\n\tpayment_method") == 1
        row["ddl"] = row["ddl"].replace(
            "\n\tpayment_method", addition + "\n\tpayment_method", 1
        )
        for name, _ in fields:
            assert name not in row["defaults"]
            row["defaults"][name] = [None, None]
    return result

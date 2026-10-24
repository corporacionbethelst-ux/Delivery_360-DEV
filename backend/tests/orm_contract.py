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

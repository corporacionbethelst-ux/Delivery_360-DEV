"""API identity, exact surface preservation and fresh-process startup fault tests."""

import importlib
import hashlib
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest
from fastapi import APIRouter

from app.main import app, create_app
from tests.api_surface_contract import api_surface

MODULES = (
    "auth",
    "orders",
    "riders",
    "telemetry",
    "tracking",
    "users",
    "roles",
    "audit",
    "settings",
    "deliveries",
    "alerts",
    "vehicles",
    "zones",
    "financial",
    "shifts",
    "reconciliation",
    "productivity",
    "routes",
    "dashboard",
    "integrations",
    "payouts",
    "wallet",
    "notifications",
    "fiscal",
    "currency",
)
ALIASES = (
    "deliveries",
    "shifts",
    "financial",
    "productivity",
    "routes",
    "dashboard",
    "alerts",
    "audit",
    "integrations",
    "users",
    "payouts",
)
PREVIOUS = Path(__file__).parent / "fixtures/api_surface_before_bootstrap.json"
RECONCILIATION = (
    Path(__file__).parent / "fixtures/api_surface_after_reconciliation.json"
)
PAYOUT_SURFACE = (
    Path(__file__).parent / "fixtures/api_surface_after_payout_pagination.json"
)
READINESS_SURFACE = Path(__file__).parent / "fixtures/api_surface_after_readiness.json"
FRAMEWORK_SURFACE = Path(__file__).parent / "fixtures/api_surface_after_framework.json"
EXPECTED = Path(__file__).parent / "fixtures/api_surface_after_delivery_catalog.json"
FRAMEWORK_DELTA = Path(__file__).parent / "fixtures/openapi_framework_delta.json"
BACKEND = Path(__file__).resolve().parents[1]


CURRENCY_PATHS = {
    "/api/v1/currency/context",
    "/api/v1/currency/rates",
    "/api/v1/currency/quotes",
    "/api/v1/currency/quotes/{quote_id}",
    "/api/v1/currency/orders/{order_id}/quotes",
    "/api/v1/currency/order-quotes/{quote_id}",
}


def before_currency_schema(application):
    schema = deepcopy(application.openapi())
    assert schema["components"]["schemas"].pop("OrderQuoteInput") == json.loads(
        (Path(__file__).parent / "fixtures/openapi_order_quote_input.json").read_text()
    )
    # Reverse only the reviewed prospective-price input changes. Every previous
    # route, dependency and unrelated schema remains pinned by historical hashes.
    delta = json.loads(
        (Path(__file__).parent / "fixtures/openapi_exact_prices_delta.json").read_text()
    )
    for change in delta:
        parent = schema
        for key in change["path"][:-1]:
            parent = parent[key]
        key = change["path"][-1]
        if "added" in change:
            assert parent.pop(key) == change["added"]
        elif "removed" in change:
            assert key not in parent
            parent[key] = change["removed"]
        else:
            assert parent[key] == change["after"]
            parent[key] = change["before"]
    unit = schema["components"]["schemas"]["PayoutRequestBody"]["properties"].pop(
        "currency"
    )
    assert unit == {
        "const": "USD",
        "enum": ["USD"],
        "type": "string",
        "title": "Currency",
        "default": "USD",
    }
    found = {key for key in schema["paths"] if key.startswith("/api/v1/currency/")}
    assert found == CURRENCY_PATHS
    for key in found:
        del schema["paths"][key]
    for key in ("BcvRateInput", "UsdVesQuoteInput"):
        del schema["components"]["schemas"][key]
    return schema


def surface_before_currency(application):
    current = api_surface(application)
    removed = [row for row in current["routes"] if row["path"] in CURRENCY_PATHS]
    assert len(removed) == 7
    current["routes"] = [
        row for row in current["routes"] if row["path"] not in CURRENCY_PATHS
    ]
    reachable = set()

    def visit(key):
        if key in reachable:
            return
        reachable.add(key)
        for child in current["dependencies"][key]["dependencies"]:
            visit(child)

    for row in current["routes"]:
        if "dependency_contract" in row:
            visit(row["dependency_contract"])
    current["dependencies"] = {
        key: value for key, value in current["dependencies"].items() if key in reachable
    }
    return current


def before_settings_schema(application=app):
    """Remove only the reviewed settings revision contract; pin all other fields."""
    schema = before_currency_schema(application)
    delta = Path(__file__).parent / "fixtures/openapi_bonus_simulation_delta.json"
    for change in json.loads(delta.read_text()):
        path = change["path"]
        assert path[:3] in [
            ["components", "schemas", "BonusSimulationRequest"],
            ["components", "schemas", "BonusSimulationResponse"],
        ] or path == ["paths", "/api/v1/settings/simulate-bonus", "post", "description"]
        parent = schema
        for key in path[:-1]:
            parent = parent[key]
        key = path[-1]
        assert (key in parent) == change["new_present"]
        if change["new_present"]:
            assert parent[key] == change["new"]
        if change["old_present"]:
            parent[key] = change["old"]
        else:
            del parent[key]
    response = schema["components"]["schemas"]["PlatformSettingsResponse"]
    assert response["properties"].pop("revision") == {
        "type": "string",
        "title": "Revision",
    }
    assert response.pop("required") == ["revision"]
    update = schema["components"]["schemas"]["PlatformSettingsUpdate"]
    assert update.pop("additionalProperties") is False
    for path in ("/api/v1/settings", "/api/v1/settings/"):
        for method in ("patch", "put"):
            assert schema["paths"][path][method].pop("parameters") == [
                {
                    "name": "if-match",
                    "in": "header",
                    "required": False,
                    "schema": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "title": "If-Match",
                    },
                }
            ]
    return schema


def surface_before_settings(application=app):
    current = surface_before_currency(application)
    canonical = json.dumps(
        before_settings_schema(application),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    current["openapi_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return current


def before_delivery_catalog_schema():
    schema = before_settings_schema()
    operation = schema["paths"].pop("/api/v1/deliveries/page")
    assert set(operation) == {"get"}
    assert schema["components"]["schemas"].pop("DeliveryStatus")["enum"] == [
        "PENDIENTE",
        "INICIADA",
        "EN_PICKUP",
        "EN_ROUTE",
        "EN_DESTINO",
        "COMPLETADA",
        "FALLIDA",
        "CANCELADA",
    ]
    return schema


def historical_surface():
    current = surface_before_currency(app)
    current["routes"] = [
        row for row in current["routes"] if row["path"] != "/api/v1/deliveries/page"
    ]
    reachable = set()

    def visit(key):
        if key in reachable:
            return
        reachable.add(key)
        for child in current["dependencies"][key]["dependencies"]:
            visit(child)

    for row in current["routes"]:
        if "dependency_contract" in row:
            visit(row["dependency_contract"])
    current["dependencies"] = {
        key: value for key, value in current["dependencies"].items() if key in reachable
    }
    canonical = json.dumps(
        before_delivery_catalog_schema(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    current["openapi_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return current


def test_delivery_catalog_preserves_every_previous_route_dependency_and_schema():
    assert historical_surface() == json.loads(FRAMEWORK_SURFACE.read_text())
    routes = api_surface(app)["routes"]
    paths = [row["path"] for row in routes]
    assert paths.index("/api/v1/deliveries/page") < paths.index(
        "/api/v1/deliveries/{delivery_id}"
    )


def before_framework_schema():
    schema = before_delivery_catalog_schema()
    for pointer, before, after in json.loads(FRAMEWORK_DELTA.read_text()):
        keys = pointer.lstrip("/").split("/")
        parent = schema
        for key in keys[:-1]:
            parent = parent[key]
        key = keys[-1]
        if after is None:
            assert key not in parent
        else:
            assert parent[key] == after
        if before is None:
            del parent[key]
        else:
            parent[key] = before
    return schema


def test_framework_changes_only_the_reviewed_schema_fields():
    previous = json.loads(READINESS_SURFACE.read_text())
    current = historical_surface()
    assert current["routes"] == previous["routes"]
    assert current["dependencies"] == previous["dependencies"]
    canonical = json.dumps(
        before_framework_schema(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == previous["openapi_sha256"]


def before_readiness_schema():
    schema = before_framework_schema()
    response = schema["paths"]["/health/ready"]["get"]["responses"].pop("503")
    assert response == {"description": "Database or Redis unavailable"}
    return schema


def test_readiness_only_adds_the_explicit_unavailable_response():
    previous = json.loads(PAYOUT_SURFACE.read_text())
    current = historical_surface()
    assert current["routes"] == previous["routes"]
    assert current["dependencies"] == previous["dependencies"]
    canonical = json.dumps(
        before_readiness_schema(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == previous["openapi_sha256"]


@pytest.mark.parametrize("name", MODULES)
def test_public_module_is_the_actual_imported_module(name):
    package = importlib.import_module("app.api.v1")
    canonical = importlib.import_module("app.api.v1." + name)
    exported = getattr(package, name)
    assert isinstance(exported, ModuleType)
    assert exported is canonical
    assert exported.__name__ == "app.api.v1." + name
    assert exported.__spec__ is not None
    assert isinstance(exported.router, APIRouter) and exported.router.routes


@pytest.mark.parametrize("name", ALIASES)
def test_compatibility_router_is_the_canonical_object(name):
    module = importlib.import_module("app.api.v1." + name)
    compatibility = importlib.import_module("app.api.v1.routers_combined")
    assert getattr(compatibility, name + "_router") is module.router


def test_exact_route_order_auth_dependencies_and_openapi_are_preserved():
    expected = json.loads(EXPECTED.read_text())
    assert len(expected["routes"]) == 204
    assert surface_before_settings() == expected


def test_reconciliation_addition_preserves_all_preexisting_routes_and_openapi():
    previous = json.loads(PREVIOUS.read_text())
    current = historical_surface()
    prefix = "/api/v1/reconciliation"
    assert [
        row
        for row in current["routes"]
        if not row["path"].startswith(prefix) and row["path"] != "/api/v1/payouts/page"
    ] == previous["routes"]
    assert all(
        current["dependencies"].get(key) == value
        for key, value in previous["dependencies"].items()
    )
    schema = before_readiness_schema()
    del schema["paths"]["/api/v1/payouts/page"]
    new_paths = {
        prefix + path
        for path in (
            "/wallet/{rider_id}",
            "/wallet/{rider_id}/sync",
            "/batch/daily",
            "/fix-all-discrepancies",
            "/audit/ledger-integrity",
        )
    }
    assert {path for path in schema["paths"] if path.startswith(prefix)} == new_paths
    for path in new_paths:
        del schema["paths"][path]
    for name in (
        "IntegrityIssue",
        "LedgerIntegrity",
        "CachePreview",
        "CacheSyncRequest",
        "CacheSyncResult",
        "CachePreviewPage",
        "LedgerAuditItem",
        "LedgerAuditPage",
        "RiderStatus",
    ):
        del schema["components"]["schemas"][name]
    canonical = json.dumps(
        schema, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == previous["openapi_sha256"]


def test_payout_pagination_preserves_existing_routes_dependencies_and_openapi():
    previous = json.loads(RECONCILIATION.read_text())
    current = historical_surface()
    path = "/api/v1/payouts/page"
    added = [row for row in current["routes"] if row["path"] == path]
    assert len(added) == 1 and added[0]["methods"] == ["GET"]
    assert [row for row in current["routes"] if row["path"] != path] == previous[
        "routes"
    ]
    assert all(
        current["dependencies"].get(key) == value
        for key, value in previous["dependencies"].items()
    )
    paths = [row["path"] for row in current["routes"]]
    assert paths.index(path) < paths.index("/api/v1/payouts/{payout_id}")
    schema = before_readiness_schema()
    del schema["paths"][path]
    canonical = json.dumps(
        schema, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == previous["openapi_sha256"]


def test_two_factories_have_identical_surfaces_without_duplicate_registration():
    first, second = create_app(), create_app()
    expected = json.loads(EXPECTED.read_text())
    assert surface_before_settings(first) == surface_before_settings(second) == expected
    # A separate factory must not mutate the module routers used by the first.
    assert first is not second


def test_compatibility_has_no_business_handlers_or_old_fallback_schemas():
    module = importlib.import_module("app.api.v1.routers_combined")
    assert set(module.__all__) == {name + "_router" for name in ALIASES}
    for name in (
        "start_delivery",
        "complete_delivery",
        "request_payout",
        "get_available_balance",
        "list_payouts",
        "list_deliveries",
        "get_audit_logs",
        "DeliveryProof",
        "PayoutRequestSchema",
        "checkin",
        "checkout",
        "_ensure_rider_scope",
    ):
        assert not hasattr(module, name)


def test_factory_does_not_open_database_connections_or_create_schema(monkeypatch):
    from app.main import engine, Base

    def forbidden(*args, **kwargs):
        raise AssertionError("Application composition attempted schema/data IO")

    monkeypatch.setattr(type(engine), "connect", forbidden)
    monkeypatch.setattr(type(engine), "begin", forbidden)
    monkeypatch.setattr(Base.metadata, "create_all", forbidden)
    assert surface_before_settings(create_app()) == json.loads(EXPECTED.read_text())


# Faults run in fresh interpreters: no reload of live modules, auth globals or
# sockets from the normal test app. Only class/module names leave the subprocess.
PROBE = r"""
import importlib, importlib.abc, importlib.util, json, sys
from fastapi import APIRouter
target, kind = sys.argv[1:]
fault_seen = False
class InvalidModule(importlib.abc.Loader):
    def create_module(self, spec): return None
    def exec_module(self, module):
        if kind == "empty_router": module.router = APIRouter()
        elif kind == "null_router": module.router = None
class Fault(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        global fault_seen
        if fullname != "app.api.v1." + globals()["target"]: return None
        fault_seen = True
        if kind == "missing":
            raise ModuleNotFoundError("required API unavailable", name=fullname)
        if kind == "transitive":
            raise ModuleNotFoundError("required vendor dependency unavailable", name="unavailable_vendor_dependency")
        if kind == "import_error": raise ImportError("required API initialization failed")
        return importlib.util.spec_from_loader(fullname, InvalidModule())
sys.meta_path.insert(0, Fault())
try:
    module = importlib.import_module("app.main")
except Exception as error:
    print(json.dumps({"initialized": False, "error": type(error).__name__, "missing": getattr(error, "name", None), "main_cached": "app.main" in sys.modules, "fault_seen": fault_seen}))
else:
    print(json.dumps({"initialized": True, "routes": len(module.app.routes)}))
"""


def probe(name, kind):
    result = subprocess.run(
        [sys.executable, "-c", PROBE, name, kind],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["initialized"] is False, (name, kind, data)
    assert data["main_cached"] is False
    assert data["fault_seen"] is True
    return data


@pytest.mark.parametrize("name", MODULES)
def test_missing_required_api_never_publishes_a_partial_application(name):
    data = probe(name, "missing")
    # Python's from-list import may wrap a missing submodule in ImportError.
    # The injected fault must be reached and the application must remain absent.
    assert data["error"] in ("ModuleNotFoundError", "ImportError")
    assert data["missing"] in ("app.api.v1." + name, "app.api.v1")


@pytest.mark.parametrize("name", ("payouts", "tracking", "notifications", "fiscal"))
@pytest.mark.parametrize("kind", ("transitive", "import_error"))
def test_initialization_failure_is_not_swallowed_as_an_optional_feature(name, kind):
    data = probe(name, kind)
    assert data["error"] == (
        "ModuleNotFoundError" if kind == "transitive" else "ImportError"
    )
    if kind == "transitive":
        assert data["missing"] == "unavailable_vendor_dependency"


@pytest.mark.parametrize("name", ("payouts", "tracking", "notifications", "fiscal"))
@pytest.mark.parametrize("kind", ("no_router", "empty_router", "null_router"))
def test_invalid_required_router_cannot_silently_remove_a_feature(name, kind):
    data = probe(name, kind)
    assert data["error"] == "RuntimeError"

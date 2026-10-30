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
EXPECTED = Path(__file__).parent / "fixtures/api_surface_after_reconciliation.json"
BACKEND = Path(__file__).resolve().parents[1]


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
    assert len(expected["routes"]) == 202
    assert api_surface(app) == expected


def test_reconciliation_addition_preserves_all_preexisting_routes_and_openapi():
    previous = json.loads(PREVIOUS.read_text())
    current = api_surface(app)
    prefix = "/api/v1/reconciliation"
    assert [
        row for row in current["routes"] if not row["path"].startswith(prefix)
    ] == previous["routes"]
    assert all(
        current["dependencies"].get(key) == value
        for key, value in previous["dependencies"].items()
    )
    schema = deepcopy(app.openapi())
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


def test_two_factories_have_identical_surfaces_without_duplicate_registration():
    first, second = create_app(), create_app()
    expected = json.loads(EXPECTED.read_text())
    assert api_surface(first) == api_surface(second) == expected
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
    assert api_surface(create_app()) == json.loads(EXPECTED.read_text())


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

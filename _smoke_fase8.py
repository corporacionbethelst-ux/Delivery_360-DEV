"""Smoke test Fase 8: arranque real de la app FastAPI + endpoints tracking + WS."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

from app.main import app  # noqa: E402


def show_routes():
    lines = []
    for r in app.routes:
        p = getattr(r, "path", "")
        if "tracking" in p or "/ws" in p:
            methods = ",".join(sorted(getattr(r, "methods", set()) or ["WS"]))
            lines.append(f"{methods:15s} {p}")
    print("\n".join(lines))


def openapi_check():
    try:
        spec = app.openapi()
        paths = [k for k in spec["paths"] if "tracking" in k]
        print("OPENAPI OK. tracking paths:", paths)
        return True
    except Exception as e:  # noqa: BLE001
        print("OPENAPI ERROR:", type(e).__name__, e)
        return False


def client_smoke():
    from fastapi.testclient import TestClient

    body = {
        "rider_id": "00000000-0000-0000-0000-000000000001",
        "latitude": 8.29,
        "longitude": -63.55,
    }
    with TestClient(app) as c:
        print("GET /health ->", c.get("/health").status_code)
        print("GET /docs ->", c.get("/docs").status_code)
        r = c.get("/api/v1/tracking/dashboard/active-riders")
        print("GET active-riders sin token ->", r.status_code)
        r = c.post("/api/v1/tracking/update-location", json=body)
        print("POST update-location sin token ->", r.status_code)
        r = c.get("/api/v1/tracking/live/00000000-0000-0000-0000-000000000001")
        print("GET live sin token ->", r.status_code)
    from fastapi.testclient import TestClient as TC
    with TC(app) as c:
        try:
            with c.websocket_connect("/api/v1/tracking/ws/all-riders?token=invalido") as ws:
                ws.send_json({"type": "ping"})
                print("WS msg:", ws.receive())
        except Exception as e:  # noqa: BLE001
            print("WS rechazado por JWT invalido (esperado):", type(e).__name__)


if __name__ == "__main__":
    show_routes()
    ok = openapi_check()
    client_smoke()
    sys.exit(0 if ok else 1)

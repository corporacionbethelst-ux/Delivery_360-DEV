"""Production fleet UI regression using local, intercepted synthetic reads only."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def vehicle(index, **changes):
    return {
        "id": f"123e4567-e89b-42d3-a456-{index:012d}",
        "edit_revision": "a" * 64,
        "plate": f"ABC-{index:03d}",
        "type": "MOTO",
        "model": "Moto de prueba",
        "color": "Azul",
        "year": 2026,
        "status": "ACTIVO",
        "insurance_expiry": None,
        "created_at": "2026-01-01T00:00:00Z",
        **changes,
    }


def zone(index):
    return {
        "id": f"123e4567-e89b-42d3-a456-{index + 100:012d}",
        "name": f"Centro {index}",
        "code": f"C{index}",
        "description": None,
        "delivery_fee_base": None if index == 1 else 0,
        "cost_per_km": 0,
        "estimated_time_min": 30,
        "is_priority": False,
        "is_active": index != 2,
        "color_hex": ["#3b82f6", "#a855f7", "#f97316"][index % 3],
        "riders_count": None if index == 1 else 0,
        "active_orders_count": None if index == 1 else 0,
        "created_at": "2026-01-01T00:00:00Z",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-fleet-browser")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    artifacts = Path(args.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    requests, writes, errors, checks = [], [], [], []
    state = {"failure": False}
    rows = [
        vehicle(1),
        vehicle(2, type="AUTO", status="MANTENIMIENTO"),
        vehicle(3, type="FUTURO", status="ESTADO_FUTURO", rider_id="actual-rider"),
    ]

    def passed(name):
        checks.append(name)
        print("passed: " + name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium, headless=True, args=["--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="es-VE",
            service_workers="block",
        )
        context.set_default_timeout(10000)
        context.add_cookies(
            [{"name": "auth-token", "value": "synthetic-token", "url": base}]
        )
        context.add_init_script("""localStorage.setItem('app_version', '1.2.1');
            localStorage.setItem('access_token', 'synthetic-token');
            localStorage.setItem('refresh_token', 'synthetic-refresh');""")
        context.route_web_socket("**/*", lambda socket: None)

        def intercept(route):
            target = urlparse(route.request.url)
            path, query = target.path, parse_qs(target.query)
            business = target.netloc != urlparse(base).netloc or path.startswith(
                "/api/v1/"
            )
            headers = {
                "access-control-allow-origin": base,
                "access-control-allow-headers": "authorization, content-type",
                "access-control-allow-methods": "GET, OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif business and route.request.method != "GET":
                writes.append({"path": path, "method": route.request.method})
                route.abort()
            elif path in ("/api/v1/vehicles", "/api/v1/zones"):
                requests.append({"path": path, "query": query})
                if path.endswith("vehicles") and state["failure"]:
                    route.fulfill(
                        status=503, json={"detail": "Fallo sintético"}, headers=headers
                    )
                    return
                data = (
                    [zone(i) for i in range(10)]
                    if path.endswith("zones")
                    else [
                        row
                        for row in rows
                        if ("type" not in query or row["type"] == query["type"][0])
                        and (
                            "search" not in query
                            or query["search"][0].lower() in row["plate"].lower()
                        )
                    ]
                )
                route.fulfill(json=data, headers=headers)
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "fleet-manager",
                        "email": "fleet@example.test",
                        "role": "GERENTE",
                        "is_active": True,
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    headers=headers,
                )
            elif business:
                route.fulfill(
                    json=[] if "alerts" in path else {"items": [], "unread_count": 0},
                    headers=headers,
                )
            else:
                route.continue_()

        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/manager/fleet/vehicles", wait_until="domcontentloaded")
        inventory = page.get_by_role(
            "region", name="Inventario de vehículos, desplazamiento horizontal"
        )
        expect(inventory).to_contain_text("ESTADO_FUTURO")
        expect(inventory).to_contain_text("Nombre de repartidor no informado")
        expect(inventory).to_contain_text("Fecha no informada")
        assert requests[-1]["query"]["limit"] == ["500"]
        passed("vehicle identities, unknown status and assigned names remain explicit")

        page.get_by_label("Buscar vehículos por placa, modelo o repartidor").fill(
            "ABC-001"
        )
        expect(inventory.get_by_role("row")).to_have_count(2)
        expect(
            page.get_by_text("Consulta cargada: tipo Todos; búsqueda ABC-001.")
        ).to_be_visible()
        state["failure"] = True
        page.get_by_role("button", name="Actualizar", exact=True).click()
        retry = page.get_by_role("button", name="Reintentar", exact=True)
        expect(retry).to_be_visible()
        expect(inventory).to_contain_text("ABC-001")
        state["failure"] = False
        retry.click()
        expect(retry).to_have_count(0)
        passed("server search and retry retain the last confirmed inventory")
        page.get_by_label("Buscar vehículos por placa, modelo o repartidor").fill("")
        expect(inventory.get_by_role("row")).to_have_count(4)
        expect(page.get_by_text("Fallo sintético", exact=True)).to_have_count(0)

        page.get_by_role("button", name="Acciones de vehículo ABC-001").click()
        page.get_by_role("menuitem", name="Dar de baja", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("ABC-001")
        dialog.get_by_role("button", name="Cancelar", exact=True).click()
        expect(dialog).to_have_count(0)
        page.screenshot(
            path=str(artifacts / "vehicles-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        passed("visible actions open the existing confirmation and allow cancellation")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        inventory.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "document.querySelector('[aria-label=\"Inventario de vehículos, desplazamiento horizontal\"]').scrollLeft > 0"
        )
        inventory.evaluate(
            "el => el.scrollIntoView({behavior:'instant',block:'start'})"
        )
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        page.screenshot(
            path=str(artifacts / "vehicles-mobile.png"), animations="disabled"
        )
        passed("mobile inventory remains bounded and scrolls from the keyboard")

        page.set_viewport_size({"width": 1440, "height": 1100})
        page.goto(base + "/manager/fleet/zones", wait_until="domcontentloaded")
        expect(page.get_by_role("article")).to_have_count(10)
        schematic = page.get_by_role("region", name="Vista esquemática de zonas")
        expect(schematic.get_by_role("link")).to_have_count(8)
        expect(
            page.get_by_role("article", name="Zona Centro 0", exact=True)
        ).to_contain_text("0,00 (moneda no informada)")
        missing = page.get_by_role("article", name="Zona Centro 1", exact=True)
        expect(missing).to_contain_text("Monto no informado")
        expect(missing.get_by_text("No informado", exact=True)).to_have_count(2)
        last = requests[-1]
        assert last["query"] == {"limit": ["100"], "page": ["1"]}
        count = len(requests)
        search = page.get_by_label("Buscar zonas por nombre o código")
        search.fill("C9")
        expect(page.get_by_role("article")).to_have_count(1)
        assert len(requests) == count
        search.fill("")
        page.screenshot(
            path=str(artifacts / "zones-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        passed(
            "zone search is local, schematic is bounded and missing values are faithful"
        )

        page.get_by_role("button", name="Nueva Zona", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("button", name="Crear Zona", exact=True).click()
        expect(dialog).to_contain_text("El nombre y el código son obligatorios.")
        dialog.get_by_label("Tarifa Base", exact=True).fill("0.75")
        expect(dialog.get_by_label("Tarifa Base", exact=True)).to_have_value("0.75")
        color = dialog.get_by_role("button", name="Color Violeta", exact=True)
        color.click()
        expect(color).to_have_attribute("aria-pressed", "true")
        page.set_viewport_size({"width": 390, "height": 844})
        box = dialog.bounding_box()
        assert box["x"] >= -1 and box["x"] + box["width"] <= 391
        assert box["height"] <= 844
        page.screenshot(
            path=str(artifacts / "zone-dialog-mobile.png"), animations="disabled"
        )
        dialog.get_by_role("button", name="Cancelar", exact=True).click()
        passed(
            "zone dialog preserves decimals and exposes named color selection on mobile"
        )

        page.goto(base + "/manager/fleet/vehicles/new", wait_until="domcontentloaded")
        expect(
            page.get_by_role("heading", name="Registrar Nuevo Vehículo")
        ).to_be_visible()
        page.get_by_label("Tipo de Vehículo *", exact=True).click()
        page.get_by_role("option", name=re.compile("Motocicleta")).click()
        page.get_by_role("button", name="Guardar Vehículo", exact=True).click()
        expect(
            page.get_by_role("alert").filter(has_text="La placa es requerida")
        ).to_be_visible()
        page.get_by_label("Placa / Patente *", exact=True).fill("DEM-076")
        year = page.get_by_label("Año *", exact=True)
        year.fill("2025.5")
        assert year.evaluate("el => el.validity.stepMismatch")
        year.fill("2026")
        expect(page.get_by_text("La placa es requerida", exact=True)).to_have_count(0)
        page.evaluate(
            "document.querySelector('main > div.overflow-auto').scrollTo({top:0,behavior:'instant'})"
        )
        page.screenshot(
            path=str(artifacts / "new-vehicle-mobile.png"), animations="disabled"
        )
        page.set_viewport_size({"width": 1440, "height": 1100})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right > 0"
        )
        page.evaluate(
            "document.querySelector('main > div.overflow-auto').scrollTo({top:0,behavior:'instant'})"
        )
        page.screenshot(
            path=str(artifacts / "new-vehicle-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        passed(
            "new vehicle keeps its fields, accessible type selection and local validation"
        )
        assert writes == [], writes
        assert errors == [], errors
        passed("zero business mutations and zero JavaScript exceptions")
        (artifacts / "results.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "requests": requests,
                    "writes": writes,
                    "errors": errors,
                },
                indent=2,
            )
            + "\n"
        )
        browser.close()


if __name__ == "__main__":
    main()

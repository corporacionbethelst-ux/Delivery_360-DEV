"""Exercise real Leaflet locally with synthetic riders and labeled test tiles."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-rider-map")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, reads, writes, errors = [], [], [], []
    state = {"failure": False, "empty": False, "tile_failure": False, "role": "GERENTE"}
    rows = [
        {
            "id": "rider-zero",
            "first_name": "José",
            "last_name": "Pérez",
            "email": "jose@example.test",
            "phone": "+58 (412) 123-4567",
            "status": "ACTIVO",
            "is_online": True,
            "last_lat": 0,
            "last_lng": 0,
            "last_location_at": "2026-11-08T12:00:00",
            "vehicle_ownership_type": "PROPIO",
            "vehicle_type": "MOTO",
            "vehicle_plate": "OWN-80",
        },
        {
            "id": "rider-offline",
            "first_name": "Ana",
            "last_name": "López",
            "status": "SUSPENDIDO",
            "is_online": False,
            "last_lat": 10.5,
            "last_lng": -66.9,
            "last_location_at": None,
            "vehicle_ownership_type": "EMPRESA",
            "vehicle_plate": "OLD-80",
            "assigned_vehicle_id": "v-80",
            "assigned_vehicle": {
                "id": "v-80",
                "plate": "ASSIGNED-80",
                "type": "AUTO",
                "model": "Modelo",
                "color": "Azul",
                "year": 2026,
            },
        },
        {
            "id": "rider-unknown",
            "last_lat": None,
            "last_lng": 9,
            "status": None,
            "is_online": None,
        },
        {
            "id": "rider-range",
            "first_name": "Fuera",
            "last_name": "de rango",
            "status": "INACTIVO",
            "is_online": False,
            "last_lat": 95,
            "last_lng": 0,
        },
        {
            "id": "rider-string",
            "first_name": "Cadena",
            "last_name": "numérica",
            "status": "PENDIENTE",
            "is_online": True,
            "last_lat": "0",
            "last_lng": 0,
        },
    ]
    tile = '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#edf4f7"/><path d="M0 64H256M0 192H256M64 0V256M192 0V256" stroke="#cedfe9" stroke-width="2"/><path d="M0 0L256 256M0 256L256 0" stroke="#dae8ee" stroke-width="1"/><text x="128" y="132" text-anchor="middle" fill="#849aa9" font-family="sans-serif" font-size="12">Prueba local · sin cartografía real</text></svg>'

    def passed(text):
        checks.append(text)
        print("passed:", text, flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1150},
            locale="es-VE",
            service_workers="block",
            reduced_motion="reduce",
        )
        context.set_default_timeout(15000)
        context.add_cookies(
            [{"name": "auth-token", "value": "synthetic-token", "url": base}]
        )
        context.add_init_script(
            "localStorage.setItem('app_version','1.2.1'); localStorage.setItem('access_token','synthetic-token'); localStorage.setItem('refresh_token','synthetic-refresh');"
        )
        context.route_web_socket("**/*", lambda socket: None)

        def intercept(route):
            target = urlparse(route.request.url)
            path = target.path
            business = (
                path.startswith("/api/v1/") or target.netloc != urlparse(base).netloc
            )
            headers = {
                "access-control-allow-origin": base,
                "access-control-allow-headers": "authorization,content-type",
                "access-control-allow-methods": "GET,OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif business and route.request.method != "GET":
                writes.append({"path": path, "method": route.request.method})
                route.abort()
            elif target.hostname and target.hostname.endswith(
                ".tile.openstreetmap.org"
            ):
                if state["tile_failure"]:
                    route.fulfill(status=503, body="synthetic tile error")
                else:
                    route.fulfill(status=200, content_type="image/svg+xml", body=tile)
            elif path == "/api/v1/riders":
                reads.append(path)
                route.fulfill(
                    status=503 if state["failure"] else 200,
                    json=(
                        {"detail": "Fallo sintético de ubicaciones"}
                        if state["failure"]
                        else [] if state["empty"] else rows
                    ),
                    headers=headers,
                )
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "manager-80",
                        "role": state["role"],
                        "is_active": True,
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "email": "manager@example.test",
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
        page.clock.install()
        page.on("pageerror", lambda error: errors.append(str(error)))
        url = base + "/manager/fleet/riders/map"
        page.goto(url, wait_until="domcontentloaded")
        content = page.locator("main main")
        cards = page.get_by_role("region", name="Tarjetas de repartidores", exact=True)
        map_region = page.get_by_role(
            "region", name="Mapa de ubicaciones registradas", exact=True
        )
        zero = cards.get_by_role("article", name="Repartidor rider-zero", exact=True)
        offline = cards.get_by_role(
            "article", name="Repartidor rider-offline", exact=True
        )
        unknown = cards.get_by_role(
            "article", name="Repartidor rider-unknown", exact=True
        )
        expect(zero).to_be_visible()
        automatic = page.get_by_role(
            "checkbox", name="Actualización automática (20 s)", exact=True
        )
        automatic.uncheck()
        markers = page.locator(".leaflet-marker-icon")
        expect(markers).to_have_count(2)
        expect(zero.get_by_text("0.000000, 0.000000", exact=True)).to_be_visible()
        expect(offline.get_by_text("Desconectado", exact=True)).to_be_visible()
        expect(offline.get_by_text("AUTO · ASSIGNED-80", exact=True)).to_be_visible()
        expect(cards.get_by_text("OLD-80", exact=False)).to_have_count(0)
        passed(
            "real Leaflet shows zero and offline coordinates, excludes missing/string/out-of-range values and preserves assigned vehicle identity"
        )

        expect(unknown.get_by_text("Estado no informado", exact=True)).to_be_visible()
        expect(
            unknown.get_by_text("Disponibilidad no informada", exact=True)
        ).to_be_visible()
        expect(
            unknown.get_by_role(
                "button", name="Centrar en mapa a Nombre no informado", exact=True
            )
        ).to_be_disabled()
        expect(
            unknown.get_by_role("link", name="Ver perfil de rider-unknown", exact=True)
        ).to_have_attribute("href", "/manager/fleet/riders/rider-unknown")
        passed(
            "unknown state, availability and location remain explicit while the actual profile link stays available"
        )

        zero.get_by_role(
            "button", name="Centrar en mapa a José Pérez", exact=True
        ).click()
        zero_marker = page.locator(
            '.leaflet-marker-icon[title="José Pérez · rider-zero"]'
        )
        container = page.locator(".leaflet-container")
        bounds, marker_bounds = container.bounding_box(), zero_marker.bounding_box()
        assert bounds and marker_bounds
        assert (
            abs(
                marker_bounds["x"]
                + marker_bounds["width"] / 2
                - bounds["x"]
                - bounds["width"] / 2
            )
            < 3
        )
        assert (
            abs(
                marker_bounds["y"]
                + marker_bounds["height"] / 2
                - bounds["y"]
                - bounds["height"] / 2
            )
            < 3
        )
        zero_marker.focus()
        zero_marker.press("Enter")
        expect(page.locator(".leaflet-popup")).to_contain_text("José Pérez")
        expect(page.locator(".leaflet-popup")).to_contain_text("Estado: Activo")
        expect(page.locator(".leaflet-popup")).to_contain_text("jose@example.test")
        expect(
            page.get_by_role("link", name="Llamar a José Pérez", exact=True)
        ).to_have_attribute("href", "tel:+584121234567")
        expect(
            page.locator(".leaflet-popup").get_by_role(
                "link", name="Ver perfil", exact=True
            )
        ).to_have_attribute("href", "/manager/fleet/riders/rider-zero")
        page.locator(".leaflet-popup-close-button").click()
        passed(
            "keyboard marker popup and list centering use the real zero position and expose native profile/telephone links"
        )

        search = page.get_by_role(
            "textbox", name="Buscar por nombre, contacto, placa o ID", exact=True
        )
        count = len(reads)
        search.fill("jose")
        expect(cards.get_by_role("article")).to_have_count(1)
        expect(markers).to_have_count(1)
        search.fill("ASSIGNED-80")
        expect(offline).to_be_visible()
        expect(markers).to_have_count(1)
        assert len(reads) == count
        search.fill("")
        page.get_by_role(
            "combobox", name="Conexión informada", exact=True
        ).select_option("UNKNOWN")
        expect(cards.get_by_role("article")).to_have_count(1)
        expect(markers).to_have_count(0)
        expect(
            page.get_by_text(
                "Sin coordenadas válidas en el filtro. Se muestra una vista mundial de referencia.",
                exact=True,
            )
        ).to_be_visible()
        page.get_by_role(
            "combobox", name="Conexión informada", exact=True
        ).select_option("ALL")
        page.get_by_role(
            "combobox", name="Estado registrado", exact=True
        ).select_option("SUSPENDIDO")
        expect(offline).to_be_visible()
        expect(markers).to_have_count(1)
        page.get_by_role(
            "combobox", name="Estado registrado", exact=True
        ).select_option("ALL")
        page.get_by_role(
            "combobox", name="Ubicación registrada", exact=True
        ).select_option("VALID")
        expect(cards.get_by_role("article")).to_have_count(2)
        assert len(reads) == count
        page.get_by_role(
            "combobox", name="Ubicación registrada", exact=True
        ).select_option("ALL")
        passed(
            "accent and assigned-plate search plus combined status/availability/location filters update actual markers without business reads"
        )

        page.get_by_role(
            "button", name="Ajustar a los puntos visibles", exact=True
        ).click()
        page.locator("main > div.overflow-auto").evaluate(
            "e => e.scrollTo({top:0,behavior:'instant'})"
        )
        page.screenshot(
            path=str(out / "rider-map-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        map_region.scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "rider-map-desktop-canvas.png"), animations="disabled"
        )
        confirmed = content.get_by_text(
            "Consulta confirmada:", exact=False
        ).inner_text()
        state["failure"] = True
        page.get_by_role("button", name="Actualizar ubicaciones", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text(
            "No se pudo consultar la ubicación de los repartidores."
        )
        expect(zero).to_be_visible()
        expect(markers).to_have_count(2)
        assert (
            content.get_by_text("Consulta confirmada:", exact=False).inner_text()
            == confirmed
        )
        state["failure"] = False
        with page.expect_response(
            lambda response: urlparse(response.url).path == "/api/v1/riders"
        ):
            page.get_by_role(
                "button", name="Reintentar ubicaciones", exact=True
            ).click()
        expect(
            page.get_by_role("button", name="Actualizar ubicaciones", exact=True)
        ).to_be_enabled()
        expect(content.get_by_role("alert")).to_have_count(0)
        passed(
            "failed refresh retains the last confirmed positions and timestamp and explicit retry recovers"
        )

        count = len(reads)
        page.clock.fast_forward(21000)
        assert len(reads) == count
        with page.expect_response(
            lambda response: urlparse(response.url).path == "/api/v1/riders"
        ):
            automatic.check()
        page.wait_for_function(
            "!document.querySelector('button:disabled') || !document.body.innerText.includes('Consultando ubicaciones…')"
        )
        expect(
            page.get_by_role("button", name="Actualizar ubicaciones", exact=True)
        ).to_be_enabled()
        assert len(reads) == count + 1, (count, len(reads))
        with page.expect_response(
            lambda response: urlparse(response.url).path == "/api/v1/riders"
        ):
            page.clock.fast_forward(21000)
        expect(
            page.get_by_role("button", name="Actualizar ubicaciones", exact=True)
        ).to_be_enabled()
        assert len(reads) == count + 2, (count, len(reads))
        automatic.uncheck()
        passed(
            "pausing stops scheduled reads and resuming restores the actual automatic query cycle"
        )

        state["tile_failure"] = True
        # Recreate Leaflet so the failure exercises a new provider request,
        # rather than a tile retained in the current layer's cache.
        page.reload(wait_until="domcontentloaded")
        expect(zero).to_be_visible()
        automatic.uncheck()
        expect(map_region.get_by_role("alert")).to_contain_text("fondo cartográfico")
        expect(markers).to_have_count(2)
        expect(zero.get_by_text("0.000000, 0.000000", exact=True)).to_be_visible()
        state["tile_failure"] = False
        page.get_by_role("button", name="Reintentar fondo del mapa", exact=True).click()
        expect(map_region.get_by_role("alert")).to_have_count(0)
        page.wait_for_function(
            "Array.from(document.querySelectorAll('.leaflet-tile')).some(image => image.complete && image.naturalWidth > 0)"
        )
        passed(
            "cartographic failure leaves actual markers and coordinates usable and supports retry"
        )

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.locator("main > div.overflow-auto").evaluate(
            "e => e.scrollTo({top:0,behavior:'instant'})"
        )
        page.screenshot(
            path=str(out / "rider-map-mobile-header.png"), animations="disabled"
        )
        map_region.scroll_into_view_if_needed()
        page.get_by_role(
            "button", name="Ajustar a los puntos visibles", exact=True
        ).click()
        map_bounds = container.bounding_box()
        assert map_bounds
        for marker in markers.all():
            box = marker.bounding_box()
            assert box
            assert (
                map_bounds["x"]
                <= box["x"]
                <= map_bounds["x"] + map_bounds["width"] - box["width"]
            )
            assert (
                map_bounds["y"]
                <= box["y"]
                <= map_bounds["y"] + map_bounds["height"] - box["height"]
            )
        page.screenshot(
            path=str(out / "rider-map-mobile-canvas.png"), animations="disabled"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        passed(
            "mobile keeps filters, scrollable list and real Leaflet canvas reachable without overlap or horizontal overflow"
        )

        state["empty"] = True
        page.get_by_role("button", name="Actualizar ubicaciones", exact=True).click()
        expect(
            cards.get_by_text("La consulta no devolvió repartidores.", exact=True)
        ).to_be_visible()
        expect(markers).to_have_count(0)
        expect(
            page.get_by_role("button", name="Ajustar a los puntos visibles", exact=True)
        ).to_be_disabled()
        passed(
            "confirmed empty catalog shows no fabricated riders, markers or regional center"
        )

        state["failure"] = True
        page.reload(wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_contain_text(
            "No se pudo consultar la ubicación de los repartidores."
        )
        expect(page.get_by_text("Sin consulta confirmada", exact=False)).to_be_visible()
        expect(page.locator(".leaflet-container")).to_have_count(0)
        expect(
            page.get_by_text("La consulta no devolvió repartidores.", exact=True)
        ).to_have_count(0)
        state["failure"] = False
        state["empty"] = False
        page.get_by_role("button", name="Reintentar ubicaciones", exact=True).click()
        expect(markers).to_have_count(2)
        passed(
            "initial failure remains distinct from confirmed emptiness and recovers without inventing a successful query time"
        )

        state["role"] = "OPERADOR"
        page.reload(wait_until="domcontentloaded")
        expect(zero).to_be_visible()
        expect(markers).to_have_count(2)
        passed(
            "operator retains read-only access to actual fleet positions and profile navigation"
        )
        assert not writes, writes
        assert not errors, errors
        passed("zero business mutations and zero JavaScript exceptions")
        (out / "results.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "reads": reads,
                    "writes": writes,
                    "errors": errors,
                    "basemap": "synthetic labeled test tiles; no external provider requests",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()


if __name__ == "__main__":
    main()

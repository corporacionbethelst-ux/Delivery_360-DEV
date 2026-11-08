"""Exercise the production delivery catalog using intercepted, synthetic reads.

Only local previews are accepted. Business traffic and WebSockets are intercepted;
mutations are rejected and reported. No credentials or production data are used.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

RIDER = "00000000-0000-0000-0000-000000000100"


def envelope(query):
    limit = int(query.get("limit", ["20"])[0])
    offset = int(query.get("offset", ["0"])[0])
    total = 0 if query.get("unassigned") == ["true"] else 45
    rider = query.get("rider_id", [RIDER])[0]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": f"delivery-{index}",
                "order_id": f"order-{index}",
                "external_id": None,
                "customer_name": "José Cliente",
                "rider_id": rider,
                "rider": {"id": rider, "first_name": "Ana", "last_name": "Rider"},
                "status": query.get("status", ["EN_ROUTE"])[0],
                "started_at": "2026-11-07T10:00:00",
                "completed_at": None,
                "total_time": 0,
                "sla_compliant": False,
            }
            for index in range(offset + 1, min(offset + limit, total) + 1)
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-delivery-catalog")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    artifacts = Path(args.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    requests, writes, errors, checks = [], [], [], []
    state = {"failure": False}

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
        context.add_init_script(
            """if (!localStorage.getItem('delivery-catalog-browser-initialized')) {
            localStorage.setItem('app_version', '1.2.1');
            localStorage.setItem('access_token', 'synthetic-token');
            localStorage.setItem('refresh_token', 'synthetic-refresh');
            localStorage.setItem('delivery-catalog-browser-initialized', 'yes'); }"""
        )
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
                writes.append(path)
                route.abort()
            elif path.endswith("/deliveries/page"):
                requests.append(query)
                route.fulfill(
                    status=503 if state["failure"] else 200,
                    json=(
                        {"detail": "Synthetic failure"}
                        if state["failure"]
                        else envelope(query)
                    ),
                    headers=headers,
                )
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "browser-manager",
                        "email": "catalog@example.test",
                        "role": "GERENTE",
                        "is_active": True,
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "created_at": "2026-11-01T00:00:00Z",
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
        page.goto(
            base + "/manager/operations/deliveries", wait_until="domcontentloaded"
        )
        confirmed = page.get_by_role("region", name="Consulta de entregas confirmada")
        expect(confirmed).to_contain_text("Total de la consulta: 45. Página 1: 20")
        row = page.get_by_role("row", name="Entrega delivery-1", exact=True)
        expect(row).to_contain_text("Referencia no informada")
        expect(row).to_contain_text("0 min")
        expect(row).to_contain_text("Fuera de SLA")
        expect(row.get_by_role("link")).to_have_attribute(
            "href", "/manager/operations/orders/order-1"
        )
        passed("actual identities, missing reference, zero duration and false SLA")

        search = page.get_by_label("Buscar solo en esta página")
        count = len(requests)
        search.fill("delivery-19")
        expect(
            page.get_by_role("row", name="Entrega delivery-19", exact=True)
        ).to_be_visible()
        expect(row).to_have_count(0)
        assert len(requests) == count
        search.fill("")
        passed("page-local search does not issue business requests")

        page.get_by_role("button", name="Siguiente", exact=True).click()
        expect(confirmed).to_contain_text("Página 2: 20")
        assert requests[-1] == {"limit": ["20"], "offset": ["20"]}
        expect(
            page.get_by_role("row", name="Entrega delivery-21", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Anterior", exact=True).click()
        expect(confirmed).to_contain_text("Página 1: 20")
        passed("confirmed server pagination uses exact offsets")

        page.get_by_label("Estado en el servidor").select_option("FALLIDA")
        expect(confirmed).to_contain_text("Todos los estados")
        state["failure"] = True
        page.get_by_role("button", name="Aplicar filtros", exact=True).click()
        retry = page.get_by_role("button", name="Reintentar consulta", exact=True)
        expect(retry).to_be_visible()
        expect(confirmed).to_contain_text("Todos los estados")
        expect(row).to_contain_text("En ruta")
        failed = requests[-1]
        state["failure"] = False
        retry.click()
        expect(confirmed).to_contain_text("estado Fallida")
        expect(row).to_contain_text("Fallida")
        assert requests[-1] == failed
        passed("failed filters preserve confirmed data and retry the exact request")

        page.get_by_label("Asignación en el servidor").select_option("unassigned")
        expect(page.get_by_label("ID repartidor (opcional)")).to_be_disabled()
        page.get_by_role("button", name="Aplicar filtros", exact=True).click()
        expect(confirmed).to_contain_text("Total de la consulta: 0")
        expect(
            page.get_by_text("No hay entregas en esta página de la consulta.")
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Siguiente", exact=True)
        ).to_be_disabled()
        passed("empty registered-delivery result is explicit, with no invented orders")

        page.get_by_role("button", name="Restablecer filtros", exact=True).click()
        expect(confirmed).to_contain_text("Total de la consulta: 45")
        page.screenshot(
            path=str(artifacts / "deliveries-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        expect(row).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        ), "The document overflows on mobile"
        assert page.get_by_role("table").evaluate(
            "table => table.parentElement.scrollWidth > table.parentElement.clientWidth"
        ), "Only the table should scroll horizontally"
        page.wait_for_function(
            """Array.from(document.querySelectorAll('form, select, input')).every(
            el => el.getBoundingClientRect().right <= innerWidth)"""
        )
        page.screenshot(
            path=str(artifacts / "deliveries-mobile.png"),
            full_page=False,
            animations="disabled",
        )
        passed("desktop and mobile render with table-local horizontal scrolling")
        scroll = page.get_by_role(
            "region", name="Tabla de entregas, desplazamiento horizontal", exact=True
        )
        scroll.focus()
        expect(scroll).to_be_focused()
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "document.querySelector('[aria-label=\"Tabla de entregas, desplazamiento horizontal\"]').scrollLeft > 0"
        )
        scroll.evaluate(
            "el => el.scrollIntoView({behavior: 'instant', block: 'start'})"
        )
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        page.screenshot(
            path=str(artifacts / "deliveries-mobile-table.png"),
            full_page=False,
            animations="disabled",
        )
        passed("delivery table supports horizontal scrolling from the keyboard")
        assert writes == [], writes
        assert errors == [], errors
        passed("zero business mutations and zero browser exceptions")
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

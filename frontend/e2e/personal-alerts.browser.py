"""Personal alert centers on a local build; synthetic reads and cancelled actions."""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-personal-alerts")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, reads, writes, errors = [], [], [], []
    state = {"failure": False, "invalid": False, "empty": False, "role": "GERENTE"}
    order_id = "123e4567-e89b-42d3-a456-000000000810"
    rider_id = "123e4567-e89b-42d3-a456-000000000811"
    rows = [
        {
            "id": f"personal-{index}",
            "type": "SLA_WARNING",
            "severity": "HIGH" if index == 0 else "LOW",
            "title": (
                "José requiere atención" if index == 0 else f"Alerta personal {index}"
            ),
            "description": "Revisar la entrega; lectura personal sin resolver la incidencia",
            "createdAt": "2026-11-08T12:00:00",
            "isRead": index == 1,
            "isDismissed": False,
            "status": "READ" if index == 1 else "UNREAD",
            "orderId": order_id if index == 0 else None,
            "riderId": rider_id if index == 0 else None,
        }
        for index in range(54)
    ]
    rows[1]["createdAt"] = "2099-11-08T12:00:00"
    rows[2].update(type="CUSTOM", severity="CUSTOM", createdAt="invalid")

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
            reduced_motion="reduce",
            service_workers="block",
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
            query = parse_qs(target.query)
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
            elif path == "/api/v1/alerts":
                reads.append(query)
                filtered = [
                    row
                    for row in rows
                    if query.get("status", ["ALL"])[0] == "ALL"
                    or row["status"] == query["status"][0]
                ]
                offset, limit = int(query.get("offset", [0])[0]), int(
                    query.get("limit", [50])[0]
                )
                body = (
                    {"detail": "Synthetic read error"}
                    if state["failure"]
                    else (
                        {"data": filtered}
                        if state["invalid"]
                        else [] if state["empty"] else filtered[offset : offset + limit]
                    )
                )
                route.fulfill(
                    status=503 if state["failure"] else 200, json=body, headers=headers
                )
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "staff-81",
                        "role": state["role"],
                        "is_active": True,
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "email": "staff@example.test",
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
        manager_url = base + "/manager/operations/alerts"
        page.goto(manager_url, wait_until="domcontentloaded")
        content = page.locator("main main")
        cards = page.get_by_role(
            "region", name="Alertas de la consulta confirmada", exact=True
        )
        first = cards.get_by_role("article", name="Alerta personal-0", exact=True)
        expect(first).to_be_visible()
        expect(cards.get_by_role("article")).to_have_count(50)
        expect(
            cards.get_by_role("article", name="Alerta personal-50", exact=True)
        ).to_have_count(0)
        assert reads[-1] == {"limit": ["51"], "offset": ["0"]}
        expect(
            page.get_by_text("El servidor no informa un total global.", exact=False)
        ).to_be_visible()
        expect(
            page.get_by_text("Tus notificaciones operacionales.", exact=False)
        ).to_contain_text("no resuelve")
        passed(
            "personal scope and operational disclaimer are explicit and 51-row lookahead displays only 50 actual records"
        )
        expect(
            first.get_by_role("link", name=f"Orden: {order_id}", exact=True)
        ).to_have_attribute("href", f"/manager/operations/orders/{order_id}")
        expect(
            first.get_by_role("link", name=f"Repartidor: {rider_id}", exact=True)
        ).to_have_attribute("href", f"/manager/fleet/riders/{rider_id}")
        passed("related order and rider links use their actual identifiers")

        search = page.get_by_role("textbox", name="Buscar en esta página", exact=True)
        severity = page.get_by_role(
            "combobox", name="Severidad en esta página", exact=True
        )
        count = len(reads)
        search.fill("jose")
        expect(cards.get_by_role("article")).to_have_count(1)
        severity.select_option("LOW")
        expect(cards.get_by_role("article")).to_have_count(0)
        expect(
            page.get_by_text(
                "No hay coincidencias en esta página. Ajusta los filtros locales.",
                exact=True,
            )
        ).to_be_visible()
        search.fill("")
        severity.select_option("UNKNOWN")
        unknown = cards.get_by_role("article", name="Alerta personal-2", exact=True)
        expect(unknown).to_be_visible()
        expect(
            unknown.get_by_text("Creada: Fecha no disponible", exact=True)
        ).to_be_visible()
        expect(unknown.get_by_text("CUSTOM", exact=True)).to_have_count(2)
        assert len(reads) == count
        severity.select_option("ALL")
        passed(
            "accent search and severity stay local and unknown severity/type/date are not assigned invented defaults"
        )
        expect(
            cards.get_by_role("article", name="Alerta personal-1", exact=True)
        ).to_contain_text("2099")
        expect(cards.get_by_text("Justo ahora", exact=True)).to_have_count(0)
        passed(
            "future timestamps retain the server date instead of claiming the alert just arrived"
        )
        page.screenshot(
            path=str(out / "alerts-desktop.png"), animations="disabled", full_page=True
        )

        page.get_by_role("button", name="Página siguiente", exact=True).click()
        expect(
            cards.get_by_role("article", name="Alerta personal-50", exact=True)
        ).to_be_visible()
        expect(cards.get_by_role("article")).to_have_count(4)
        assert reads[-1] == {"limit": ["51"], "offset": ["50"]}
        expect(
            page.get_by_role("button", name="Página siguiente", exact=True)
        ).to_be_disabled()
        page.get_by_role("button", name="Página anterior", exact=True).click()
        expect(first).to_be_visible()
        passed(
            "confirmed pagination uses offsets 0 and 50 and the lookahead controls next-page availability"
        )

        page.get_by_role("button", name="Leídas", exact=True).click()
        expect(cards.get_by_role("article")).to_have_count(1)
        expect(
            cards.get_by_role("article", name="Alerta personal-1", exact=True)
        ).to_be_visible()
        assert reads[-1] == {"status": ["READ"], "limit": ["51"], "offset": ["0"]}
        page.get_by_role("button", name="No leídas", exact=True).click()
        expect(first).to_be_visible()
        expect(
            cards.get_by_role("article", name="Alerta personal-1", exact=True)
        ).to_have_count(0)
        assert reads[-1] == {"status": ["UNREAD"], "limit": ["51"], "offset": ["0"]}
        page.get_by_role("button", name="Todas las alertas", exact=True).click()
        expect(
            cards.get_by_role("article", name="Alerta personal-1", exact=True)
        ).to_be_visible()
        passed(
            "read-state filters query the actual personal endpoint and restart from the first page"
        )

        before = cards.get_by_text("Consulta confirmada:", exact=False).inner_text()
        state["failure"] = True
        page.get_by_role("button", name="Leídas", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text("no se pudo confirmar")
        expect(first).to_be_visible()
        assert (
            cards.get_by_text("Consulta confirmada:", exact=False).inner_text()
            == before
        )
        expect(
            first.get_by_role("button", name="Marcar como leída", exact=True)
        ).to_be_disabled()
        expect(
            page.get_by_text(
                "La selección solicitada todavía no está confirmada.", exact=False
            )
        ).to_be_visible()
        state["failure"] = False
        page.get_by_role("button", name="Reintentar consulta", exact=True).click()
        expect(cards.get_by_role("article")).to_have_count(1)
        expect(
            cards.get_by_text("Consulta confirmada: Leídas", exact=False)
        ).to_be_visible()
        page.get_by_role("button", name="Todas las alertas", exact=True).click()
        expect(first).to_be_visible()
        passed(
            "failed query retains and labels its confirmed data and timestamp and retries the exact requested filter"
        )

        page.get_by_role("button", name="Leer todas mis alertas", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("incluidas otras páginas")
        expect(dialog).to_contain_text("filtros locales")
        expect(dialog).to_contain_text("no resuelve")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(out / "alerts-bulk-mobile.png"), animations="disabled")
        dialog.get_by_role("button", name="Cancelar", exact=True).click()
        assert not writes
        passed(
            "read-all confirmation states its full personal scope and cancelling sends no operation"
        )

        first.get_by_role("button", name="Descartar alerta", exact=True).click()
        expect(dialog).to_contain_text("José requiere atención")
        expect(dialog).to_contain_text("personal-0")
        expect(dialog).to_contain_text("No resuelve")
        assert dialog.evaluate("e => e.getBoundingClientRect().width <= innerWidth")
        page.screenshot(
            path=str(out / "alerts-dismiss-mobile.png"), animations="disabled"
        )
        dialog.get_by_role("button", name="Cancelar", exact=True).click()
        passed(
            "discard confirmation identifies the selected alert, fits mobile and cancels without deletion"
        )
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        page.locator("main > div.overflow-auto").evaluate(
            "e => e.scrollTo({top:0,behavior:'instant'})"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(out / "alerts-mobile.png"), animations="disabled")
        first.scroll_into_view_if_needed()
        page.screenshot(path=str(out / "alerts-card-mobile.png"), animations="disabled")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        passed(
            "mobile keeps filters, related IDs and explicit card actions within the viewport"
        )

        state["invalid"] = True
        page.reload(wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_be_visible()
        expect(cards).to_have_count(0)
        expect(
            page.get_by_text(
                "La página consultada no contiene alertas visibles.", exact=True
            )
        ).to_have_count(0)
        expect(
            page.get_by_role("button", name="Leer todas mis alertas", exact=True)
        ).to_be_disabled()
        state["invalid"] = False
        page.get_by_role("button", name="Reintentar consulta", exact=True).click()
        expect(first).to_be_visible()
        passed(
            "malformed initial data does not masquerade as an empty inbox and explicit retry restores the confirmed page"
        )
        state["empty"] = True
        page.get_by_role("button", name="Actualizar", exact=True).click()
        expect(
            cards.get_by_text(
                "La página consultada no contiene alertas visibles.", exact=True
            )
        ).to_be_visible()
        expect(cards.get_by_role("article")).to_have_count(0)
        passed(
            "confirmed empty results describe only the requested page without claiming all operational incidents are resolved"
        )

        state["empty"] = False
        state["role"] = "OPERADOR"
        page.goto(base + "/operator/alerts", wait_until="domcontentloaded")
        expect(first).to_be_visible()
        expect(
            page.get_by_role("link", name="Volver al panel", exact=True)
        ).to_have_attribute("href", "/operator")
        expect(
            first.get_by_role("link", name=f"Orden: {order_id}", exact=True)
        ).to_have_attribute("href", f"/operator/orders/{order_id}")
        passed(
            "operator uses the same reliable personal center with its own navigation targets"
        )
        assert not writes, writes
        assert not errors, errors
        passed("zero business mutations and zero JavaScript exceptions")
        (out / "results.json").write_text(
            json.dumps(
                {"checks": checks, "reads": reads, "writes": writes, "errors": errors},
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()


if __name__ == "__main__":
    main()

"""Verify the local audit catalog and an actual CSV download with synthetic data.

Requires Playwright Python and Chromium. All business HTTP/WebSocket traffic is
intercepted. Refuses remote previews; never makes real payments or mutations.
"""

import argparse
import csv
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect


def summary(index, query):
    return dict(
        rider_id=f"rider-{index}",
        user_id=f"actual-user-{index}",
        full_name="=SUM(1,1)" if index == 50 else f"José Rider {index}",
        email="rider@example.test",
        phone="+584121234567",
        status=query.get("status_filter", ["ACTIVO"])[0],
        is_online=(
            query["is_online"][0] == "true"
            if "is_online" in query
            else None if index == 1 else bool(index % 2)
        ),
        vehicle_type=None,
        vehicle_plate=f"PLACA-{index}",
        operating_zone='José, "Centro"\nSector',
        zone_id=None,
        current_order_id=None,
        orders_assigned=9,
        orders_delivered=3,
        orders_active=4,
        deliveries_total=8,
        deliveries_completed=3,
        deliveries_failed=1,
        deliveries_in_progress=2,
        sla_compliant=4,
        sla_compliance_rate=50,
        total_earned=0,
        pending_payouts=0,
        available_to_payout=0,
        last_lat=0,
        last_lng=0,
        last_location_at="2026-11-07T08:00:00-04:00",
    )


def envelope(query):
    offset, limit = int(query.get("offset", ["0"])[0]), int(
        query.get("limit", ["51"])[0]
    )
    rows = [summary(index, query) for index in range(offset, min(offset + limit, 73))]
    return dict(items=rows, total=len(rows), limit=limit, offset=offset)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3071")
    parser.add_argument(
        "--artifacts-dir", default="/tmp/delivery360-audit-catalog-browser"
    )
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    artifacts = Path(args.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    requests, writes, errors, downloads, checks = [], [], [], [], []
    state = {"mode": "normal", "pending": None}

    def passed(name):
        checks.append(name)
        print("passed: " + name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium, headless=True, args=["--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            accept_downloads=True,
            locale="es-VE",
            service_workers="block",
        )
        context.set_default_timeout(10000)
        context.add_cookies(
            [{"name": "auth-token", "value": "synthetic-token", "url": base}]
        )
        context.add_init_script(
            """if (!localStorage.getItem('audit-catalog-browser-initialized')) {
          localStorage.setItem('app_version', '1.2.1'); localStorage.setItem('access_token', 'synthetic-token');
          localStorage.setItem('refresh_token', 'synthetic-refresh'); localStorage.setItem('audit-catalog-browser-initialized', 'yes'); }"""
        )
        context.route_web_socket("**/*", lambda socket: None)

        def intercept(route):
            target = urlparse(route.request.url)
            path, query = target.path, parse_qs(target.query)
            headers = {
                "access-control-allow-origin": base,
                "access-control-allow-headers": "authorization, content-type",
                "access-control-allow-methods": "GET, OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif (
                target.netloc != urlparse(base).netloc or path.startswith("/api/v1/")
            ) and path.endswith(
                (
                    "/riders/audit/summary",
                    "/orders",
                    "/deliveries",
                    "/financial/transactions",
                )
            ):
                requests.append(
                    {"path": path, "query": query, "method": route.request.method}
                )
                if route.request.method != "GET":
                    writes.append(path)
                    route.abort()
                    return
                catalog = path.endswith("/riders/audit/summary") and query.get(
                    "limit"
                ) == ["51"]
                if catalog and state["mode"] == "failure":
                    route.fulfill(
                        status=503,
                        json={"detail": "Synthetic failure"},
                        headers=headers,
                    )
                elif catalog and state["mode"] == "defer":
                    state["pending"] = (route, query, headers)
                elif path.endswith("/riders/audit/summary"):
                    route.fulfill(json=envelope(query), headers=headers)
                elif path.endswith("/deliveries"):
                    route.fulfill(
                        json={"items": [], "total": 0, "limit": 51, "offset": 0},
                        headers=headers,
                    )
                else:
                    route.fulfill(json=[], headers=headers)
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "browser-user",
                        "email": "catalog@example.test",
                        "role": "GERENTE",
                        "is_active": True,
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "created_at": "2026-11-01T00:00:00Z",
                    },
                    headers=headers,
                )
            elif path.startswith("/api/v1/"):
                if route.request.method != "GET":
                    writes.append(path)
                route.fulfill(
                    json=[] if "alerts" in path else {"items": [], "unread_count": 0},
                    headers=headers,
                )
            elif route.request.url.startswith(base + "/"):
                route.continue_()
            else:
                if route.request.method != "GET":
                    writes.append(path)
                route.fulfill(
                    json=[] if "alerts" in path else {"items": [], "unread_count": 0},
                    headers=headers,
                )

        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("download", lambda download: downloads.append(download))
        catalog_url = base + "/manager/operations/rider-audit"
        page.goto(catalog_url, wait_until="domcontentloaded")
        confirmed = page.get_by_role("region", name="Página de auditoría confirmada")
        expect(confirmed).to_be_visible()
        expect(page.get_by_role("article")).to_have_count(50)
        expect(
            page.get_by_role("article", name="Auditoría de rider-50", exact=True)
        ).to_have_count(0)
        expect(page.get_by_text("24 · 1 sin información", exact=True)).to_be_visible()
        assert requests[-1]["query"] == {"limit": ["51"], "offset": ["0"]}
        assert "COP" not in confirmed.inner_text() and "$" not in confirmed.inner_text()
        passed("bounded_first_page_unknown_availability_and_scoped_metrics")

        page.get_by_role("button", name="Siguiente", exact=True).click()
        expect(
            page.get_by_role("article", name="Auditoría de rider-50", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Siguiente", exact=True)
        ).to_be_disabled()
        count = len(requests)
        page.get_by_label("Buscar solo en esta página", exact=True).fill("rider-50")
        expect(page.get_by_role("article")).to_have_count(1)
        with page.expect_download() as event:
            page.get_by_role("button", name="Exportar página CSV", exact=True).click()
        download = event.value
        csv_path = artifacts / "auditoria-pagina-verificada.csv"
        download.save_as(str(csv_path))
        rows = list(
            csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8-sig")))
        )
        assert len(requests) == count and len(rows) == 1
        row = rows[0]
        assert row["id_rider"] == "rider-50" and row["id_usuario"] == "actual-user-50"
        assert row["nombre"] == "'=SUM(1,1)" and row["telefono"].startswith("'+58412")
        assert row["zona"] == 'José, "Centro"\nSector'
        assert (
            row["online"] == "false"
            and row["creditos_procesado"] == "0"
            and row["moneda"] == ""
        )
        assert (
            row["latitud"] == "0"
            and row["longitud"] == "0"
            and row["id_orden_actual"] == ""
        )
        assert row["ubicacion_fecha_utc"] == "2026-11-07T12:00:00.000Z"
        assert (
            row["desplazamiento_consulta"] == "50"
            and row["busqueda_local"] == "rider-50"
        )
        assert (
            "no es el catálogo completo" in row["alcance"]
            and "pagina_2_1_filas" in download.suggested_filename
        )
        passed(
            "actual_page_csv_contains_identity_zero_missing_values_utc_and_safe_text"
        )

        state["mode"] = "failure"
        page.get_by_label("Estado en el servidor", exact=True).select_option("INACTIVO")
        expect(
            page.get_by_role("alert").filter(has_text="No se pudo comprobar")
        ).to_be_visible()
        expect(
            page.get_by_text(
                "Consulta confirmada: estado ALL; disponibilidad Todos.", exact=True
            )
        ).to_be_visible()
        expect(page.get_by_role("button", name="Exportar página CSV")).to_be_disabled()
        expect(
            page.get_by_role("article", name="Auditoría de rider-50", exact=True)
        ).to_be_visible()
        state["mode"] = "normal"
        page.get_by_role("button", name="Reintentar consulta").click()
        expect(
            page.get_by_text(
                "Consulta confirmada: estado INACTIVO; disponibilidad Todos.",
                exact=True,
            )
        ).to_be_visible()
        expect(
            page.get_by_text("Sin coincidencias en esta página.", exact=False)
        ).to_be_visible()
        page.get_by_label("Buscar solo en esta página", exact=True).fill("")
        page.get_by_label("Disponibilidad en el servidor", exact=True).select_option(
            "false"
        )
        expect(
            page.get_by_text(
                "Consulta confirmada: estado INACTIVO; disponibilidad Offline.",
                exact=True,
            )
        ).to_be_visible()
        assert requests[-1]["query"] == {
            "status_filter": ["INACTIVO"],
            "is_online": ["false"],
            "limit": ["51"],
            "offset": ["0"],
        }
        passed("failed_filter_keeps_confirmed_page_and_retry_uses_exact_server_filters")

        state["mode"] = "defer"
        page.get_by_label("Estado en el servidor", exact=True).select_option(
            "SUSPENDIDO"
        )
        expect(confirmed).to_have_attribute("aria-busy", "true")
        expect(page.get_by_role("button", name="Exportar página CSV")).to_be_disabled()
        old = state["pending"]
        state["mode"] = "normal"
        page.get_by_label("Disponibilidad en el servidor", exact=True).select_option(
            "true"
        )
        expect(
            page.get_by_text(
                "Consulta confirmada: estado SUSPENDIDO; disponibilidad Online.",
                exact=True,
            )
        ).to_be_visible()
        old[0].fulfill(json=envelope(old[1]), headers=old[2])
        page.wait_for_timeout(150)
        expect(
            page.get_by_text(
                "Consulta confirmada: estado SUSPENDIDO; disponibilidad Online.",
                exact=True,
            )
        ).to_be_visible()
        expect(page.get_by_role("button", name="Exportar página CSV")).to_be_enabled()
        page.screenshot(
            path=str(artifacts / "audit-catalog-desktop.png"), full_page=True
        )
        passed("rapid_filters_combine_and_old_response_cannot_replace_new_query")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for label in (
            "Buscar solo en esta página",
            "Estado en el servidor",
            "Disponibilidad en el servidor",
        ):
            box = page.get_by_label(label, exact=True).bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= 390
        page.screenshot(
            path=str(artifacts / "audit-catalog-mobile.png"), full_page=True
        )
        passed("mobile_filters_and_cards_fit_viewport")

        state["mode"] = "defer"
        page.get_by_role("button", name="Actualizar consulta").click()
        expect(confirmed).to_have_attribute("aria-busy", "true")
        old = state["pending"]
        state["mode"] = "normal"
        page.get_by_role("link", name="Ver auditoría de rider-0", exact=True).click()
        expect(
            page.get_by_text(
                "Repartidor de la consulta confirmada: rider-0", exact=True
            )
        ).to_be_visible()
        old[0].fulfill(json=envelope(old[1]), headers=old[2])
        page.wait_for_timeout(150)
        expect(
            page.get_by_role("region", name="Página de auditoría confirmada")
        ).to_have_count(0)
        assert len(downloads) == 1
        page.get_by_role("link", name="Volver al catálogo de auditoría").click()
        expect(confirmed).to_be_visible()
        expect(
            page.get_by_text(
                "Consulta confirmada: estado ALL; disponibilidad Todos.", exact=True
            )
        ).to_be_visible()
        expect(
            page.get_by_label("Buscar solo en esta página", exact=True)
        ).to_have_value("")
        passed("actual_detail_link_and_retired_catalog_read_do_not_leak_old_state")

        state["mode"] = "defer"
        page.get_by_role("button", name="Actualizar consulta").click()
        expect(confirmed).to_have_attribute("aria-busy", "true")
        page.evaluate("window.dispatchEvent(new Event('delivery360-session-expired'))")
        page.wait_for_url("**/login")
        pending = state["pending"]
        pending[0].fulfill(json=envelope(pending[1]), headers=pending[2])
        page.wait_for_timeout(150)
        assert page.evaluate("localStorage.getItem('access_token')") is None
        expect(page.get_by_role("article")).to_have_count(0)
        assert len(downloads) == 1 and not writes and not errors
        passed("logout_retires_late_private_page_and_prevents_another_csv")
        (artifacts / "browser-results.json").write_text(
            json.dumps(
                {
                    "checks_passed": checks,
                    "business_requests": requests,
                    "downloads": len(downloads),
                    "write_requests": writes,
                    "page_errors": errors,
                },
                indent=2,
            )
            + "\n"
        )
        print(
            json.dumps(
                {
                    "checks_passed": len(checks),
                    "business_requests": len(requests),
                    "downloads": len(downloads),
                    "write_requests": len(writes),
                    "page_errors": errors,
                }
            ),
            flush=True,
        )
        browser.close()


if __name__ == "__main__":
    main()

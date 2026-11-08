"""Test the local audit production build with synthetic, intercepted business data.

Requires Playwright Python and Chromium. Refuses remote preview URLs. All business
HTTP/WebSocket traffic is intercepted; no payments or production mutations.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect


def summary(rider="rider-1"):
    return dict(
        rider_id=rider,
        user_id="user-" + rider,
        full_name="Rider dos" if rider == "rider-2" else "José Rider",
        email="rider@example.test",
        status="ACTIVO",
        is_online=False,
        orders_assigned=73,
        orders_delivered=30,
        orders_active=20,
        deliveries_total=73,
        deliveries_completed=30,
        deliveries_failed=1,
        deliveries_in_progress=20,
        sla_compliant=0,
        sla_compliance_rate=0,
        total_earned=0,
        pending_payouts=0,
        available_to_payout=0,
        last_lat=0,
        last_lng=0,
        last_location_at="2026-11-07T12:00:00",
    )


def summary_page(query):
    limit, offset = int(query.get("limit", ["100"])[0]), int(
        query.get("offset", ["0"])[0]
    )
    rows = [summary("rider-1"), summary("rider-2")]
    if limit == 100 and offset == 0:
        rows = [summary(f"other-{i}") for i in range(100)]
    return dict(items=rows, limit=limit, offset=offset, total=len(rows))


def order(index, rider):
    return dict(
        id=f"o-{index}",
        external_id=f"EXT-{index}",
        assigned_rider_id=rider,
        rider_id=rider,
        status="ASIGNADO",
        customer_name="Ana",
        total=0,
        created_at="2026-11-07T12:00:00",
    )


def delivery(index, rider):
    return dict(
        id=f"d-{index}",
        order_id=f"o-{index}",
        rider_id=rider,
        status="COMPLETADA",
        locked_bonus_amount=0,
        customer_name="Ana",
        created_at="2026-11-07T12:00:00",
        updated_at=None,
    )


def transaction(index, rider):
    return dict(
        id=f"tx-{index}",
        rider_id=rider,
        type="RETIRO",
        transaction_type="RETIRO",
        status="PROCESADO",
        amount=25,
        description="Retiro registrado",
        balance_before=0,
        balance_after=None,
        created_at="2026-11-07T12:00:00",
    )


def batch(path, query):
    rider = query.get("rider_id", ["rider-1"])[0]
    offset = int(query.get("offset", ["0"])[0])
    indexes = range(offset, min(offset + 51, 73))
    if path.endswith("/orders"):
        return [order(i, rider) for i in indexes]
    if path.endswith("/transactions"):
        return [transaction(i, rider) for i in indexes]
    rows = [delivery(i, rider) for i in indexes]
    if offset == 0:
        rows.append(
            dict(
                id="order-support",
                order_id="support",
                rider_id=rider,
                status="COMPLETADA",
            )
        )
    return dict(items=rows, total=74 if offset == 0 else 73, limit=51, offset=offset)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3070")
    parser.add_argument(
        "--artifacts-dir", default="/tmp/delivery360-rider-audit-browser"
    )
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    artifacts = Path(args.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    requests, writes, errors, checks = [], [], [], []
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
            locale="es-VE",
            service_workers="block",
        )
        context.set_default_timeout(10000)
        context.add_cookies(
            [{"name": "auth-token", "value": "synthetic-token", "url": base}]
        )
        context.add_init_script(
            """if (!localStorage.getItem('audit-browser-initialized')) {
          localStorage.setItem('app_version', '1.2.1'); localStorage.setItem('access_token', 'synthetic-token');
          localStorage.setItem('refresh_token', 'synthetic-refresh'); localStorage.setItem('audit-browser-initialized', 'yes'); }"""
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
                elif state["mode"] == "failure" and path.endswith("/deliveries"):
                    route.fulfill(
                        status=503,
                        json={"detail": "Synthetic failure"},
                        headers=headers,
                    )
                elif (
                    state["mode"] == "defer_summary"
                    and path.endswith("/riders/audit/summary")
                    and query.get("limit") == ["100"]
                    and query.get("offset") == ["0"]
                ):
                    state["pending"] = (route, query, headers)
                else:
                    data = (
                        summary_page(query)
                        if path.endswith("/riders/audit/summary")
                        else batch(path, query)
                    )
                    if state["mode"] == "wrong_rider" and path.endswith("/orders"):
                        data[0]["rider_id"] = "another-rider"
                        data[0]["assigned_rider_id"] = "another-rider"
                    route.fulfill(json=data, headers=headers)
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "browser-user",
                        "email": "audit@example.test",
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
        detail = base + "/manager/operations/rider-audit/rider-1"
        page.goto(detail, wait_until="domcontentloaded")
        confirmed = page.get_by_role("region", name="Auditoría confirmada")
        expect(confirmed).to_be_visible()
        expect(page.get_by_text("José Rider", exact=True)).to_be_visible()
        expect(page.get_by_text("0, 0", exact=True)).to_be_visible()
        expect(
            page.get_by_role("link", name="Ver orden o-49", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("link", name="Ver orden o-50", exact=True)
        ).to_have_count(0)
        assert (
            "COP" not in confirmed.inner_text() and "+25" not in confirmed.inner_text()
        )
        assert any(
            r["path"].endswith("/riders/audit/summary")
            and r["query"].get("offset") == ["100"]
            for r in requests
        )
        expect(
            page.get_by_role("link", name="Ver orden de apoyo support", exact=True)
        ).to_have_attribute("href", "/manager/operations/orders/support")
        expect(
            page.get_by_role("region", name="Entregas registradas del repartidor")
        ).to_contain_text("50 filas cargadas")
        page.screenshot(
            path=str(artifacts / "rider-audit-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        passed(
            "bounded_first_pages_second_summary_page_zero_values_and_separate_fallback"
        )

        for title, marker in [
            ("Órdenes del repartidor", "o-50"),
            ("Entregas registradas del repartidor", "d-50"),
            ("Transacciones del repartidor", "tx-50"),
        ]:
            panel = page.get_by_role("region", name=title, exact=True)
            panel.get_by_role("button", name="Siguiente", exact=True).click()
            expect(panel).to_contain_text(marker)
            expect(
                panel.get_by_role("button", name="Siguiente", exact=True)
            ).to_be_disabled()
            expect(panel).to_contain_text("23 filas cargadas en la página 2.")
        expect(
            page.get_by_text("Vuelve al inicio para consultar este bloque.", exact=True)
        ).to_be_visible()
        passed("independent_offsets_and_real_end_of_each_table")

        state["mode"] = "failure"
        page.get_by_role("button", name="Actualizar auditoría").click()
        expect(
            page.get_by_role("alert").filter(has_text="No se pudo comprobar")
        ).to_be_visible()
        expect(
            page.get_by_role("link", name="Ver orden o-50", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("link", name="Ver transacción tx-50", exact=True)
        ).to_be_visible()
        state["mode"] = "normal"
        page.get_by_role("button", name="Reintentar auditoría").click()
        expect(
            page.get_by_role("alert").filter(has_text="No se pudo comprobar")
        ).to_have_count(0)
        expect(confirmed).to_have_attribute("aria-busy", "false")
        assert all(
            r["query"].get("offset") == ["50"]
            for r in requests[-5:]
            if not r["path"].endswith("/riders/audit/summary")
        )
        passed("failed_block_keeps_complete_confirmed_set_and_exact_retry")

        state["mode"] = "wrong_rider"
        page.get_by_role("button", name="Actualizar auditoría").click()
        expect(
            page.get_by_role("alert").filter(has_text="No se pudo comprobar")
        ).to_be_visible()
        expect(
            page.get_by_text(
                "Repartidor de la consulta confirmada: rider-1", exact=True
            )
        ).to_be_visible()
        state["mode"] = "normal"
        page.get_by_role("button", name="Volver al inicio", exact=True).click()
        expect(
            page.get_by_role("link", name="Ver orden o-0", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("link", name="Ver orden de apoyo support", exact=True)
        ).to_be_visible()
        passed("wrong_rider_rejected_and_explicit_restart_recovers")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_role(
            "heading", name="Detalle de auditoría de repartidor"
        ).scroll_into_view_if_needed()
        page.screenshot(
            path=str(artifacts / "rider-audit-mobile.png"),
            full_page=False,
            animations="disabled",
        )
        passed("mobile_content_fits_with_locally_scrollable_tables")

        state["mode"] = "defer_summary"
        page.get_by_role("button", name="Actualizar auditoría").click()
        expect(confirmed).to_have_attribute("aria-busy", "true")
        old = state["pending"]
        state["mode"] = "normal"
        page.get_by_role("link", name="Volver al catálogo de auditoría").click()
        expect(page.get_by_text("Rider dos", exact=True)).to_be_visible()
        page.get_by_role("link", name="Ver auditoría de rider-2", exact=True).click()
        expect(
            page.get_by_text(
                "Repartidor de la consulta confirmada: rider-2", exact=True
            )
        ).to_be_visible()
        count = len(requests)
        old[0].fulfill(json=summary_page(old[1]), headers=old[2])
        page.wait_for_timeout(150)
        assert len(requests) == count
        expect(
            page.get_by_text(
                "Repartidor de la consulta confirmada: rider-1", exact=True
            )
        ).to_have_count(0)
        passed("retired_route_cannot_continue_summary_scan_or_replace_next_rider")

        state["mode"] = "defer_summary"
        page.get_by_role("button", name="Actualizar auditoría").click()
        expect(
            page.get_by_role("region", name="Auditoría confirmada")
        ).to_have_attribute("aria-busy", "true")
        page.evaluate("window.dispatchEvent(new Event('delivery360-session-expired'))")
        page.wait_for_url("**/login")
        pending = state["pending"]
        count = len(requests)
        pending[0].fulfill(json=summary_page(pending[1]), headers=pending[2])
        page.wait_for_timeout(150)
        assert (
            len(requests) == count
            and page.evaluate("localStorage.getItem('access_token')") is None
        )
        expect(page.get_by_role("region", name="Auditoría confirmada")).to_have_count(0)
        assert not writes and not errors
        passed("logout_prevents_late_snapshot_and_additional_summary_pages")
        (artifacts / "browser-results.json").write_text(
            json.dumps(
                {
                    "checks_passed": checks,
                    "audit_requests": requests,
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
                    "audit_requests": len(requests),
                    "write_requests": len(writes),
                    "page_errors": errors,
                }
            ),
            flush=True,
        )
        browser.close()


if __name__ == "__main__":
    main()

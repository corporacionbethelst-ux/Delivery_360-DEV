"""Check a local production build and downloaded CSV with synthetic HTTP data.

Requires Playwright Python and Chromium. All business HTTP/WebSocket traffic is
intercepted; this script refuses remote preview URLs and makes no real payments.
"""

import argparse
import csv
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect


def bounds(query):
    start = query.get("date_from", [None])[0]
    end = query.get("date_to", [None])[0]
    return {
        "period_start": start + "T00:00:00" if start else None,
        "period_end": end + "T23:59:59.999999" if end else None,
    }


def orders(query):
    first = dict(
        id="order-1",
        external_id="EXT-1",
        status="ENTREGADO",
        priority="NORMAL",
        created_at="2026-11-06T12:00:00",
        ordered_at="2026-11-06T11:00:00",
        delivered_at="2026-11-06T13:00:00",
        customer_name='José, "Pérez"\nSegunda línea',
        customer_phone="+584121234567",
        customer_email="jose@example.test",
        pickup_address="Origen",
        delivery_address="Destino",
        subtotal=90,
        delivery_fee=10,
        total=100,
        payment_method=None,
        payment_status="PAGADO",
        rider_id="rider-1",
    )
    second = {
        **first,
        "id": "order-2",
        "external_id": "EXT-2",
        "status": "PENDIENTE",
        "customer_name": "=SUM(1,1)",
        "subtotal": 0,
        "delivery_fee": 0,
        "total": 0,
        "delivered_at": None,
        "payment_status": None,
        "rider_id": None,
    }
    return {
        **bounds(query),
        "total_orders": 2,
        "completed_orders": 1,
        "active_customers": 2,
        "total_revenue": 10,
        "gross_order_value": 100,
        "status_counts": {"ENTREGADO": 1, "PENDIENTE": 1},
        "rows": [first, second],
    }


def reconciliation(query):
    return {
        **bounds(query),
        "gross_order_value": 100,
        "delivery_revenue": 10,
        "completed_orders": 1,
        "ledger_transactions": 3,
        "payout_count": 2,
        "rider_earnings": 20,
        "rider_deductions": 5,
        "adjustments": -2,
        "net_rider_liability": 13,
        "pending_payouts": 2,
        "processed_payouts": 3,
        "rejected_payouts": 0,
        "available_liability": 8,
        "total_costs": 5,
        "net_margin_after_rider_costs": 5,
        "currency": "COP",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3068")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-reports-browser")
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
            [{"name": "auth-token", "value": "synthetic-reports-token", "url": base}]
        )
        context.add_init_script(
            """if (!localStorage.getItem('reports-browser-initialized')) { localStorage.setItem('app_version', '1.2.1'); localStorage.setItem('access_token', 'synthetic-reports-token'); localStorage.setItem('refresh_token', 'synthetic-reports-refresh'); localStorage.setItem('reports-browser-initialized', 'yes'); }"""
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
            elif path.endswith(
                ("/financial/reports/orders", "/financial/reconciliation")
            ):
                requests.append(
                    {"path": path, "query": query, "method": route.request.method}
                )
                if route.request.method != "GET":
                    writes.append(path)
                    route.abort()
                elif state["mode"] == "failed_export" and path.endswith(
                    "/reconciliation"
                ):
                    route.fulfill(
                        status=503,
                        json={"detail": "Synthetic failure"},
                        headers=headers,
                    )
                elif state["mode"] == "defer_export" and query.get("limit") == ["5000"]:
                    state["pending"] = (route, query, headers)
                else:
                    route.fulfill(
                        json=(
                            orders(query)
                            if path.endswith("/orders")
                            else reconciliation(query)
                        ),
                        headers=headers,
                    )
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "browser-user",
                        "email": "reports@example.test",
                        "role": "GERENTE",
                        "is_active": True,
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "created_at": "2026-11-01T00:00:00Z",
                    },
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
        page.goto(base + "/manager/financial/reports", wait_until="domcontentloaded")
        expect(page.get_by_role("region", name="Reporte confirmado")).to_be_visible()
        expect(
            page.get_by_text("Moneda no informada para órdenes", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("Moneda informada: COP", exact=True)).to_be_visible()
        passed("initial_pair_and_separate_currencies")

        count = len(requests)
        page.get_by_label("Fecha inicio", exact=True).fill("2026-11-01")
        page.get_by_label("Fecha fin", exact=True).fill("2026-11-07")
        expect(
            page.get_by_role("button", name="Exportar CSV", exact=True)
        ).to_be_disabled()
        assert len(requests) == count
        expect(page.get_by_text("Rango confirmado:", exact=False)).to_contain_text(
            "sin límite inicial"
        )
        page.get_by_role("button", name="Aplicar consulta").click()
        expect(page.get_by_text("Rango confirmado:", exact=False)).to_contain_text(
            "2026-11-01 → 2026-11-07"
        )
        assert all(
            item["query"].get("date_from") == ["2026-11-01"]
            and item["query"].get("date_to") == ["2026-11-07"]
            for item in requests[-2:]
        )
        passed("draft_requires_apply_and_pair_uses_same_range")

        state["mode"] = "failed_export"
        page.get_by_role("button", name="Exportar CSV", exact=True).click()
        expect(
            page.get_by_role("alert").filter(has_text="No se pudo comprobar")
        ).to_be_visible()
        expect(page.get_by_role("region", name="Reporte confirmado")).to_be_visible()
        assert not downloads
        passed("failed_reconciliation_does_not_download_or_mix_data")

        state["mode"] = "normal"
        with page.expect_download() as event:
            page.get_by_role("button", name="Reintentar exportación").click()
        download = event.value
        expect(
            page.get_by_text("CSV generado con 2 órdenes", exact=False)
        ).to_be_visible()
        csv_path = artifacts / "reporte-verificado.csv"
        download.save_as(str(csv_path))
        content = csv_path.read_text(encoding="utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(content)))
        assert len(rows) == 2
        assert rows[0]["id_orden"] == "order-1"
        assert rows[0]["cliente"] == 'José, "Pérez"\nSegunda línea'
        assert rows[0]["telefono"].startswith("'+58412")
        assert rows[1]["cliente"] == "'=SUM(1,1)"
        assert (
            rows[1]["total"] == "0"
            and rows[1]["metodo_pago"] == ""
            and rows[1]["moneda"] == ""
        )
        assert rows[0]["rango_desde_utc"] == "2026-11-01T00:00:00Z"
        assert "2026-11-01_2026-11-07_2_filas" in download.suggested_filename
        page.screenshot(
            path=str(artifacts / "financial-reports-desktop.png"), full_page=True
        )
        passed("actual_csv_download_preserves_range_zero_missing_values_and_safe_text")

        state["mode"] = "defer_export"
        page.get_by_role("button", name="Exportar CSV", exact=True).click()
        expect(
            page.get_by_role("status").filter(has_text="preparando el CSV")
        ).to_be_visible()
        page.get_by_label("Fecha inicio", exact=True).fill("2026-11-02")
        expect(
            page.get_by_text("La exportación se canceló", exact=False)
        ).to_be_visible()
        route, query, headers = state["pending"]
        route.fulfill(json=orders(query), headers=headers)
        state["pending"] = None
        page.wait_for_timeout(150)
        assert len(downloads) == 1
        expect(
            page.get_by_role("button", name="Exportar CSV", exact=True)
        ).to_be_disabled()
        state["mode"] = "normal"
        page.get_by_role("button", name="Aplicar consulta").click()
        expect(page.get_by_text("Rango confirmado:", exact=False)).to_contain_text(
            "2026-11-02 → 2026-11-07"
        )
        passed("editing_dates_cancels_old_pending_file")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for label in ("Fecha inicio", "Fecha fin"):
            box = page.get_by_label(label, exact=True).bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= 390
        page.screenshot(
            path=str(artifacts / "financial-reports-mobile.png"), full_page=True
        )
        passed("mobile_filters_fit_and_table_scrolls_locally")

        state["mode"] = "defer_export"
        page.get_by_role("button", name="Exportar CSV", exact=True).click()
        expect(
            page.get_by_role("status").filter(has_text="preparando el CSV")
        ).to_be_visible()
        page.evaluate("window.dispatchEvent(new Event('delivery360-session-expired'))")
        page.wait_for_url("**/login")
        assert page.evaluate("localStorage.getItem('access_token')") is None
        if state["pending"]:
            route, query, headers = state["pending"]
            route.fulfill(json=orders(query), headers=headers)
        page.wait_for_timeout(150)
        assert len(downloads) == 1
        assert not writes and not errors
        passed("logout_prevents_late_private_download")
        (artifacts / "browser-results.json").write_text(
            json.dumps(
                {
                    "checks_passed": checks,
                    "report_requests": requests,
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
                    "report_requests": len(requests),
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

"""Chromium checks of a local production build using synthetic HTTP responses.

Run: python e2e/financial-summary.browser.py --base-url http://127.0.0.1:3067
Requires Playwright Python and Chromium. Never connects to a real business API.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, expect


def summary(period, **changes):
    result = dict(
        period=period,
        period_start=f"2026-11-{'02' if period == 'week' else '01' if period == 'month' else '06'}T00:00:00",
        period_end="2026-11-06T18:00:00",
        total_revenue=100,
        total_costs=40,
        net_margin=60,
        total_rider_payouts=30,
        total_transactions=8,
        avg_per_delivery=25,
        gross_order_value=200,
        completed_deliveries=4,
        other_costs=10,
        cash_payouts_processed=20,
        rider_earnings_accrued=35,
        rider_deductions=5,
    )
    result.update(changes)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3067")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-summary-browser")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Use a local preview, never a production site")
    artifacts = Path(args.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    state = {"mode": "normal", "pending": None}
    requests, writes, errors, checks = [], [], [], []

    def record(name):
        checks.append(name)
        print("passed: " + name, flush=True)

    profile = dict(
        id="summary-browser-user",
        email="browser@example.test",
        role="GERENTE",
        first_name="Prueba",
        last_name="Local",
        is_active=True,
        created_at="2026-11-01T00:00:00Z",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium, headless=True, args=["--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100}, service_workers="block"
        )
        context.add_cookies(
            [{"name": "auth-token", "value": "synthetic-browser-token", "url": base}]
        )
        context.add_init_script(
            """if (!localStorage.getItem('summary-browser-initialized')) { localStorage.setItem('app_version', '1.2.1'); localStorage.setItem('access_token', 'synthetic-browser-token'); localStorage.setItem('refresh_token', 'synthetic-browser-refresh'); localStorage.setItem('summary-browser-initialized', 'yes'); }"""
        )
        context.set_default_timeout(10000)
        # An intercepted socket stays local unless connect_to_server is called.
        context.route_web_socket("**/*", lambda socket: None)

        def intercept(route):
            target = urlparse(route.request.url)
            path = target.path
            headers = {
                "access-control-allow-origin": base,
                "access-control-allow-headers": "authorization, content-type",
                "access-control-allow-methods": "GET, OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
                return
            if path.endswith("/financial/summary"):
                period = parse_qs(target.query).get("period", ["today"])[0]
                requests.append({"period": period, "method": route.request.method})
                if route.request.method != "GET":
                    writes.append(path)
                    route.abort()
                    return
                if state["mode"] == "fail_month" and period == "month":
                    route.fulfill(
                        status=503,
                        json={"detail": "Synthetic unavailable response"},
                        headers=headers,
                    )
                elif state["mode"] == "defer_today" and period == "today":
                    state["pending"] = route
                elif state["mode"] == "negative":
                    route.fulfill(
                        json=summary(
                            period,
                            total_costs=140,
                            total_rider_payouts=130,
                            rider_earnings_accrued=135,
                            net_margin=-40,
                        ),
                        headers=headers,
                    )
                elif state["mode"] == "optional":
                    route.fulfill(
                        json=summary(period, other_costs=None), headers=headers
                    )
                else:
                    route.fulfill(json=summary(period), headers=headers)
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(json=profile, headers=headers)
            elif route.request.url.startswith(base + "/"):
                route.continue_()
            else:
                if route.request.method != "GET":
                    writes.append(path)
                # All external traffic is fulfilled locally; no real API calls.
                route.fulfill(
                    json=[] if "alerts" in path else {"items": [], "unread_count": 0},
                    headers=headers,
                )

        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/manager/financial/resumen", wait_until="domcontentloaded")
        expect(
            page.get_by_text("Datos confirmados: Semana", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text("Moneda no informada por el servidor", exact=True)
        ).to_be_visible()
        assert not page.get_by_text("USD", exact=True).count()
        record("initial_week_unknown_currency")

        state["mode"] = "fail_month"
        page.get_by_role("button", name="Mes", exact=True).click()
        expect(
            page.get_by_role("alert").filter(has_text="No se pudo comprobar")
        ).to_be_visible()
        expect(
            page.get_by_text("Datos confirmados: Semana", exact=True)
        ).to_be_visible()
        expect(page.get_by_role("button", name="Semana", exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )
        state["mode"] = "normal"
        page.get_by_role("button", name="Reintentar consulta").click()
        expect(page.get_by_text("Datos confirmados: Mes", exact=True)).to_be_visible()
        record("failed_period_retained_and_retry")

        state["mode"] = "defer_today"
        page.get_by_role("button", name="Hoy", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("Consultando Hoy")
        page.get_by_role("button", name="Mes", exact=True).click()
        expect(page.get_by_role("status")).to_have_count(0)
        assert state["pending"] is not None
        state["pending"].fulfill(
            json=summary("today", total_revenue=999, net_margin=959),
            headers={"access-control-allow-origin": base},
        )
        state["pending"] = None
        page.wait_for_timeout(150)
        expect(page.get_by_text("Datos confirmados: Mes", exact=True)).to_be_visible()
        assert not page.get_by_text("999,00 (moneda no informada)", exact=True).count()
        record("late_period_does_not_replace_newer")

        state["mode"] = "negative"
        page.get_by_role("button", name="Actualizar resumen").click()
        graph = page.get_by_role(
            "img", name="Neto: -40,00 (moneda no informada)", exact=True
        )
        expect(graph).to_be_visible()
        box = graph.bounding_box()
        bar = graph.locator('[data-direction="negative"]').bounding_box()
        assert bar["width"] > 0 and bar["x"] < box["x"] + box["width"] / 2
        page.screenshot(
            path=str(artifacts / "financial-summary-desktop.png"), full_page=True
        )
        record("negative_margin_visible")

        state["mode"] = "optional"
        page.get_by_role("button", name="Actualizar resumen").click()
        expect(page.get_by_text("No informado", exact=True)).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        expect(page.get_by_text("Datos confirmados: Mes", exact=True)).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        description = page.get_by_text(
            "Ingresos por entregas cobradas y costos registrados del período.",
            exact=True,
        )
        assert description.evaluate(
            "e => e.getBoundingClientRect().right <= e.closest('.max-w-7xl').getBoundingClientRect().right + 1 && e.scrollWidth <= e.clientWidth + 1"
        )
        page.screenshot(
            path=str(artifacts / "financial-summary-mobile.png"), full_page=True
        )
        record("missing_cost_not_invented_mobile_layout")

        state["mode"] = "defer_today"
        page.get_by_role("button", name="Hoy", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("Consultando Hoy")
        page.evaluate("window.dispatchEvent(new Event('delivery360-session-expired'))")
        page.wait_for_url("**/login")
        assert page.evaluate("localStorage.getItem('access_token')") is None
        if state["pending"] is not None:
            state["pending"].fulfill(
                json=summary("today"), headers={"access-control-allow-origin": base}
            )
        expect(page.get_by_text("Datos confirmados: Mes", exact=True)).to_have_count(0)
        record("logout_discards_pending_private_summary")
        assert not writes, writes
        assert not errors, errors
        (artifacts / "browser-results.json").write_text(
            json.dumps(
                {
                    "checks_passed": checks,
                    "summary_requests": requests,
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
                    "summary_requests": len(requests),
                    "write_requests": len(writes),
                    "page_errors": errors,
                }
            )
        )
        browser.close()


if __name__ == "__main__":
    main()

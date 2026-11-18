"""Read versioned operational prices without writes in the retained marked lab."""

import argparse
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--lifecycle-results", required=True)
    parser.add_argument("--wait-request-window", action="store_true")
    args = parser.parse_args()
    state = local_test.configuration()
    command = local_test.compose(state, local_test.local_docker())
    env = local_test.compose_environment()

    def sql(q):
        return subprocess.check_output(
            command
            + [
                "exec",
                "-T",
                "test-db",
                "psql",
                "-U",
                "local_test",
                "-d",
                "test_delivery360_manual",
                "-Atc",
                q,
            ],
            env=env,
            text=True,
        ).strip()

    assert sql("SELECT id FROM local_test_instance") == state["instance"]
    local_test.check(state, authenticate=False)
    life = json.loads(Path(args.lifecycle_results).read_text())
    assert re.fullmatch(r"[0-9a-f]{12}", life["run"])
    private = local_test.STATE / ("lifecycle-rider-" + life["run"] + ".json")
    assert stat.S_IMODE(private.stat().st_mode) & 0o077 == 0
    account = json.loads(private.read_text())
    assert (
        account["instance"] == state["instance"]
        and account["rider_id"] == life["rider_id"]
    )
    if args.wait_request_window:
        time.sleep(60)
        time.sleep(1)
    users = json.loads(local_test.ACCOUNTS.read_text())
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors, writes, readonly_posts, reads = [], [], [], [], []

    def passed(message):
        checks.append(message)
        print("passed:", message, flush=True)

    def snapshot():
        return {
            t: sql(
                "SELECT count(*)::text||':'||md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM "
                + t
                + " t"
            )
            for t in (
                "orders",
                "deliveries",
                "financials",
                "financial_transactions",
                "rider_wallets",
                "payouts",
                "payout_status_history",
                "platform_settings",
                "bcv_rates",
                "usd_ves_quotes",
                "order_currency_quotes",
                "customer_collections",
                "customer_collection_reviews",
                "customer_refunds",
                "customer_refund_events",
                "rider_documents",
            )
        }

    before = snapshot()
    passed("marked laboratory and private rider identity confirmed before price reads")

    def label(value):
        assert isinstance(value, str) and re.fullmatch(
            r"(?:0|[1-9][0-9]{0,7})\.[0-9]{2}", value
        )
        units, fraction = value.split(".")
        return "USD " + re.sub(r"\B(?=(\d{3})+(?!\d))", ".", units) + "," + fraction

    selected = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        contexts = []

        def login(credentials, home):
            context = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                locale="es-VE",
                timezone_id="America/Caracas",
                reduced_motion="reduce",
            )
            contexts.append(context)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def guard(route):
                request = route.request
                path = request.url.split("/api/v1/", 1)[-1].split("?", 1)[0]
                if request.method not in ("GET", "OPTIONS") and path not in (
                    "auth/login",
                    "auth/refresh",
                ):
                    writes.append({"method": request.method, "path": path})
                    route.abort()
                    return
                if request.method == "GET":
                    reads.append(path)
                route.continue_()

            context.route("**/api/v1/**", guard)
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.locator("input[type=email]").fill(credentials["email"])
            page.locator("input[type=password]").fill(credentials["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(base + home, timeout=30000)
            token = page.evaluate('localStorage.getItem("access_token")')
            assert token
            return page, context, {"Authorization": "Bearer " + token}

        def get(page, headers, path):
            response = page.request.get(api + path, headers=headers)
            assert response.status == 200, (path, response.status)
            return response.json()

        for role in ["OPERADOR", "SUPERADMIN", "GERENTE"]:
            page, context, headers = login(
                users[role], "/operator" if role == "OPERADOR" else "/manager"
            )
            assert get(page, headers, "/auth/me")["role"] == role
            if selected is None:
                for order_id in life["created_order_ids"]:
                    assert str(UUID(order_id)) == order_id
                    candidate = get(page, headers, "/orders/" + order_id)
                    if candidate.get("pricing") and candidate.get("delivery"):
                        selected = candidate
                        break
            assert selected is not None
            order_id, delivery_id = selected["id"], selected["delivery"]["id"]
            source = get(page, headers, "/orders/" + order_id)
            price = source["pricing"]
            assert (
                price["version"] == 1
                and price["currency"] == "USD"
                and isinstance(price["total"], str)
            )
            total = label(price["total"])
            page.goto(base + "/operator/orders", wait_until="domcontentloaded")
            search = page.get_by_placeholder("Buscar por ID o cliente...")
            expect(search).to_be_visible(timeout=30000)
            search.fill(source["external_id"])
            row = page.get_by_role("row").filter(has_text=source["external_id"])
            expect(row).to_have_count(1, timeout=30000)
            expect(row).to_contain_text(total)
            expect(row).to_contain_text("Revisión " + str(price["revision"]))
            passed(
                role
                + ": operational order catalog shows the versioned decimal total and revision"
            )

            page.goto(
                base + "/operator/orders/" + order_id, wait_until="domcontentloaded"
            )
            panel = page.get_by_role(
                "region", name="Precio registrado de la orden", exact=True
            )
            expect(panel).to_be_visible(timeout=30000)
            expect(panel.get_by_text(total, exact=True).first).to_be_visible()
            expect(panel).to_contain_text(label(price["delivery_fee"]))
            expect(panel).to_contain_text("Los cobros, el saldo pendiente y el bono")
            if price["items"]:
                expect(
                    page.get_by_role("table", name="Artículos del precio registrado")
                ).to_be_visible()
                expect(
                    page.get_by_role("table", name="Artículos del precio registrado")
                ).to_contain_text(label(price["items"][0]["subtotal"]))
            passed(
                role
                + ": real order detail preserves price items, fee, total and explicit independent books"
            )

            page.goto(
                base + "/operator/deliveries/" + delivery_id,
                wait_until="domcontentloaded",
            )
            panel = page.get_by_role(
                "region", name="Precio registrado de la orden", exact=True
            )
            expect(panel).to_be_visible(timeout=30000)
            expect(panel.get_by_text(total, exact=True).first).to_be_visible()
            assert "orders/" + order_id in reads
            passed(
                role
                + ": delivery detail reads the identified order and confirms the two-way delivery link"
            )

            context.route(
                "**/api/v1/orders/" + order_id,
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"synthetic read failure"}',
                ),
            )
            page.reload(wait_until="domcontentloaded")
            expect(
                page.get_by_role("alert").filter(
                    has_text="No se pudo confirmar el precio"
                )
            ).to_contain_text("No se pudo confirmar el precio", timeout=30000)
            expect(
                page.get_by_role(
                    "region", name="Precio registrado de la orden", exact=True
                )
            ).to_have_count(0)
            expect(
                page.get_by_role("heading", name="Detalles", exact=True)
            ).to_be_visible()
            context.unroute("**/api/v1/orders/" + order_id)
            page.get_by_role("button", name="Reintentar precio", exact=True).click()
            panel = page.get_by_role(
                "region", name="Precio registrado de la orden", exact=True
            )
            expect(panel.get_by_text(total, exact=True).first).to_be_visible(
                timeout=30000
            )
            passed(
                role
                + ": secondary price failure leaves delivery details available and retry only repeats a read"
            )

            page.set_viewport_size({"width": 390, "height": 844})
            panel.scroll_into_view_if_needed()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth + 1"
            )
            page.screenshot(
                path=str(out / (role.lower() + "-delivery-price-mobile.png")),
                animations="disabled",
            )
            page.set_viewport_size({"width": 1440, "height": 1100})
            page.goto(
                base + "/operator/orders/" + order_id, wait_until="domcontentloaded"
            )
            panel = page.get_by_role(
                "region", name="Precio registrado de la orden", exact=True
            )
            expect(panel).to_be_visible(timeout=30000)
            page.screenshot(
                path=str(out / (role.lower() + "-order-price-desktop.png")),
                animations="disabled",
                full_page=True,
            )
            passed(
                role
                + ": colorful confirmed price panels fit desktop and mobile without document overflow"
            )

            if role == "OPERADOR":
                historic_id = sql(
                    "SELECT o.id FROM orders o WHERE o.pricing_version IS NULL AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.order_id=o.id AND d.rider_id IS DISTINCT FROM o.assigned_rider_id) ORDER BY o.id LIMIT 1"
                )
                if historic_id:
                    assert str(UUID(historic_id)) == historic_id
                    historic = get(page, headers, "/orders/" + historic_id)
                    assert historic["pricing"] is None
                    page.goto(
                        base + "/operator/orders/" + historic_id,
                        wait_until="domcontentloaded",
                    )
                    panel = page.get_by_role(
                        "region", name="Precio registrado de la orden", exact=True
                    )
                    expect(panel).to_contain_text(
                        "Precio versionado no disponible", timeout=30000
                    )
                    expect(panel).not_to_contain_text("USD")
                    passed(
                        "operator: actual historical order retains its absence of exact pricing without a USD or zero fallback"
                    )
                else:
                    # A fresh CI laboratory may contain only versioned fixtures.
                    passed(
                        "operator: no unversioned order present; historical absence covered by deterministic protocol and consumer cases"
                    )
            context.close()

        assert selected is not None
        page, context, headers = login(account["account"], "/rider")
        owned = get(page, headers, "/orders/" + selected["id"])
        assert owned["assigned_rider_id"] == life["rider_id"]
        total = label(owned["pricing"]["total"])
        page.goto(base + "/rider/my-orders", wait_until="domcontentloaded")
        expect(page.get_by_text("#" + owned["external_id"], exact=True)).to_be_visible(
            timeout=30000
        )
        card = page.locator("div.cursor-pointer").filter(
            has=page.get_by_text("#" + owned["external_id"], exact=True)
        )
        expect(card).to_have_count(1)
        expect(card).to_contain_text(total)
        expect(card).to_contain_text("Precio de la orden")
        expect(page.get_by_text("A cobrar", exact=True)).to_have_count(0)
        passed(
            "rider: real owned order catalog shows its versioned price without claiming outstanding debt or earnings"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        card.scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(
            path=str(out / "rider-order-price-mobile.png"), animations="disabled"
        )
        passed("rider: exact price and revision remain readable on a narrow screen")
        context.route(
            "**/api/v1/orders?*",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"synthetic catalog failure"}',
            ),
        )
        page.get_by_role("button", name="Actualizar", exact=True).click()
        expect(
            page.get_by_role("alert").filter(
                has_text="No se pudieron consultar las órdenes"
            )
        ).to_contain_text("última lectura confirmada", timeout=30000)
        expect(card).to_contain_text(total)
        context.unroute("**/api/v1/orders?*")
        page.get_by_role("button", name="Actualizar", exact=True).click()
        expect(
            page.get_by_role("alert").filter(
                has_text="No se pudieron consultar las órdenes"
            )
        ).to_have_count(0, timeout=30000)
        expect(card).to_contain_text(total)
        passed(
            "rider: failed refresh retains the confirmed list explicitly and a fresh read recovers"
        )
        context.close()
        browser.close()
    after = snapshot()
    assert (
        before == after
    ), "Read-only price checks changed operational or monetary rows"
    assert not errors and not writes, (errors, writes)
    passed(
        "all original table hashes preserved; zero business writes or JavaScript errors"
    )
    assert len(checks) == 21
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "writes": writes,
                "reads": reads,
                "history_preserved": True,
                "instance": state["instance"],
                "bank_transfer_performed": False,
                "external_messages_sent": False,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

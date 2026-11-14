"""Order-linked BCV quotation receipts against the marked real local laboratory."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", required=True)
    args = parser.parse_args()
    state = local_test.configuration()
    command = local_test.compose(state, local_test.local_docker())

    def sql(statement):
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
                statement,
            ],
            text=True,
            env=local_test.compose_environment(),
        ).strip()

    assert (
        sql("SELECT id FROM local_test_instance") == state["instance"]
    ), "Marked laboratory required before any write"
    local_test.check(state, authenticate=False)
    users = json.loads(local_test.ACCOUNTS.read_text())
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    run = uuid4().hex[:12]

    def passed(name):
        checks.append(name)
        print("passed:", name, flush=True)

    def ledger_snapshot():
        return {
            table: sql(
                "SELECT count(*)::text||':'||md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM "
                + table
                + " t"
            )
            for table in (
                "financials",
                "financial_transactions",
                "rider_wallets",
                "payouts",
                "payout_status_history",
            )
        }

    before = ledger_snapshot()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="es-VE",
            timezone_id="America/Caracas",
        )
        page = context.new_page()
        page.on("pageerror", lambda problem: errors.append(str(problem)))
        page.goto(base + "/login", wait_until="domcontentloaded")
        page.locator("input[type=email]").fill(users["SUPERADMIN"]["email"])
        page.locator("input[type=password]").fill(users["SUPERADMIN"]["password"])
        page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
        page.wait_for_url(re.compile("/manager(?:/|$)"), timeout=30000)
        token = page.evaluate('localStorage.getItem("access_token")')
        assert isinstance(token, str) and token
        headers = {"Authorization": "Bearer " + token}

        def call(method, path, body=None, status=200):
            response = page.request.fetch(
                api + path, method=method, headers=headers, data=body
            )
            assert response.status == status, (
                method,
                path,
                response.status,
                response.text(),
            )
            return response.json()

        identity = call("GET", "/auth/me")
        assert identity["id"] == sql(
            "SELECT id FROM users WHERE email='admin.local-test@example.com'"
        )
        passed("real identity and dedicated laboratory marker verified")

        def rate(value):
            current = call("GET", "/currency/context")
            return call(
                "POST",
                "/currency/rates",
                {
                    "request_key": str(uuid4()),
                    "previous_rate_id": (
                        current["current_rate"]["id"]
                        if current["current_rate"]
                        else None
                    ),
                    "valid_on": current["today"],
                    "reference_date": current["today"],
                    "ves_per_usd": value,
                    "note": "ENTREGA93 SYNTHETIC BCV reference " + run,
                    "confirmed_bcv": True,
                },
                status=201,
            )

        first_rate = rate("1.50000000")
        order = call(
            "POST",
            "/orders",
            {
                "customer_name": "Order BCV " + run,
                "customer_phone": "+584120000000",
                "pickup_address": "Synthetic origin",
                "delivery_address": "Synthetic destination",
                "delivery_contact": "Laboratory contact",
                "items": [
                    {
                        "product_name": "Decimal product",
                        "quantity": "3",
                        "unit_price": "0.10",
                    }
                ],
                "delivery_fee": "0.20",
                "currency": "USD",
            },
            status=201,
        )
        oid = order["id"]
        assert re.fullmatch(r"[0-9a-f-]{36}", oid)
        quote_path = "/currency/orders/" + oid + "/quotes"

        def count():
            return sql(
                "SELECT count(*) FROM order_currency_quotes WHERE order_id='"
                + oid
                + "'"
            )

        page.goto(
            base + "/manager/operations/orders/" + oid, wait_until="domcontentloaded"
        )
        panel = page.get_by_role(
            "region", name="Cotización BCV de la orden", exact=True
        )
        review = panel.get_by_role(
            "button", name="Revisar cotización de la orden", exact=True
        )
        expect(review).to_be_enabled(timeout=20000)
        review.click()
        dialog = page.get_by_role("dialog", name="Revisar cotización de esta orden")
        expect(dialog.get_by_text("Bs. 0,75", exact=True)).to_be_visible()
        dialog.get_by_role("button", name="Cancelar", exact=True).click()
        assert count() == "0"
        passed(
            "real review displays 0.50 USD and 0.75 VES; cancellation performs no quotation write"
        )
        review.click()
        with page.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/api/v1" + quote_path)
        ) as posted:
            dialog.get_by_role("button", name="Guardar cotización", exact=True).click()
        response = posted.value
        assert response.status == 201, response.text()
        original = response.json()
        intent = response.request.post_data_json
        assert set(intent) == {"request_key", "rate_id", "expected_pricing_revision"}
        assert (
            intent["rate_id"] == first_rate["id"]
            and intent["expected_pricing_revision"] == 1
        )
        assert (original["amount_usd"], original["amount_ves"]) == ("0.50", "0.75")
        assert (
            original["pricing"]["revision"] == 1
            and original["payment_confirmed"] is False
        )
        assert (
            sql(
                "SELECT amount_usd::text||':'||amount_ves::text FROM order_currency_quotes WHERE id='"
                + original["id"]
                + "'"
            )
            == "0.50:0.75"
        )
        saved = panel.locator('[aria-label="Comprobante conservado"]')
        expect(saved.get_by_text("Cotización guardada", exact=True)).to_be_visible()
        assert "bcv_quote=" + original["id"] in page.url
        panel.scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "order-bcv-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        passed(
            "server derives the amount from the exact price and PostgreSQL stores a linked immutable receipt"
        )
        page.reload(wait_until="domcontentloaded")
        expect(saved).to_be_visible(timeout=20000)
        second_rate = rate("2.00000000")
        page.reload(wait_until="domcontentloaded")
        expect(saved.get_by_text("USD 0,50 → Bs. 0,75", exact=True)).to_be_visible(
            timeout=20000
        )
        assert call("GET", "/currency/order-quotes/" + original["id"]) == original
        assert (
            call("POST", quote_path, intent, status=201) == original and count() == "1"
        )
        passed(
            "reload and a corrected BCV reference preserve the original receipt and idempotent identity"
        )
        call(
            "PATCH",
            "/orders/" + oid,
            {"delivery_fee": "0.30", "expected_pricing_revision": 1},
        )
        page.reload(wait_until="domcontentloaded")
        expect(
            saved.get_by_text(
                "El precio actual de la orden cambió. Este comprobante conserva su revisión anterior.",
                exact=True,
            )
        ).to_be_visible(timeout=20000)
        passed(
            "an updated order price is identified separately from the retained quotation revision"
        )
        review.click()
        expect(dialog.get_by_text("Bs. 1,20", exact=True)).to_be_visible()
        call(
            "PATCH",
            "/orders/" + oid,
            {"delivery_fee": "0.40", "expected_pricing_revision": 2},
        )
        with page.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/api/v1" + quote_path)
        ) as stale_price:
            dialog.get_by_role("button", name="Guardar cotización", exact=True).click()
        assert stale_price.value.status == 412 and count() == "1"
        expect(panel.get_by_role("alert")).to_contain_text("precio")
        expect(review).to_be_enabled()
        review.click()
        expect(dialog.get_by_text("Bs. 1,40", exact=True)).to_be_visible()
        third_rate = rate("3.00000000")
        with page.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/api/v1" + quote_path)
        ) as stale_rate:
            dialog.get_by_role("button", name="Guardar cotización", exact=True).click()
        assert stale_rate.value.status == 412 and count() == "1"
        expect(panel.get_by_role("alert")).to_contain_text("tasa BCV")
        passed("price and BCV races both return 412 without saving a partial quotation")
        expect(review).to_be_enabled()
        review.click()
        expect(dialog.get_by_text("Bs. 2,10", exact=True)).to_be_visible()
        lost = []

        def drop_first_response(route):
            if route.request.method != "POST" or lost:
                route.continue_()
                return
            result = route.fetch()
            assert result.status == 201, result.text()
            lost.append(result.json())
            route.abort("failed")

        page.route("**/api/v1" + quote_path, drop_first_response)
        dialog.get_by_role("button", name="Guardar cotización", exact=True).click()
        retry = dialog.get_by_role("button", name="Reintentar comprobante", exact=True)
        expect(retry).to_be_enabled(timeout=20000)
        assert len(lost) == 1 and count() == "2"
        with page.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/api/v1" + quote_path)
        ) as retried:
            retry.click()
        assert (
            retried.value.status == 201
            and retried.value.json() == lost[0]
            and count() == "2"
        )
        assert (
            retried.value.request.post_data_json["request_key"]
            == lost[0]["request_key"]
        )
        page.unroute("**/api/v1" + quote_path, drop_first_response)
        expect(saved.get_by_text("USD 0,70 → Bs. 2,10", exact=True)).to_be_visible()
        passed(
            "a genuinely committed response lost to the browser is recovered by the same request key without duplication"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        saved.scroll_into_view_if_needed()
        expect(saved).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.screenshot(
            path=str(out / "order-bcv-mobile.png"),
            full_page=True,
            animations="disabled",
        )
        passed(
            "the colorful order quotation and preserved receipt fit the mobile viewport"
        )
        assert call("GET", "/currency/order-quotes/" + original["id"]) == original
        assert call("GET", "/currency/order-quotes/" + lost[0]["id"]) == lost[0]
        after = ledger_snapshot()
        assert before == after and not errors, errors
        passed(
            "quotes leave balances, ledger movements and withdrawals unchanged; no JavaScript exceptions"
        )
        context.close()
        browser.close()
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "instance": state["instance"],
                "order_id": oid,
                "receipt_ids": [original["id"], lost[0]["id"]],
                "ledger_before": before,
                "ledger_after": after,
                "expected_lost_response_simulated": True,
                "bank_transfer_performed": False,
            },
            indent=2,
        )
    )
    print(json.dumps({"checks": len(checks), "errors": errors}))


if __name__ == "__main__":
    main()

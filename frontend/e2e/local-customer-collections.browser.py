"""Customer declarations and independent manual review in the marked real laboratory."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--wait-request-window", action="store_true")
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
    ), "Marked laboratory required before writing"
    local_test.check(state, authenticate=False)
    if args.wait_request_window:
        print("Respecting the shared request/authentication window", flush=True)
        time.sleep(60)
        time.sleep(1)
    accounts = json.loads(local_test.ACCOUNTS.read_text())
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    run = uuid4().hex[:12]

    def passed(name):
        checks.append(name)
        print("passed:", name, flush=True)

    def ledger():
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

    before = ledger()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        def session(role):
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                locale="es-VE",
                timezone_id="America/Caracas",
            )
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.locator("input[type=email]").fill(accounts[role]["email"])
            page.locator("input[type=password]").fill(accounts[role]["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(re.compile("/manager(?:/|$)"), timeout=30000)
            token = page.evaluate('localStorage.getItem("access_token")')
            assert token
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
            assert (
                identity["id"]
                == sql(
                    "SELECT id FROM users WHERE email='" + accounts[role]["email"] + "'"
                )
                and identity["role"] == role
            )
            return ctx, page, call, identity

        admin_ctx, page, call, admin = session("SUPERADMIN")
        manager_ctx, manager, review_call, supervisor = session("GERENTE")
        assert admin["id"] != supervisor["id"]
        passed("two real independent staff identities match the dedicated database")
        current = call("GET", "/currency/context")
        rate = call(
            "POST",
            "/currency/rates",
            dict(
                request_key=str(uuid4()),
                previous_rate_id=(
                    current["current_rate"]["id"] if current["current_rate"] else None
                ),
                valid_on=current["today"],
                reference_date=current["today"],
                ves_per_usd="1.50000000",
                note="ENTREGA94 SYNTHETIC BCV reference " + run,
                confirmed_bcv=True,
            ),
            201,
        )
        order = call(
            "POST",
            "/orders",
            dict(
                customer_name="Collections " + run,
                customer_phone="+584120000000",
                pickup_address="Synthetic origin",
                delivery_address="Synthetic destination",
                delivery_contact="Laboratory",
                items=[dict(product_name="Decimal", quantity="3", unit_price="0.10")],
                delivery_fee="0.20",
                currency="USD",
            ),
            201,
        )
        oid = order["id"]
        path = "/customer-collections/orders/" + oid
        url = base + "/manager/operations/orders/" + oid
        quote = call(
            "POST",
            "/currency/orders/" + oid + "/quotes",
            dict(
                request_key=str(uuid4()),
                rate_id=rate["id"],
                expected_pricing_revision=1,
            ),
            201,
        )
        page.goto(url, wait_until="domcontentloaded")
        panel = page.get_by_role("region", name="Cobros de clientes", exact=True)

        def fill(usd, actual, reference):
            panel.get_by_label("Abono a la orden en USD", exact=True).fill(usd)
            panel.get_by_label("Importe realmente recibido", exact=True).fill(actual)
            panel.get_by_label("Alias interno de caja o cuenta", exact=True).fill(
                "CAJA-" + run.upper()
            )
            panel.get_by_label("Referencia completa o recibo único", exact=True).fill(
                reference
            )
            panel.get_by_label(re.compile("Confirmo que el importe")).check()
            panel.get_by_role(
                "button", name="Revisar declaración de cobro", exact=True
            ).click()

        expect(
            panel.get_by_role("button", name="Revisar declaración de cobro", exact=True)
        ).to_be_disabled(timeout=20000)
        fill("0.20", "0.20", "USD-" + run.upper())
        modal = page.get_by_role("dialog", name="Confirmar declaración de cobro")
        expect(modal.get_by_text("USD 0,20", exact=True)).to_be_visible()
        modal.get_by_role("button", name="Cancelar", exact=True).click()
        assert call("GET", path)["collection_revision"] == 0
        passed("declaration review displays exact cents and cancel performs no write")
        panel.get_by_role(
            "button", name="Revisar declaración de cobro", exact=True
        ).click()
        lost = []

        def lose(route):
            if route.request.method != "POST" or lost:
                route.continue_()
                return
            result = route.fetch()
            assert result.status == 201, result.text()
            lost.append(result.json())
            route.abort("failed")

        page.route("**/api/v1" + path, lose)
        modal.get_by_role("button", name="Confirmar y guardar", exact=True).click()
        expect(
            modal.get_by_role("button", name="Reintentar misma solicitud", exact=True)
        ).to_be_enabled(timeout=20000)
        assert (
            len(lost) == 1
            and sql(
                "SELECT count(*) FROM customer_collections WHERE order_id='" + oid + "'"
            )
            == "1"
        )
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/api/v1" + path)
        ) as recovered:
            modal.get_by_role(
                "button", name="Reintentar misma solicitud", exact=True
            ).click()
        first = recovered.value.json()
        assert (
            recovered.value.status == 201
            and first == lost[0]
            and recovered.value.request.post_data_json["request_key"]
            == first["request_key"]
        )
        page.unroute("**/api/v1" + path, lose)
        expect(panel.get_by_label("Registro de cobro conservado")).to_be_visible(
            timeout=20000
        )
        ctx = call("GET", path)
        assert (
            ctx["summary"]["verified_usd"] == "0.00"
            and ctx["summary"]["pending_usd"] == "0.20"
            and ctx["summary"]["due_usd"] == "0.50"
            and ctx["price_locked"]
        )
        passed(
            "a committed response lost to the browser recovers the same pending receipt without duplicate credit"
        )
        assert "customer_collection=" + first["id"] in page.url
        page.reload(wait_until="domcontentloaded")
        expect(panel.get_by_label("Registro de cobro conservado")).to_be_visible(
            timeout=20000
        )
        assert (
            panel.get_by_role("button", name="Revisar este cobro", exact=True).count()
            == 0
        )
        call(
            "POST",
            "/customer-collections/" + first["id"] + "/review",
            dict(
                request_key=str(uuid4()),
                expected_collection_revision=1,
                decision="VERIFICADO",
                note="Synthetic invalid self verification",
                verified_evidence=True,
            ),
            403,
        )
        call(
            "PATCH",
            "/orders/" + oid,
            dict(delivery_fee="0.30", expected_pricing_revision=1),
            409,
        )
        page.goto(url + "/edit", wait_until="domcontentloaded")
        expect(
            page.get_by_text(re.compile("Precio protegido por cobros"))
        ).to_be_visible(timeout=20000)
        expect(page.locator("input[type=number]").first).to_be_disabled()
        expect(
            page.get_by_role("button", name="Guardar Cambios", exact=True)
        ).to_be_enabled()
        page.locator('input[value="Synthetic origin"]').fill("Synthetic origin revised")
        with page.expect_response(
            lambda r: r.request.method == "PATCH"
            and r.url.endswith("/api/v1/orders/" + oid)
        ) as edited:
            page.get_by_role("button", name="Guardar Cambios", exact=True).click()
        assert edited.value.status == 200, edited.value.text()
        payload = edited.value.request.post_data_json
        assert payload["pickup_address"] == "Synthetic origin revised"
        assert not set(payload).intersection(
            {
                "items",
                "subtotal",
                "delivery_fee",
                "total",
                "declared_value",
                "expected_pricing_revision",
            }
        )
        assert edited.value.json()["pricing"] == order["pricing"]
        passed(
            "self review is rejected; the protected edit form saves addresses without resubmitting money"
        )
        manager.goto(url, wait_until="domcontentloaded")
        review_panel = manager.get_by_role(
            "region", name="Cobros de clientes", exact=True
        )
        review_panel.get_by_role(
            "button", name="Revisar este cobro", exact=True
        ).click()
        review_panel.get_by_label("Comprobación o motivo", exact=True).fill(
            "Efectivo contado contra el recibo sintético"
        )
        review_panel.get_by_label(re.compile("He comprobado el efectivo")).check()
        review_panel.get_by_role("button", name="Revisar decisión", exact=True).click()
        review_modal = manager.get_by_role("dialog", name="Confirmar revisión manual")
        with manager.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/" + first["id"] + "/review")
        ) as verified:
            review_modal.get_by_role(
                "button", name="Confirmar y guardar", exact=True
            ).click()
        confirmed = verified.value.json()
        assert (
            verified.value.status == 201
            and confirmed["status"] == "VERIFICADO_MANUALMENTE"
            and confirmed["review"]["reviewed_by"] == supervisor["id"]
        )
        ctx = call("GET", path)
        assert (
            ctx["summary"]["verified_usd"] == "0.20"
            and ctx["summary"]["due_usd"] == "0.30"
        )
        passed(
            "another supervisor checks evidence and only that decision recognizes the partial USD credit"
        )
        page.goto(url, wait_until="domcontentloaded")
        expect(
            panel.get_by_role("button", name="Revisar declaración de cobro", exact=True)
        ).to_be_visible(timeout=20000)
        panel.get_by_label("Medio de cobro", exact=True).select_option("PAGO_MOVIL")
        expect(panel.get_by_label("Moneda recibida", exact=True)).to_have_value("VES")
        panel.get_by_label("Cotización BCV conservada", exact=True).select_option(
            quote["id"]
        )
        fill("0.30", "0.45", "VES-" + run.upper())
        expect(modal.get_by_text(re.compile("Bs. 0,45"))).to_be_visible()
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/api/v1" + path)
        ) as posted:
            modal.get_by_role("button", name="Confirmar y guardar", exact=True).click()
        second = posted.value.json()
        assert (
            posted.value.status == 201
            and second["quote"] == quote
            and second["paid_amount"] == "0.45"
        )
        expect(panel.get_by_label("Registro de cobro conservado")).to_contain_text(
            second["id"]
        )
        decision = dict(
            request_key=str(uuid4()),
            expected_collection_revision=3,
            decision="VERIFICADO",
            note="Pago móvil comprobado en cuenta sintética",
            verified_evidence=True,
            acknowledge_refund_due=False,
        )
        receipt = review_call(
            "POST", "/customer-collections/" + second["id"] + "/review", decision, 201
        )
        assert receipt["status"] == "VERIFICADO_MANUALMENTE"
        assert (
            review_call(
                "POST",
                "/customer-collections/" + second["id"] + "/review",
                decision,
                201,
            )
            == receipt
        )
        ctx = call("GET", path)
        assert (
            ctx["summary"]["state"] == "COMPLETO"
            and ctx["summary"]["verified_usd"] == "0.50"
            and ctx["summary"]["available_to_declare_usd"] == "0.00"
        )
        passed(
            "partial pago móvil preserves the agreed BCV quote and completes USD credit with idempotent manual review"
        )
        page.reload(wait_until="domcontentloaded")
        expect(panel.get_by_label("Registro de cobro conservado")).to_be_visible(
            timeout=20000
        )
        expect(
            panel.get_by_role("button", name="Revisar declaración de cobro", exact=True)
        ).to_have_count(0)
        panel.scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "collections-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        panel.scroll_into_view_if_needed()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.screenshot(
            path=str(out / "collections-mobile.png"),
            full_page=True,
            animations="disabled",
        )
        passed(
            "colorful cobro summaries, history and receipt fit desktop and mobile without overflow"
        )
        call("PATCH", "/orders/" + oid + "/status?new_status=CANCELADO", status=200)
        ctx = call("GET", path)
        assert (
            ctx["summary"]["refund_due_usd"] == "0.50"
            and ctx["summary"]["due_usd"] == "0.00"
            and ctx["summary"]["state"] == "DEVOLUCION_PENDIENTE"
        )
        assert (
            call("GET", "/customer-collections/" + first["id"])["review"]
            == confirmed["review"]
        )
        passed(
            "cancellation preserves original declarations and surfaces a refund liability without executing a refund"
        )
        after = ledger()
        assert before == after and not errors, errors
        passed(
            "rider books, wallet balances and withdrawals remain byte-identical; no JavaScript exceptions"
        )
        admin_ctx.close()
        manager_ctx.close()
        browser.close()
    (out / "results.json").write_text(
        json.dumps(
            dict(
                checks=checks,
                errors=errors,
                instance=state["instance"],
                order_id=oid,
                collection_ids=[first["id"], second["id"]],
                ledger_before=before,
                ledger_after=after,
                expected_lost_response_simulated=True,
                bank_transfer_performed=False,
            ),
            indent=2,
        )
    )
    print(json.dumps(dict(checks=len(checks), errors=errors)))


if __name__ == "__main__":
    main()

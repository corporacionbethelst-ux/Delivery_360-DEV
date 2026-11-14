"""Real USD/VES quotations, restricted to the explicitly marked local lab."""

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
    parser.add_argument("--wait-auth-window", action="store_true")
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

    if sql("SELECT id FROM local_test_instance") != state["instance"]:
        raise SystemExit("Not the dedicated laboratory; no writes permitted")
    local_test.check(state, authenticate=False)
    if args.wait_auth_window:
        # Earlier functional runners share the real five-logins/minute quota.
        time.sleep(60)
        time.sleep(1)
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

    def legacy_snapshot():
        # Compare only digests/counts; never export legacy financial contents.
        result = {}
        for table in (
            "orders",
            "financials",
            "financial_transactions",
            "rider_wallets",
            "payout_requests",
            "payouts",
            "platform_settings",
        ):
            result[table] = sql(
                "SELECT count(*)::text || ':' || md5(COALESCE("
                "string_agg(to_jsonb(t)::text, '' ORDER BY to_jsonb(t)::text), '')) "
                "FROM " + table + " t"
            )
        return result

    before = legacy_snapshot()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        def login(role):
            context = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                locale="es-VE",
                timezone_id="America/Caracas",
            )
            page = context.new_page()
            page.on("pageerror", lambda problem: errors.append(str(problem)))
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.locator("input[type=email]").fill(users[role]["email"])
            page.locator("input[type=password]").fill(users[role]["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(re.compile("/(?:manager|operator)(?:/|$)"), timeout=30000)
            token = page.evaluate('localStorage.getItem("access_token")')
            assert isinstance(token, str) and token
            return context, page, {"Authorization": "Bearer " + token}

        context, page, staff = login("SUPERADMIN")

        def call(method, path, body=None, expected=200, headers=None, client=None):
            response = (client or page).request.fetch(
                api + path,
                method=method,
                headers=headers or staff,
                data=body,
            )
            assert response.status == expected, (
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
        passed("real API identity matches the marked laboratory database")
        page.goto(base + "/manager/admin/currency", wait_until="domcontentloaded")
        expect(
            page.get_by_role("heading", name="USD y bolívares", exact=True)
        ).to_be_visible()
        rate_field = page.get_by_label("Bolívares por 1 USD", exact=True)
        expect(rate_field).to_be_enabled(timeout=20000)
        current = call("GET", "/currency/context")
        assert (
            current["scope"] == "quotation_only"
            and not current["automatic_bcv_available"]
        )
        initial_count = sql("SELECT count(*) FROM bcv_rates")
        note = "DATO SINTÉTICO DE LABORATORIO; no es tasa BCV real. " + run

        def review(value):
            rate_field.fill(value)
            page.get_by_label("Fecha de la referencia BCV", exact=True).fill(
                current["today"]
            )
            page.get_by_role("textbox", name=re.compile("^Nota de verificación")).fill(
                note
            )
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="Revisar tasa", exact=True).click()
            expect(page.get_by_role("dialog")).to_be_visible()

        review("1,5")
        page.get_by_role("button", name="Cancelar", exact=True).click()
        assert sql("SELECT count(*) FROM bcv_rates") == initial_count
        passed("review cancellation causes no rate write")
        review("1,5")
        with page.expect_response(
            lambda r: r.url.endswith("/currency/rates") and r.request.method == "POST"
        ) as saved:
            page.get_by_role("button", name="Confirmar tasa", exact=True).click()
        assert saved.value.status == 201
        rate_body = saved.value.request.post_data_json
        first_rate = saved.value.json()
        expect(page.get_by_role("dialog")).to_have_count(0)
        assert (
            first_rate["ves_per_usd"] == "1.50000000"
            and not first_rate["automatically_verified"]
        )
        passed("confirmed manual rate is stored with exact decimals and provenance")

        page.get_by_label("Importe en USD", exact=True).fill("0,01")
        page.get_by_label("Referencia de la cotización", exact=True).fill(
            "Cotización sintética " + run
        )
        with page.expect_response(
            lambda r: r.url.endswith("/currency/quotes") and r.request.method == "POST"
        ) as quoted:
            page.get_by_role("button", name="Guardar cotización", exact=True).click()
        assert quoted.value.status == 201
        quote_body = quoted.value.request.post_data_json
        receipt = quoted.value.json()
        assert (receipt["amount_usd"], receipt["amount_ves"]) == ("0.01", "0.02")
        assert not receipt["payment_confirmed"] and receipt["quotation_only"]
        region = page.get_by_role("region", name="Cotización conservada", exact=True)
        expect(region).to_contain_text("Bs. 0,02")
        expect(page).to_have_url(re.compile(r"\?quote=" + receipt["id"]))
        passed(
            "browser quotation uses half-up rounding and saves a recoverable receipt"
        )

        review("2,5")
        with page.expect_response(
            lambda r: r.url.endswith("/currency/rates") and r.request.method == "POST"
        ) as corrected:
            page.get_by_role("button", name="Confirmar tasa", exact=True).click()
        assert corrected.value.status == 201
        second_rate = corrected.value.json()
        expect(page.get_by_role("dialog")).to_have_count(0)
        assert second_rate["previous_rate_id"] == first_rate["id"]
        assert second_rate["revision"] == first_rate["revision"] + 1
        expect(region).to_contain_text("Bs. 0,02")
        page.reload(wait_until="domcontentloaded")
        expect(region).to_contain_text("Bs. 0,02", timeout=20000)
        assert call("GET", "/currency/quotes/" + receipt["id"]) == receipt
        passed("rate correction and full reload preserve the original quotation")

        assert call("POST", "/currency/rates", rate_body, expected=201) == first_rate
        assert call("POST", "/currency/quotes", quote_body, expected=201) == receipt
        stale = {**quote_body, "request_key": str(uuid4())}
        call("POST", "/currency/quotes", stale, expected=412)
        assert (
            sql("SELECT count(*) FROM usd_ves_quotes WHERE id='" + receipt["id"] + "'")
            == "1"
        )
        passed(
            "retries reuse the original records and a stale rate cannot create a new quote"
        )

        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(
            path=str(out / "currency-mobile.png"), full_page=True, animations="disabled"
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        review("3,5")
        page.screenshot(
            path=str(out / "currency-review-mobile.png"),
            full_page=True,
            animations="disabled",
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.get_by_role("button", name="Cancelar", exact=True).click()
        passed(
            "colorful mobile page and review dialog fit the viewport without overflow"
        )

        operator_context, operator, operations = login("OPERADOR")
        operator.goto(base + "/manager/admin/currency", wait_until="domcontentloaded")
        expect(
            operator.get_by_text(
                "Solo gerencia y superadministración pueden registrar tasas.",
                exact=True,
            )
        ).to_be_visible()
        expect(operator.get_by_label("Bolívares por 1 USD", exact=True)).to_have_count(
            0
        )
        denied = {
            **rate_body,
            "request_key": str(uuid4()),
            "previous_rate_id": second_rate["id"],
        }
        call(
            "POST",
            "/currency/rates",
            denied,
            expected=403,
            headers=operations,
            client=operator,
        )
        call(
            "GET",
            "/currency/quotes/" + receipt["id"],
            expected=403,
            headers=operations,
            client=operator,
        )
        passed(
            "operator UI and real API deny rate changes and another account's receipt"
        )
        operator_context.close()
        context.close()
        browser.close()

    after = legacy_snapshot()
    assert before == after, "Legacy amounts or settings changed"
    passed("legacy orders, accounting, withdrawals and platform settings are unchanged")
    assert not errors, errors
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "run": run,
                "rate_ids": [first_rate["id"], second_rate["id"]],
                "quote_id": receipt["id"],
                "synthetic_rates_only": True,
                "automatic_bcv_verified": False,
                "legacy_snapshot_before": before,
                "legacy_snapshot_after": after,
                "bank_transfer_performed": False,
                "external_messages_sent": False,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

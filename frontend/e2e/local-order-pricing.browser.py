"""Real exact-USD form flow, restricted to the marked disposable local lab."""

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
    ), "Dedicated lab marker required before any writes"
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
            result = page.request.fetch(
                api + path, method=method, headers=headers, data=body
            )
            assert result.status == status, (method, path, result.status, result.text())
            return result.json()

        me = call("GET", "/auth/me")
        assert me["id"] == sql(
            "SELECT id FROM users WHERE email='admin.local-test@example.com'"
        )
        passed("real API identity and marked laboratory verified")

        page.goto(
            base + "/manager/operations/orders/new", wait_until="domcontentloaded"
        )
        page.get_by_placeholder("Ej: Juan Pérez").fill("Exact USD " + run)
        page.get_by_placeholder("Nombre y teléfono").fill("Local synthetic contact")
        page.get_by_placeholder("Calle, Número, Local", exact=True).fill(
            "Synthetic pickup"
        )
        page.get_by_placeholder("Calle, Número, Apartamento", exact=True).fill(
            "Synthetic destination"
        )
        page.get_by_placeholder("Nombre del producto").fill("Decimal product")
        numbers = page.get_by_role("spinbutton")
        numbers.nth(0).fill("3")
        numbers.nth(1).fill("0.10")
        numbers.nth(2).fill("0.20")
        save = page.get_by_role("button", name="Crear Orden", exact=True)
        expect(save).to_be_enabled()
        page.screenshot(path=str(out / "new-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.screenshot(path=str(out / "new-mobile.png"), full_page=True)
        save.scroll_into_view_if_needed()
        expect(save).to_be_visible()
        page.screenshot(
            path=str(out / "new-mobile-summary.png"),
            full_page=True,
            animations="disabled",
        )
        passed("colorful USD form fits desktop and mobile without horizontal overflow")
        numbers.nth(1).fill("0.001")
        expect(save).to_be_disabled()
        expect(page.get_by_text("Por confirmar", exact=True).first).to_be_visible()
        numbers.nth(1).fill("0.10")
        passed("invalid decimal precision stays unconfirmed and blocks submission")
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/api/v1/orders")
        ) as posted:
            save.click()
        result = posted.value
        assert result.status == 201, result.text()
        sent = result.request.post_data_json
        assert (sent["subtotal"], sent["delivery_fee"], sent["total"]) == (
            "0.30",
            "0.20",
            "0.50",
        )
        order = result.json()
        oid = order["id"]
        assert re.fullmatch(r"[0-9a-f-]{36}", oid)
        assert order["pricing"]["total"] == "0.50" and order["pricing"]["revision"] == 1
        assert (
            sql(
                "SELECT subtotal_exact::text||':'||delivery_fee_exact::text||':'||total_exact::text||':'||pricing_revision FROM orders WHERE id='"
                + oid
                + "'"
            )
            == "0.30:0.20:0.50:1"
        )
        passed(
            "form submits canonical decimal strings and PostgreSQL stores exact 0.30 + 0.20 = 0.50"
        )
        page.wait_for_url(base + "/manager/operations/orders/" + oid, timeout=30000)
        page.goto(
            base + "/manager/operations/orders/" + oid + "/edit",
            wait_until="domcontentloaded",
        )
        numbers = page.get_by_role("spinbutton")
        expect(numbers.nth(1)).to_have_value("0.10")
        expect(numbers.nth(2)).to_have_value("0.20")
        numbers.nth(2).fill("0.30")
        with page.expect_response(
            lambda r: r.request.method == "PATCH"
            and r.url.endswith("/api/v1/orders/" + oid)
        ) as patched:
            page.get_by_role("button", name=re.compile("Guardar cambios", re.I)).click()
        assert patched.value.status == 200, patched.value.text()
        assert patched.value.request.post_data_json["expected_pricing_revision"] == 1
        assert patched.value.json()["pricing"]["revision"] == 2
        assert patched.value.json()["pricing"]["total"] == "0.60"
        passed(
            "edit reloads exact prices, submits the loaded revision and confirms revision two"
        )
        page.wait_for_url(base + "/manager/operations/orders/" + oid, timeout=30000)
        page.goto(
            base + "/manager/operations/orders/" + oid + "/edit",
            wait_until="domcontentloaded",
        )
        numbers = page.get_by_role("spinbutton")
        expect(numbers.nth(2)).to_have_value("0.30")
        call(
            "PATCH",
            "/orders/" + oid,
            {"delivery_fee": "0.40", "expected_pricing_revision": 2},
        )
        numbers.nth(2).fill("0.50")
        with page.expect_response(
            lambda r: r.request.method == "PATCH"
            and r.url.endswith("/api/v1/orders/" + oid)
        ) as stale:
            page.get_by_role("button", name=re.compile("Guardar cambios", re.I)).click()
        assert stale.value.status == 412
        expect(numbers.nth(2)).to_have_value("0.50")
        expect(
            page.get_by_role("alert").filter(has_text="precio cambió")
        ).to_be_visible()
        current = call("GET", "/orders/" + oid)
        assert (
            current["pricing"]["revision"] == 3
            and current["pricing"]["total"] == "0.70"
        )
        passed(
            "stale edit receives 412, preserves its draft and cannot overwrite the current price"
        )
        call(
            "PATCH",
            "/orders/" + oid,
            {"total": "0.00", "expected_pricing_revision": 3},
            status=422,
        )
        assert call("GET", "/orders/" + oid)["pricing"] == current["pricing"]
        passed("tampered zero total is rejected atomically")
        report = call("GET", "/financial/reports/orders")
        assert report["exact_order_pricing"]["scope"] == "exact_usd_only"
        assert report["exact_order_pricing"]["order_count"] >= 1
        passed(
            "financial report identifies its exact-only USD subset separately from legacy totals"
        )
        page.screenshot(path=str(out / "edit-conflict-mobile.png"), full_page=True)
        assert not errors, errors
        context.close()
        browser.close()
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "order_id": oid,
                "instance": state["instance"],
                "bank_transfer_performed": False,
            },
            indent=2,
        )
    )
    print(json.dumps({"checks": len(checks), "errors": errors}))


if __name__ == "__main__":
    main()

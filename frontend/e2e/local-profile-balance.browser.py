"""Read canonical staff profile balances in the retained marked laboratory."""

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
    passed(
        "marked laboratory and private rider identity confirmed before balance reads"
    )

    def cash(value):
        assert isinstance(value, str) and re.fullmatch(
            r"-?(?:0|[1-9][0-9]*)\.[0-9]{2}", value
        )
        negative = value.startswith("-")
        units, cents = value.lstrip("-").split(".")
        return (
            ("−" if negative else "")
            + "USD "
            + re.sub(r"\B(?=(\d{3})+(?!\d))", ".", units)
            + ","
            + cents
        )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        for role in ("SUPERADMIN", "GERENTE", "OPERADOR"):
            context = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                locale="es-VE",
                timezone_id="America/Caracas",
                reduced_motion="reduce",
            )
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
            page.locator("input[type=email]").fill(users[role]["email"])
            page.locator("input[type=password]").fill(users[role]["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(
                base + ("/operator" if role == "OPERADOR" else "/manager"),
                timeout=30000,
            )
            token = page.evaluate('localStorage.getItem("access_token")')
            assert token
            headers = {"Authorization": "Bearer " + token}
            rider_id = life["rider_id"]
            path = "/payouts/riders/" + rider_id + "/balance/exact"
            response = page.request.get(api + path, headers=headers)
            if role == "OPERADOR":
                assert response.status == 403
                start = len(reads)
                page.goto(
                    base + "/manager/fleet/riders/" + rider_id,
                    wait_until="domcontentloaded",
                )
                panel = page.get_by_role("region", name="Resumen financiero informado")
                expect(panel).to_contain_text(
                    "requiere acceso de gerencia", timeout=30000
                )
                expect(panel.get_by_text("Saldo del libro USD", exact=True)).to_have_count(0)
                expect(panel.get_by_text("Reservas de retiro", exact=True)).to_have_count(0)
                expect(panel.get_by_text("Disponible contable", exact=True)).to_have_count(0)
                expect(panel.locator("dd")).to_have_count(0)
                assert not any(path.lstrip("/") == value for value in reads[start:])
                passed(
                    "operator: operational profile remains available without a financial request or cached money"
                )
                context.close()
                continue
            assert response.status == 200
            value = response.json()
            me = page.request.get(api + "/auth/me", headers=headers).json()
            assert (
                value["scope"] == "staff_canonical_usd_balance"
                and value["rider_id"] == rider_id
            )
            assert value["actor"] == {"user_id": me["id"], "role": role}
            assert value["bank_verified"] is False
            assert all(
                isinstance(value[k], str)
                for k in ("ledger_balance", "reserved", "available")
            )
            passed(
                role
                + ": actual canonical response binds target rider, owner and authenticated financial actor"
            )
            page.goto(
                base + "/manager/fleet/riders/" + rider_id,
                wait_until="domcontentloaded",
            )
            panel = page.get_by_role("region", name="Resumen financiero informado")
            expect(
                panel.get_by_text(cash(value["available"]), exact=True).first
            ).to_be_visible(timeout=30000)
            expect(panel).to_contain_text(cash(value["ledger_balance"]))
            expect(panel).to_contain_text(cash(value["reserved"]))
            expect(panel).to_contain_text("America/Caracas")
            expect(panel).to_contain_text("No confirma un pago bancario")
            passed(
                role
                + ": profile shows real ledger, reservations and availability in exact USD with a Caracas cut"
            )
            context.route(
                "**/api/v1" + path,
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"synthetic read failure"}',
                ),
            )
            page.get_by_role("button", name="Actualizar saldo", exact=True).click()
            expect(panel.get_by_role("alert")).to_contain_text(
                "última lectura confirmada", timeout=30000
            )
            expect(
                page.get_by_role("region", name="Identidad del repartidor")
            ).to_be_visible()
            expect(panel).to_contain_text(cash(value["available"]))
            passed(
                role
                + ": financial refresh failure keeps the operational profile and explicitly marks the last confirmed reading"
            )
            context.unroute("**/api/v1" + path)
            page.get_by_role("button", name="Reintentar saldo", exact=True).click()
            expect(panel.get_by_role("alert")).to_have_count(0, timeout=30000)
            expect(panel).to_contain_text(cash(value["available"]))
            passed(
                role
                + ": retry recovers by GET without repeating an operational or monetary mutation"
            )
            page.screenshot(
                path=str(out / (role.lower() + "-profile-balance-desktop.png")),
                full_page=True,
                animations="disabled",
            )
            page.set_viewport_size({"width": 390, "height": 844})
            panel.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1")
            page.screenshot(
                path=str(out / (role.lower() + "-profile-balance-mobile.png")),
                animations="disabled",
            )
            passed(
                role
                + ": financial profile remains readable on desktop and mobile without horizontal overflow"
            )
            context.close()
        browser.close()
    assert before == snapshot() and not errors and not writes
    passed(
        "all original operational and monetary table hashes preserved; zero business writes or browser exceptions"
    )
    assert len(checks) == 13, checks
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

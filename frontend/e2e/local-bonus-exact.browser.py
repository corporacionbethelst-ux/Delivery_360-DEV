"""Read exact configuration and owner bonus screens in the marked retained lab."""

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
        "marked laboratory and private lifecycle identity confirmed before read-only checks"
    )
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
            page.on("pageerror", lambda e: errors.append(str(e)))

            def guard(route):
                request = route.request
                path = request.url.split("/api/v1/", 1)[-1].split("?", 1)[0]
                if request.method not in ("GET", "OPTIONS") and path not in (
                    "auth/login",
                    "auth/refresh",
                    "settings/simulate-bonus/exact/v2",
                ):
                    writes.append({"method": request.method, "path": path})
                    route.abort()
                    return
                if (
                    path == "settings/simulate-bonus/exact/v2"
                    and request.method == "POST"
                ):
                    readonly_posts.append(path)
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

        def get(page, headers, path, status=200):
            r = page.request.get(api + path, headers=headers)
            assert r.status == status, (path, r.status)
            return r.json()

        for role in ["SUPERADMIN", "GERENTE"]:
            page, context, headers = login(users[role], "/manager")
            me = get(page, headers, "/auth/me")
            settings = get(page, headers, "/settings/exact/v2")
            assert (
                settings["version"] == 2
                and settings["currency"] == "USD"
                and settings["revision"].startswith("s2-")
                and isinstance(settings["rider_delivery_bonus"], str)
            )
            page.goto(base + "/manager/admin/settings", wait_until="domcontentloaded")
            field = page.get_by_role("textbox", name=re.compile("^Bono por entrega"))
            expect(field).to_have_value(settings["rider_delivery_bonus"], timeout=30000)
            passed(
                role
                + ": current monetary parameters are exact USD strings with a raw-JSON revision"
            )
            if role == "SUPERADMIN":
                field.fill("0.001")
                page.get_by_role("button", name="Revisar cambios", exact=True).click()
                expect(page.locator("main main").get_by_role("alert")).to_contain_text(
                    "dos decimales"
                )
                expect(page.get_by_role("dialog")).to_have_count(0)
                field.fill(
                    "1.23" if settings["rider_delivery_bonus"] != "1.23" else "1.24"
                )
                page.get_by_role("button", name="Revisar cambios", exact=True).click()
                dialog = page.get_by_role(
                    "dialog", name="Confirmar cambios de configuración", exact=True
                )
                expect(dialog).to_be_visible()
                dialog.get_by_role("button", name="Cancelar", exact=True).click()
                page.get_by_role(
                    "button", name="Recargar configuración", exact=True
                ).click()
                page.get_by_role(
                    "dialog", name="Recargar configuración", exact=True
                ).get_by_role(
                    "button", name="Descartar borrador y recargar", exact=True
                ).click()
                expect(field).to_have_value(settings["rider_delivery_bonus"])
                passed(
                    "SUPERADMIN: overprecision is blocked locally and reviewed valid changes can be cancelled without PATCH"
                )
            else:
                expect(field).to_be_disabled()
                expect(
                    page.get_by_role("button", name="Revisar cambios", exact=True)
                ).to_have_count(0)
                passed(
                    "GERENTE: exact configuration is readable and simulation is allowed without a save control"
                )
            proposals = []

            def response(r):
                if (
                    r.url.endswith("/settings/simulate-bonus/exact/v2")
                    and r.status == 200
                ):
                    proposals.append(r.json())

            page.on("response", response)
            page.get_by_label("Bono propuesto", exact=True).fill("0,10")
            page.get_by_role("button", name="Simular impacto", exact=True).click()
            region = page.get_by_role(
                "region", name="Resultado confirmado de simulación", exact=True
            )
            expect(region).to_be_visible(timeout=30000)
            assert proposals and proposals[-1]["actor"] == {
                "user_id": me["id"],
                "role": role,
            }
            result = proposals[-1]
            assert (
                result["applied_bonus"] == "0.10"
                and result["settings_revision"] == settings["revision"]
            )
            assert result["candidate_deliveries"] == result[
                "completed_deliveries"
            ] + result["failed_bonus_deliveries"] + sum(result["exclusions"].values())
            assert (
                isinstance(result["historical_cost"], str)
                and not result["bank_verified"]
            )
            expect(region).to_contain_text("USD")
            expect(region).to_contain_text("no confirma pagos")
            passed(
                role
                + ": real uniform-bonus calculation preserves text cents, actor, settings revision and explicit exclusions"
            )
            region.scroll_into_view_if_needed()
            page.screenshot(
                path=str(out / (role.lower() + "-scenario-desktop.png")),
                animations="disabled",
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function(
                "document.querySelector('aside').getBoundingClientRect().right<=1"
            )
            region.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            page.screenshot(
                path=str(out / (role.lower() + "-scenario-mobile.png")),
                animations="disabled",
            )
            passed(
                role
                + ": colorful settings and confirmed scenario fit mobile without horizontal overflow"
            )
            page.remove_listener("response", response)
        page, context, headers = login(account["account"], "/rider")
        me = get(page, headers, "/auth/me")
        profile = get(page, headers, "/riders/me")
        assert profile["id"] == life["rider_id"]
        ids = [str(UUID(v)) for v in life["created_order_ids"]]
        read = get(
            page, headers, "/deliveries/bonuses/exact?order_ids=" + ",".join(ids)
        )
        assert (
            read["actor"] == {"user_id": me["id"], "role": "REPARTIDOR"}
            and not read["ledger_credit_included"]
            and not read["available_balance_included"]
        )
        recorded = next(
            r
            for r in read["records"]
            if r["status"] == "COMPLETADA" and r["amount"] == "2.50"
        )
        absent = next(
            r
            for r in read["records"]
            if r["status"] == "FALLIDA" and r["amount"] is None
        )
        assert absent["currency"] is None and recorded["currency"] == "USD"
        passed(
            "rider: one real bounded read preserves completed USD bonuses and a nonbonifiable absence without inventing zero"
        )
        page.goto(base + "/rider/productivity", wait_until="domcontentloaded")
        panel = page.get_by_role("region", name="Bono conservado", exact=True).first
        expect(panel.get_by_text("2,50 USD", exact=True).first).to_be_visible(
            timeout=30000
        )
        assert "deliveries/bonuses/exact" in reads
        passed(
            "rider productivity uses a scoped exact bonus batch instead of numeric breakdown arithmetic"
        )
        page.goto(
            base + "/rider/my-orders/" + recorded["order_id"],
            wait_until="domcontentloaded",
        )
        panel = page.get_by_role("region", name="Bono conservado", exact=True)
        expect(panel.get_by_text("2,50 USD", exact=True).first).to_be_visible(
            timeout=30000
        )
        expect(panel).to_contain_text("Componentes guardados, sin recalcular")
        expect(panel.get_by_text("COP", exact=False)).to_have_count(0)
        passed(
            "rider order detail displays only the stored bonus unit and does not call it available balance or bank payment"
        )
        panel.scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "rider-bonus-desktop.png"), animations="disabled"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right<=1"
        )
        panel.scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
        page.screenshot(path=str(out / "rider-bonus-mobile.png"), animations="disabled")
        passed(
            "rider: stored bonus and optional components remain readable on a narrow screen"
        )

        def offline(route):
            route.fulfill(status=503, json={"detail": "Synthetic bonus read outage"})

        context.route("**/api/v1/deliveries/bonuses/exact?*", offline)
        page.reload(wait_until="domcontentloaded")
        expect(
            page.get_by_role("button", name="Reintentar bono", exact=True)
        ).to_be_visible(timeout=30000)
        expect(panel.get_by_text("0,00 USD", exact=True)).to_have_count(0)
        context.unroute("**/api/v1/deliveries/bonuses/exact?*", offline)
        page.get_by_role("button", name="Reintentar bono", exact=True).click()
        expect(panel.get_by_text("2,50 USD", exact=True).first).to_be_visible(
            timeout=30000
        )
        passed(
            "rider: a failed bonus read never becomes zero and explicit retry recovers without repeating a delivery mutation"
        )
        page.goto(
            base + "/rider/my-orders/" + absent["order_id"],
            wait_until="domcontentloaded",
        )
        expect(
            page.get_by_role("region", name="Bono conservado", exact=True)
        ).to_contain_text("Sin importe de bono guardado", timeout=30000)
        expect(
            page.get_by_role("region", name="Bono conservado", exact=True).get_by_text(
                "0,00 USD", exact=True
            )
        ).to_have_count(0)
        passed(
            "rider: nonbonifiable closure remains an absent bonus in the real UI, not a zero-valued USD payment"
        )
        for c in contexts:
            c.close()
        browser.close()
    assert before == snapshot(), "Existing database records changed"
    assert not writes and not errors, (writes, errors)
    passed(
        "all original table hashes preserved; zero business writes or JavaScript exceptions"
    )
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "writes": writes,
                "readonly_posts": readonly_posts,
                "reads": reads,
                "history_preserved": True,
                "instance": state["instance"],
                "bank_transfer_performed": False,
                "external_messages_sent": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

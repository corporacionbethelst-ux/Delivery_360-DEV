"""Exact management reports: real sessions, same-snapshot CSV and zero monetary writes."""

import argparse, csv, hashlib, io, json, re, subprocess, sys, time
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from playwright.sync_api import sync_playwright, expect


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chromium", default="/usr/bin/chromium")
    p.add_argument("--artifacts-dir", required=True)
    p.add_argument("--wait-request-window", action="store_true")
    args = p.parse_args()
    state = local_test.configuration()
    cmd = local_test.compose(state, local_test.local_docker())
    env = local_test.compose_environment()

    def sql(q):
        return subprocess.check_output(
            cmd
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
    if args.wait_request_window:
        time.sleep(60)
        time.sleep(1)
    accounts = json.loads(local_test.ACCOUNTS.read_text())
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    writes = []
    reads = []

    def passed(name):
        checks.append(name)
        print("passed:", name, flush=True)

    def snapshot():
        return {
            t: sql(
                "SELECT count(*)::text||':'||md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM "
                + t
                + " t"
            )
            for t in (
                "orders",
                "financials",
                "financial_transactions",
                "rider_wallets",
                "payouts",
                "payout_status_history",
                "bcv_rates",
                "customer_collections",
                "customer_collection_reviews",
                "customer_refunds",
                "customer_refund_events",
            )
        }

    before = snapshot()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        def login(role):
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                locale="es-VE",
                timezone_id="America/Caracas",
                accept_downloads=True,
            )
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.locator("input[type=email]").fill(accounts[role]["email"])
            page.locator("input[type=password]").fill(accounts[role]["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(
                re.compile("/(?:manager|dashboard|auditor)(?:/|$)"), timeout=30000
            )
            token = page.evaluate('localStorage.getItem("access_token")')
            assert token
            return ctx, page, {"Authorization": "Bearer " + token}

        ctx, page, headers = login("SUPERADMIN")
        me = page.request.get(api + "/auth/me", headers=headers).json()
        assert me["id"] == sql(
            "SELECT id FROM users WHERE email='" + accounts["SUPERADMIN"]["email"] + "'"
        )
        passed(
            "real staff session matches the dedicated database and report is read-only"
        )

        def request(params=""):
            response = page.request.get(
                api + "/financial/reports/exact" + params, headers=headers
            )
            assert response.status == 200, response.text()
            return response.json()

        value = request()
        assert (
            value["rows"]
            and value["orders"]["count"]
            and value["ledger"]["count"]
            and value["payouts"]["count"]
        ), "Run the prior native fixture flows first"
        assert (
            value["row_count"] == len(value["rows"])
            and value["export_complete"]
            and not value["bank_verified"]
        )
        assert Decimal(value["ledger"]["credit_usd"]) - Decimal(
            value["ledger"]["debit_usd"]
        ) + Decimal(value["ledger"]["adjustment_usd"]) == Decimal(
            value["ledger"]["net_change_usd"]
        )
        assert Decimal(value["orders"]["subtotal_usd"]) + Decimal(
            value["orders"]["delivery_fee_usd"]
        ) == Decimal(value["orders"]["total_usd"])
        assert sum(
            Decimal(s["amount_usd"]) for s in value["payouts"]["by_status"]
        ) == Decimal(value["payouts"]["amount_usd"])
        passed(
            "API separates exact order prices, canonical ledger directions and withdrawal cohorts without double counting"
        )

        def track(request):
            if "/api/v1/" not in request.url:
                return
            if request.method not in ("GET", "OPTIONS"):
                writes.append(request.method + " " + request.url)
            elif "/financial/" in request.url:
                reads.append(request.url)

        page.on("request", track)
        page.goto(base + "/manager/financial/reports", wait_until="domcontentloaded")
        region = page.get_by_role(
            "region", name="Reporte exacto confirmado", exact=True
        )
        expect(region).to_be_visible(timeout=30000)
        expect(
            page.get_by_role("heading", name="Reportes y exportación exactos")
        ).to_be_visible()
        expect(
            page.get_by_text(re.compile("Los precios no equivalen a ingresos cobrados"))
        ).to_be_visible()
        passed(
            "production report shows three distinct sources, exclusions and the correct monetary meaning"
        )
        initial = len(reads)
        with page.expect_download() as dl:
            page.get_by_role("button", name="Exportar CSV completo", exact=True).click()
        target = out / "exact-financial.csv"
        dl.value.save_as(target)
        rows = list(csv.DictReader(io.StringIO(target.read_text(encoding="utf-8-sig"))))
        assert len(rows) == value["row_count"] and {r["key"] for r in rows} == {
            r["key"] for r in value["rows"]
        }
        assert len(reads) == initial
        assert len({r["huella_sha256"] for r in rows}) == 1 and all(
            r["filas_completas"] == str(value["row_count"]) for r in rows
        )
        assert {r["kind"] for r in rows} == {"ORDEN", "MOVIMIENTO", "RETIRO"}
        for original, exported in zip(value["rows"], rows):
            for field in (
                "subtotal_usd",
                "delivery_fee_usd",
                "total_usd",
                "amount_usd",
                "delta_usd",
            ):
                expected = original[field] or ""
                if expected.startswith("-"):
                    expected = "'" + expected
                assert exported[field] == expected, field
        passed(
            "complete CSV preserves every source amount and exclusion from one loaded snapshot without refetching"
        )
        page.get_by_label("Mostrar fuente", exact=True).select_option("ORDEN")
        with page.expect_download() as dl:
            page.get_by_role("button", name="Exportar CSV completo", exact=True).click()
        other = out / "exact-all-sources.csv"
        dl.value.save_as(other)
        assert (
            len(
                list(csv.DictReader(io.StringIO(other.read_text(encoding="utf-8-sig"))))
            )
            == value["row_count"]
            and len(reads) == initial
        )
        passed(
            "table source selection does not truncate or change the full exported snapshot"
        )
        # A real empty historical range; undated records remain visible as exclusions.
        page.get_by_label("Desde", exact=True).fill("2001-01-01")
        page.get_by_label("Hasta", exact=True).fill("2001-01-01")
        expect(
            page.get_by_role("button", name="Exportar CSV completo")
        ).to_be_disabled()
        expect(region).not_to_be_visible()
        page.get_by_role("button", name="Aplicar consulta", exact=True).click()
        expect(region).to_be_visible()
        empty = request("?date_from=2001-01-01&date_to=2001-01-01")
        assert (
            empty["orders"]["count"] == 0
            and empty["ledger"]["count"] == 0
            and empty["payouts"]["count"] == 0
        )
        passed(
            "editing filters removes stale figures and a genuine empty dated range remains distinct from failure"
        )
        # Restore the exact confirmed dates, without using a browser-time default.
        page.get_by_label("Desde", exact=True).fill(value["date_from"])
        page.get_by_label("Hasta", exact=True).fill(value["date_to"])
        page.get_by_role("button", name="Aplicar consulta").click()
        expect(region).to_be_visible()
        page.get_by_label("Mostrar fuente", exact=True).select_option("TODOS")
        page.screenshot(path=str(out / "reports-desktop.png"))
        page.goto(base + "/manager/financial/resumen", wait_until="domcontentloaded")
        expect(region).to_be_visible(timeout=30000)
        expect(
            page.get_by_role("heading", name="Resumen financiero exacto")
        ).to_be_visible()
        assert all("/reports/exact" in url for url in reads), reads
        passed(
            "summary uses the same decimal endpoint and neither screen requests legacy Float totals"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right<=1"
        )
        expect(
            page.get_by_role("heading", name="Resumen financiero exacto")
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(out / "summary-mobile.png"))
        passed(
            "colorful financial screens remain readable on desktop and mobile without viewport overflow"
        )
        page.route(
            "**/api/v1/financial/reports/exact?**",
            lambda r: r.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "Reporte temporalmente no disponible"}),
            ),
        )
        page.get_by_role("button", name="Aplicar consulta").click()
        expect(
            page.get_by_role("alert").filter(
                has_text="Reporte temporalmente no disponible"
            )
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Exportar CSV completo")
        ).to_be_disabled()
        expect(region).not_to_be_visible()
        passed(
            "a failed request exposes an error and cannot export obsolete or invented zero figures"
        )
        assert not errors and not writes, (errors, writes)
        ctx.close()
        audit_ctx = browser.new_context()
        auth = audit_ctx.request.post(
            api + "/auth/login",
            form={
                "username": accounts["AUDITOR"]["email"],
                "password": accounts["AUDITOR"]["password"],
            },
        )
        assert auth.status == 200, "Auditor API authentication failed"
        audit_headers = {"Authorization": "Bearer " + auth.json()["access_token"]}
        response = audit_ctx.request.get(
            api + "/financial/reports/exact", headers=audit_headers
        )
        assert response.status == 403
        audit_ctx.close()
        passed(
            "auditor retains its dedicated customer-book permissions and cannot access management report sources"
        )
        browser.close()
    assert before == snapshot(), "Reports changed financial history"
    passed(
        "orders, customer history, withdrawals and both rider books retain identical hashes; zero report writes"
    )
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "writes": writes,
                "history_preserved": True,
                "rows": value["row_count"],
                "excluded": value["excluded_count"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

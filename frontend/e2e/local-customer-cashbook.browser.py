"""Read-only verified customer book, exact CSV and responsive UI in the marked lab."""

import argparse, csv, io, json, re, subprocess, sys, time
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
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    accounts = json.loads(local_test.ACCOUNTS.read_text())
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    checks = []
    errors = []
    writes = []

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
            for t in [
                "customer_collections",
                "customer_collection_reviews",
                "customer_refunds",
                "customer_refund_events",
                "financials",
                "financial_transactions",
                "rider_wallets",
                "payouts",
                "payout_status_history",
            ]
        }

    before = snapshot()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="es-VE",
            timezone_id="America/Caracas",
            accept_downloads=True,
        )
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/login", wait_until="domcontentloaded")
        page.locator("input[type=email]").fill(accounts["SUPERADMIN"]["email"])
        page.locator("input[type=password]").fill(accounts["SUPERADMIN"]["password"])
        page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
        page.wait_for_url(re.compile("/manager(?:/|$)"), timeout=30000)
        token = page.evaluate('localStorage.getItem("access_token")')
        assert token
        # Login is complete. Every action from here must be read-only.
        page.on(
            "request",
            lambda r: (
                writes.append(r.method + " " + r.url)
                if "/api/v1/" in r.url and r.method not in ["GET", "OPTIONS"]
                else None
            ),
        )

        def get(params=""):
            r = page.request.get(
                api + "/customer-cashbook/report" + params,
                headers={"Authorization": "Bearer " + token},
            )
            assert r.status == 200, r.text()
            return r.json()

        value = get()
        assert value[
            "rows"
        ], "Run verified collection/refund fixture flows before this report test"
        assert value["summary"]["collection_count"] and value["summary"]["refund_count"]
        assert Decimal(value["summary"]["collection_usd"]) - Decimal(
            value["summary"]["refund_usd"]
        ) == Decimal(value["summary"]["net_usd"])
        passed(
            "API returns exact customer credits and refunds, separate original currencies and manual verification"
        )
        page.goto(
            base + "/manager/financial/customer-cashbook", wait_until="domcontentloaded"
        )
        region = page.get_by_role("region", name="Libro confirmado", exact=True)
        expect(region).to_be_visible(timeout=30000)
        expect(
            page.get_by_role("heading", name="Libro de cobros y devoluciones")
        ).to_be_visible()
        passed("real production page loads the complete verified customer book")
        with page.expect_download() as download:
            page.get_by_role("button", name="Exportar CSV completo", exact=True).click()
        target = out / "verified-cashbook.csv"
        download.value.save_as(target)
        exported = list(
            csv.DictReader(io.StringIO(target.read_text(encoding="utf-8-sig")))
        )
        assert len(exported) == len(value["rows"])
        assert {r["verification_id"] for r in exported} == {
            r["verification_id"] for r in value["rows"]
        }
        assert all(
            r["filas_completas"] == str(len(value["rows"]))
            and r["verificacion"] == "MANUAL"
            for r in exported
        )
        # Rows and totals match one snapshot; generated timestamp differs only between API requests.
        assert all(
            r["amount_usd"] == s["amount_usd"]
            and r["amount_original"] == s["amount_original"]
            for r, s in zip(exported, value["rows"])
        )
        assert len({r["huella_sha256"] for r in exported}) == 1
        passed(
            "download contains all source rows, original exact amounts and one snapshot fingerprint"
        )
        page.get_by_label("Moneda recibida", exact=True).select_option("VES")
        expect(
            page.get_by_role("button", name="Exportar CSV completo")
        ).to_be_disabled()
        expect(region).not_to_be_visible()
        page.get_by_role("button", name="Aplicar consulta", exact=True).click()
        expect(region).to_be_visible()
        ves = get("?currency=VES")
        assert ves["rows"] and all(r["original_currency"] == "VES" for r in ves["rows"])
        with page.expect_download() as download:
            page.get_by_role("button", name="Exportar CSV completo").click()
        path = out / "ves-cashbook.csv"
        download.value.save_as(path)
        ves_csv = list(
            csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")))
        )
        assert len(ves_csv) == len(ves["rows"]) and all(
            r["original_currency"] == "VES" for r in ves_csv
        )
        passed(
            "editing filters clears stale figures and CSV includes only confirmed VES movements"
        )
        page.get_by_label("Caja o cuenta", exact=True).fill("NO-MOVEMENTS-DELIVERY96")
        page.get_by_role("button", name="Aplicar consulta").click()
        expect(region).to_be_visible()
        expect(
            page.get_by_text(
                "No hay movimientos verificados para estos filtros.", exact=True
            )
        ).to_be_visible()
        passed(
            "empty filtered result is distinguished from unavailable or failed reports"
        )
        page.get_by_label("Caja o cuenta", exact=True).fill("")
        page.get_by_role("button", name="Aplicar consulta").click()
        expect(region).to_be_visible()
        page.screenshot(path=str(out / "cashbook-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        expect(
            page.get_by_role("heading", name="Libro de cobros y devoluciones")
        ).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), "Page overflow outside scrollable table"
        page.screenshot(path=str(out / "cashbook-mobile.png"), full_page=True)
        passed("desktop and mobile layout remain readable without viewport overflow")
        page.route(
            "**/api/v1/customer-cashbook/report?**",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "Reporte temporalmente no disponible"}),
            ),
        )
        page.get_by_role("button", name="Aplicar consulta").click()
        expect(page.get_by_role("alert")).to_be_visible()
        expect(
            page.get_by_role("button", name="Exportar CSV completo")
        ).to_be_disabled()
        expect(region).not_to_be_visible()
        passed("failed request shows an error and prevents exporting obsolete figures")
        assert not errors and not writes, (errors, writes)
        ctx.close()
        browser.close()
    assert before == snapshot(), "Read-only book changed monetary history"
    passed(
        "all customer and rider monetary history hashes preserved; zero writes and JavaScript errors"
    )
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "writes": writes,
                "history_preserved": True,
                "rows": len(value["rows"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

"""Read-only manager orders regression: HTTP200 conflicting rider links must not hide orders."""

import argparse, csv, io, json, re, subprocess, sys, time
from pathlib import Path
from uuid import UUID
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifacts-dir", required=True)
    p.add_argument("--chromium", default="/usr/bin/chromium")
    p.add_argument("--wait-request-window", action="store_true")
    p.add_argument("--expect-original-error", action="store_true")
    args = p.parse_args()
    state = local_test.configuration()
    command = local_test.compose(state, local_test.local_docker())
    env = local_test.compose_environment()
    accounts = json.loads(local_test.ACCOUNTS.read_text())
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)

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
                "payouts",
                "payout_status_history",
                "rider_wallets",
                "financial_transactions",
                "customer_collections",
                "customer_refunds",
            )
        }

    before = snapshot()
    checks = []
    errors = []
    writes = []

    def passed(s):
        checks.append(s)
        print("passed:", s, flush=True)

    if args.wait_request_window:
        time.sleep(60)
        time.sleep(1)
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 1050}, accept_downloads=True
        )
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        account = accounts["SUPERADMIN"]
        page.goto(base + "/login", wait_until="domcontentloaded")
        page.locator("input[type=email]").fill(account["email"])
        page.locator("input[type=password]").fill(account["password"])
        page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
        page.wait_for_url(base + "/manager", timeout=30000)
        token = page.evaluate('localStorage.getItem("access_token")')
        assert token
        headers = {"Authorization": "Bearer " + token}

        def get(path):
            r = page.request.get(api + path, headers=headers)
            assert r.status == 200, (path, r.status)
            return r.json()

        assert get("/auth/me")["role"] == "SUPERADMIN"
        passed("real superadmin and marked PostgreSQL laboratory confirmed")
        orders = []
        for offset in range(0, 2000, 200):
            chunk = get("/orders?limit=200&offset=" + str(offset))
            orders += chunk
            if len(chunk) < 200:
                break
        else:
            raise AssertionError("Read-only test requires complete bounded catalog")
        riders = get("/riders?status_filter=ACTIVO")
        target = next(
            o
            for o in orders
            if o.get("pricing")
            and o.get("assigned_rider_id")
            and o.get("delivery")
            and o["delivery"]["rider_id"] == o["assigned_rider_id"]
        )
        other = next(r["id"] for r in riders if r["id"] != target["assigned_rider_id"])
        assert str(UUID(other)) == other
        passed(
            "actual coherent assigned order selected; synthetic conflict is injected only into its HTTP200 response"
        )
        mode = {"bad_price": False}
        observed = []

        def inject(route):
            response = route.fetch()
            assert response.status == 200
            rows = response.json()
            assert isinstance(rows, list)
            for i, row in enumerate(rows):
                if row["id"] == target["id"]:
                    changed = {
                        **row,
                        "delivery": {**row["delivery"], "rider_id": other},
                    }
                    if mode["bad_price"]:
                        changed["pricing"] = {**row["pricing"], "total": "99999999.99"}
                    rows[i] = changed
            route.fulfill(response=response, json=rows)

        page.route(re.compile(r"/api/v1/orders\?"), inject)

        def track(r):
            if (
                "/api/v1/" in r.url
                and "/auth/" not in r.url
                and r.method not in ("GET", "OPTIONS")
            ):
                writes.append(r.method + " " + r.url)
            if "/api/v1/orders?" in r.url and r.method == "GET":
                observed.append(r.url)

        page.on("request", track)
        page.goto(base + "/manager/operations/orders", wait_until="domcontentloaded")
        if args.expect_original_error:
            expect(
                page.get_by_text("No se pudieron cargar los datos.", exact=True)
            ).to_be_visible(timeout=20000)
            page.screenshot(path=str(out / "original-error.png"))
            assert not writes
            passed(
                "original generic failure reproduced with HTTP200 and mismatched delivery rider"
            )
            result = {
                "checks": checks,
                "errors": errors,
                "writes": writes,
                "original_bug_reproduced": True,
                "synthetic_response_conflict": True,
            }
        else:

            def ready():
                expect(page.get_by_role("article")).to_have_count(
                    len(orders), timeout=30000
                )

            ready()
            expect(
                page.get_by_text("No se pudieron cargar los datos.", exact=True)
            ).not_to_be_visible()
            passed(
                "complete order catalog stays visible including the conflicting row; no record is dropped"
            )
            bad = page.get_by_role(
                "article",
                name="Orden " + (target.get("external_id") or target["id"]),
                exact=True,
            )
            expect(
                bad.get_by_text("Asignación por revisar", exact=True)
            ).to_be_visible()
            expect(bad.get_by_role("button")).to_have_count(1)
            bad.get_by_role("button", name="Ver", exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible()
            expect(dialog.get_by_text(other, exact=True)).to_be_visible()
            expect(
                dialog.get_by_text(target["assigned_rider_id"], exact=True).first
            ).to_be_visible()
            page.screenshot(path=str(out / "review-desktop.png"))
            dialog.get_by_role("button", name="Cerrar revisión", exact=True).click()
            passed(
                "conflicting order shows both original rider references and offers no assignment, status or cancellation writes"
            )
            healthy = next(
                o
                for o in orders
                if o["id"] != target["id"]
                and o["status"] == "PENDIENTE"
                and not o.get("assigned_rider_id")
                and not o.get("delivery")
            )
            good = page.get_by_role(
                "article",
                name="Orden " + (healthy.get("external_id") or healthy["id"]),
                exact=True,
            )
            expect(
                good.get_by_role("button", name="Asignar", exact=True)
            ).to_be_enabled()
            passed("unaffected pending orders retain their normal operational controls")
            search = page.get_by_placeholder(
                "Buscar por ID, cliente, dirección o rider..."
            )
            search.fill(target.get("external_id") or target["id"])
            expect(page.get_by_role("article")).to_have_count(1)
            search.fill("")
            ready()
            with page.expect_download() as dl:
                page.get_by_role("button", name="Exportar", exact=True).click()
            csvpath = out / "orders-review.csv"
            dl.value.save_as(csvpath)
            rows = list(
                csv.DictReader(io.StringIO(csvpath.read_text(encoding="utf-8-sig")))
            )
            assert len(rows) == len(orders)
            badrow = next(
                r
                for r in rows
                if r["ID"] == (target.get("external_id") or target["id"])
            )
            assert (
                badrow["Repartidor_orden"] == target["assigned_rider_id"]
                and badrow["Repartidor_entrega"] == other
                and badrow["Rider"] == "Asignación por revisar"
                and "no coinciden" in badrow["Revision_asignacion"]
            )
            passed(
                "search and complete CSV preserve the review flag and conflicting references without inventing a rider"
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function(
                "document.querySelector('aside').getBoundingClientRect().right<=1"
            )
            search.fill(target.get("external_id") or target["id"])
            bad.get_by_role("button", name="Ver", exact=True).click()
            expect(dialog).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(out / "review-mobile.png"))
            dialog.get_by_role("button", name="Cerrar revisión", exact=True).click()
            page.set_viewport_size({"width": 1440, "height": 1050})
            passed("review dialog fits desktop and mobile without horizontal overflow")
            page.route(
                re.compile(r"/api/v1/riders\?status_filter=ACTIVO$"),
                lambda r: r.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({"detail": "Synthetic catalog outage"}),
                ),
            )
            page.reload(wait_until="domcontentloaded")
            ready()
            expect(
                page.get_by_text(
                    re.compile("No se pudieron cargar los repartidores.*HTTP 503")
                )
            ).to_be_visible()
            passed(
                "failed auxiliary rider catalog cannot hide successfully loaded orders"
            )
            page.unroute(re.compile(r"/api/v1/riders\?status_filter=ACTIVO$"))
            mode["bad_price"] = True
            page.reload(wait_until="domcontentloaded")
            expect(
                page.get_by_text(re.compile("No se pudieron cargar las órdenes"))
            ).to_be_visible(timeout=30000)
            expect(page.get_by_role("article")).to_have_count(0)
            expect(
                page.get_by_role("button", name="Exportar", exact=True)
            ).to_be_disabled()
            expect(
                page.get_by_text("No se encontraron órdenes.", exact=True)
            ).not_to_be_visible()
            mode["bad_price"] = False
            page.get_by_role("button", name="Reintentar", exact=True).click()
            ready()
            passed(
                "price corruption still blocks an unverified list; retry restores the complete operational review"
            )
            assert not writes and not errors, (writes, errors)
            passed(
                "zero business writes or JavaScript exceptions while reviewing orders"
            )
            result = {
                "checks": checks,
                "errors": errors,
                "writes": writes,
                "rows": len(orders),
                "synthetic_response_conflict": True,
                "no_database_conflict_created": True,
                "private_credentials_exported": False,
                "complete_catalog": True,
            }
        ctx.close()
        browser.close()
    assert snapshot() == before, "Read-only manager review changed records"
    result["history_preserved"] = True
    (out / "results.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

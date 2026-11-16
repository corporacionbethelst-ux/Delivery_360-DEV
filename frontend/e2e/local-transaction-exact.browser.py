"""Read-only decimal transaction history and detail with real staff sessions."""

import argparse, csv, io, json, re, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifacts-dir", required=True)
    p.add_argument("--chromium", default="/usr/bin/chromium")
    p.add_argument("--wait-request-window", action="store_true")
    args = p.parse_args()
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    state = local_test.configuration()
    cmd = local_test.compose(state, local_test.local_docker())
    env = local_test.compose_environment()
    accounts = json.loads(local_test.ACCOUNTS.read_text())

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
    literal = lambda s: (
        "'" + s
        if isinstance(s, str) and s.startswith("-")
        else s if s is not None else ""
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        for role in ("SUPERADMIN", "GERENTE"):
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 1050}, accept_downloads=True
            )
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/login", wait_until="domcontentloaded")
            a = accounts[role]
            page.locator("input[type=email]").fill(a["email"])
            page.locator("input[type=password]").fill(a["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(base + "/manager", timeout=30000)
            token = page.evaluate('localStorage.getItem("access_token")')
            assert token
            headers = {"Authorization": "Bearer " + token}

            def get(path):
                r = page.request.get(api + path, headers=headers)
                assert r.status == 200, (path, r.status)
                return r.json()

            me = get("/auth/me")
            assert me["role"] == role

            def track(r):
                if (
                    "/api/v1/" in r.url
                    and "/auth/" not in r.url
                    and r.method not in ("GET", "OPTIONS")
                ):
                    writes.append({"method": r.method, "path": r.url.split("?")[0]})

            page.on("request", track)
            page.goto(
                base + "/manager/financial/transactions", wait_until="domcontentloaded"
            )
            confirmed = page.get_by_role("region", name="Página confirmada")
            expect(confirmed).to_be_visible(timeout=30000)
            raw = get("/financial/transactions/exact/page?limit=51&offset=0")
            assert (
                raw["items"]
                and raw["viewer_user_id"] == me["id"]
                and raw["viewer_role"] == role
            )
            assert (
                not raw["bank_verified"]
                and not raw["available_balance_included"]
                and not raw["wallet_cents_included"]
            )
            passed(
                role
                + ": exact catalog, real actor and explicit registered-record scope"
            )
            with page.expect_download() as event:
                page.get_by_role(
                    "button", name="Exportar página CSV", exact=True
                ).click()
            file = out / (role.lower() + "-transactions.csv")
            event.value.save_as(str(file))
            rows = list(
                csv.DictReader(io.StringIO(file.read_text(encoding="utf-8-sig")))
            )
            by_id = {r["id"]: r for r in raw["items"]}
            assert len(rows) == min(len(raw["items"]), 50)
            for r in rows:
                original = by_id[r["id"]]
                for field, column in [
                    ("amount", "importe_registrado"),
                    ("balance_before", "saldo_anterior"),
                    ("balance_after", "saldo_posterior"),
                ]:
                    assert r[column] == literal(original[field])
                assert (
                    r["moneda"] == (original["currency"] or "")
                    and r["saldo_disponible_incluido"] == "false"
                    and r["verificado_por_banco"] == "false"
                    and len(r["huella_sha256"]) == 64
                )
            passed(
                role
                + ": CSV preserves exact strings, signs, missing snapshots and read metadata"
            )
            all_rows = get("/financial/transactions/exact/page?limit=500&offset=0")[
                "items"
            ]
            unknown = next(r for r in all_rows if r["currency_recorded"] is None)
            page.goto(
                base + "/manager/financial/transactions/" + unknown["id"],
                wait_until="domcontentloaded",
            )
            expect(
                page.get_by_role("region", name="Transacción confirmada")
            ).to_be_visible()
            expect(
                page.get_by_text("Moneda", exact=True).locator("..")
            ).to_contain_text("No informada")
            passed(
                role
                + ": historical unknown currency remains unknown without USD conversion"
            )
            target = raw["items"][0]["id"]
            page.goto(
                base + "/manager/financial/transactions/" + target,
                wait_until="domcontentloaded",
            )
            detail = page.get_by_role("region", name="Transacción confirmada")
            expect(detail).to_be_visible()
            expect(detail).to_contain_text("ID confirmado: " + target)
            expect(detail).to_contain_text("no son una confirmación bancaria")
            expect(detail).to_contain_text("no representan el saldo disponible actual")
            page.evaluate(
                "() => { window.printCalls=0;window.print=()=>{window.printCalls+=1;}; }"
            )
            page.get_by_role("button", name="Imprimir registro", exact=True).click()
            page.wait_for_function("window.printCalls===1")
            page.screenshot(
                path=str(out / (role.lower() + "-desktop.png")),
                full_page=True,
                animations="disabled",
            )
            passed(
                role + ": exact identity detail and honest read-only printable record"
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function(
                "document.querySelector('aside').getBoundingClientRect().right <= 1"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_text(
                "Importe registrado", exact=True
            ).scroll_into_view_if_needed()
            page.screenshot(
                path=str(out / (role.lower() + "-mobile.png")), animations="disabled"
            )
            passed(role + ": mobile cards and metadata fit without document overflow")
            mode = {"bad": True, "injected": False}

            def corrupt(route):
                if route.request.method != "GET":
                    route.continue_()
                    return
                response = route.fetch()
                assert response.status == 200
                if not mode["bad"]:
                    route.fulfill(response=response)
                    return
                changed = response.json()
                changed["items"][0]["amount"] = 1.23
                route.fulfill(response=response, json=changed)
                mode["injected"] = True

            page.route(
                re.compile(
                    r"/api/v1/financial/transactions/exact/" + target + r"(?:\?|$)"
                ),
                corrupt,
            )
            page.get_by_role("button", name="Consultar transacción", exact=True).click()
            error = page.get_by_role("alert").filter(
                has_text="No se pudo comprobar la transacción solicitada"
            )
            expect(error).to_be_visible()
            expect(detail).to_be_visible()
            expect(
                page.get_by_role("button", name="Imprimir registro", exact=True)
            ).to_be_disabled()
            deadline = time.monotonic() + 10
            while not mode["injected"] and time.monotonic() < deadline:
                page.wait_for_timeout(20)
            assert mode["injected"]
            passed(
                role
                + ": numeric impostor rejected, previous record retained and printing blocked"
            )
            mode["bad"] = False
            page.get_by_role("button", name="Reintentar lectura", exact=True).click()
            expect(
                page.get_by_role("button", name="Imprimir registro", exact=True)
            ).to_be_enabled()
            expect(error).to_have_count(0)
            expect(detail).to_have_attribute("aria-busy", "false")
            expect(detail).to_contain_text("ID confirmado: " + target)
            passed(role + ": clean exact retry fully recovers the confirmed record")
            ctx.close()
        browser.close()
    after = snapshot()
    assert after == before and not writes and not errors
    passed(
        "all registered history and source tables preserved; zero business writes and JS errors"
    )
    (out / "results.json").write_text(
        json.dumps(
            dict(
                checks=checks,
                errors=errors,
                writes=writes,
                history_preserved=True,
                before=before,
                after=after,
                bank_transfer_performed=False,
                external_messages_sent=False,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

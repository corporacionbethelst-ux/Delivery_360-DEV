"""Read-only exact payout pages, combined history and ownership with real sessions."""

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
        # A fresh auth window for this independent browser group.
        for _ in range(61):
            time.sleep(1)
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        staff_rows = []
        for role in ("SUPERADMIN", "GERENTE", "REPARTIDOR"):
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
            page.wait_for_url(
                base + ("/rider" if role == "REPARTIDOR" else "/manager"), timeout=30000
            )
            token = page.evaluate('localStorage.getItem("access_token")')
            assert token
            headers = {"Authorization": "Bearer " + token}

            def get(path, status=200):
                r = page.request.get(api + path, headers=headers)
                assert r.status == status, (path, r.status)
                return r.json()

            def track(r):
                if (
                    "/api/v1/" in r.url
                    and "/auth/" not in r.url
                    and r.method not in ("GET", "OPTIONS")
                ):
                    writes.append({"method": r.method, "path": r.url.split("?")[0]})

            page.on("request", track)
            owner = role == "REPARTIDOR"
            audience = "OWNER" if owner else "STAFF"
            page.goto(
                base
                + (
                    "/rider/earnings/payouts" if owner else "/manager/financial/payouts"
                ),
                wait_until="domcontentloaded",
            )
            expect(page.get_by_text("Página 1", exact=True)).to_be_visible(
                timeout=30000
            )
            raw = get("/payouts/exact/page?audience=" + audience + "&limit=50")
            assert raw["viewer_role"] == role
            if not owner:
                assert raw["items"]
                staff_rows = raw["items"]
            assert (
                not raw["bank_verified"]
                and not raw["available_balance_included"]
                and not raw["wallet_cents_included"]
            )
            assert all(
                isinstance(r["amount"], str) or r["amount"] is None
                for r in raw["items"]
            )
            if owner:
                assert all(
                    r["rider_id"] == raw["effective_rider_id"] for r in raw["items"]
                )
                assert raw["effective_rider_id"]
                foreign = next(
                    (
                        r
                        for r in staff_rows
                        if r["rider_id"] != raw["effective_rider_id"]
                    ),
                    None,
                )
                assert (
                    foreign
                ), "The lab must retain a foreign payout for the ownership check"
                get("/payouts/exact/" + foreign["id"] + "?audience=OWNER", 404)
                if not raw["items"]:
                    expect(
                        page.get_by_text("Sin retiros en esta página", exact=True)
                    ).to_be_visible()

            get("/payouts/exact/page?audience=" + ("STAFF" if owner else "OWNER"), 403)
            passed(role + ": exact page, actor and explicit role scope")
            if not owner:
                with page.expect_download() as event:
                    page.get_by_role(
                        "button", name="Exportar página CSV", exact=True
                    ).click()
                file = out / (role.lower() + "-payouts.csv")
                event.value.save_as(str(file))
                rows = list(
                    csv.DictReader(io.StringIO(file.read_text(encoding="utf-8-sig")))
                )
                by_id = {r["id"]: r for r in raw["items"]}
                assert len(rows) == len(raw["items"])
                for r in rows:
                    source = by_id[r["id"]]
                    for field, column in [
                        ("amount", "importe_registrado"),
                        ("balance_before", "saldo_anterior_registrado"),
                        ("balance_after", "saldo_posterior_registrado"),
                    ]:
                        expected = source[field] or ""
                        expected = (
                            "'" + expected if expected.startswith("-") else expected
                        )
                        assert r[column] == expected
                    assert (
                        r["moneda"] == (source["currency"] or "")
                        and r["verificado_por_banco"] == "false"
                        and len(r["huella_sha256"]) == 64
                    )
                passed(
                    role
                    + ": exact CSV page and missing snapshots, original units and cut metadata"
                )
                target = raw["items"][0]["id"]
                detail = get("/payouts/exact/" + target + "?audience=STAFF")
                assert (
                    detail["history_included"]
                    and detail["history_complete"]
                    and detail["items"][0]["id"] == target
                )
                requests = []
                page.on(
                    "request",
                    lambda r: (
                        requests.append(r.url)
                        if "/payouts/" in r.url
                        and "/api/v1/" in r.url
                        and r.method == "GET"
                        else None
                    ),
                )
                page.goto(
                    base + "/manager/financial/payouts/" + target,
                    wait_until="domcontentloaded",
                )
                expect(page.get_by_text(target, exact=True)).to_be_visible()
                expect(page.get_by_text("Huella SHA-256:", exact=False)).to_be_visible()
                assert len(requests) == 1 and "/payouts/exact/" + target in requests[0]
                expect(
                    page.get_by_text(
                        "Los saldos son registros históricos.", exact=False
                    )
                ).to_be_visible()
                passed(
                    role + ": parent and complete history loaded by one exact request"
                )
                mode = {"bad": True}

                def corrupt(route):
                    if route.request.method != "GET":
                        route.continue_()
                        return
                    response = route.fetch()
                    assert response.status == 200
                    if mode["bad"]:
                        data = response.json()
                        data["history_complete"] = False
                        route.fulfill(response=response, json=data)
                    else:
                        route.fulfill(response=response)

                page.route(
                    re.compile("/api/v1/payouts/exact/" + target + r"(?:\?|$)"), corrupt
                )
                page.get_by_role(
                    "button", name="Consultar estado del retiro", exact=True
                ).click()
                error = page.get_by_role("alert").filter(
                    has_text="No se pudo confirmar el registro exacto"
                )
                expect(error).to_be_visible()
                expect(page.get_by_text(target, exact=True)).to_be_visible()
                expect(
                    page.get_by_role("button", name="Aprobar retiro", exact=True)
                ).to_have_count(0)
                passed(
                    role
                    + ": incomplete history rejected, previous cut retained and decisions blocked"
                )
                mode["bad"] = False
                page.get_by_role(
                    "button", name="Consultar estado del retiro", exact=True
                ).click()
                expect(error).to_have_count(0)
                expect(page.get_by_text(target, exact=True)).to_be_visible()
                passed(role + ": explicit read recovers without replaying a decision")
            page.screenshot(
                path=str(out / (role.lower() + "-desktop.png")),
                full_page=True,
                animations="disabled",
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function(
                "document.querySelector('aside').getBoundingClientRect().right <= 1"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(
                path=str(out / (role.lower() + "-mobile.png")), animations="disabled"
            )
            passed(role + ": mobile page fits without document overflow")
            ctx.close()
        browser.close()
    after = snapshot()
    assert before == after and not errors and not writes
    passed(
        "history and original source tables preserved; zero business writes and JS errors"
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

"""Read-only exact rider audit against the marked PostgreSQL laboratory."""

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
        for role in ("SUPERADMIN", "GERENTE"):
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 1050}, accept_downloads=True
            )
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/login", wait_until="domcontentloaded")
            account = accounts[role]
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
                base + "/manager/operations/rider-audit", wait_until="domcontentloaded"
            )
            confirmed = page.get_by_role(
                "region", name="Página de auditoría confirmada"
            )
            expect(confirmed).to_be_visible(timeout=30000)
            raw = get("/riders/audit/summary/exact?limit=51&offset=0")
            assert (
                raw["viewer_role"] == role
                and raw["viewer_user_id"] == me["id"]
                and raw["currency"] == "USD"
            )
            assert not raw["available_balance_included"] and not raw["bank_verified"]
            assert raw["items"]
            passed(role + ": authenticated exact catalog and owner/currency scope")
            with page.expect_download() as event:
                page.get_by_role(
                    "button", name="Exportar página CSV", exact=True
                ).click()
            file = out / (role.lower() + "-audit.csv")
            event.value.save_as(str(file))
            rows = list(
                csv.DictReader(io.StringIO(file.read_text(encoding="utf-8-sig")))
            )
            assert len(rows) == min(50, len(raw["items"]))
            by_id = {r["rider_id"]: r for r in raw["items"]}
            for r in rows:
                m = by_id[r["id_rider"]]["money"]
                assert (
                    r["creditos_usd"] == m["credit_usd"]
                    and r["cambio_neto_usd"]
                    == (
                        "'" + m["net_change_usd"]
                        if m["net_change_usd"].startswith("-")
                        else m["net_change_usd"]
                    )
                    and r["solicitudes_pendientes_usd"] == m["pending_usd"]
                )
                assert (
                    r["moneda"] == "USD"
                    and r["saldo_disponible_incluido"] == "false"
                    and r["verificado_por_banco"] == "false"
                    and len(r["huella_sha256"]) == 64
                )
            passed(
                role + ": CSV preserves decimal strings, exclusions, cut and page scope"
            )
            target = next(
                r["rider_id"]
                for r in raw["items"]
                if r["orders_assigned"]
                or r["deliveries_total"]
                or r["money"]["ledger_rows"]
            )
            page.get_by_role(
                "link", name="Ver auditoría de " + target, exact=True
            ).click()
            detail = page.get_by_role("region", name="Auditoría confirmada")
            expect(detail).to_be_visible(timeout=30000)
            exact = get(
                "/riders/audit/summary/exact?rider_id=" + target + "&limit=1&offset=0"
            )
            assert len(exact["items"]) == 1 and exact["items"][0]["rider_id"] == target
            expect(detail).to_contain_text("Alcance del cálculo USD")
            expect(detail).to_contain_text("Créditos USD registrados")
            expect(detail).to_contain_text("Solicitudes USD pendientes")
            expect(detail).to_contain_text("no acreditan una transferencia bancaria")
            passed(
                role + ": direct identity detail and independent ledger/request totals"
            )
            # Each table has its own SQL cut; neither price nor bonus is a ledger balance.
            order_records = get(
                "/riders/audit/records/exact?kind=orders&rider_id="
                + target
                + "&limit=51&offset=0"
            )
            delivery_records = get(
                "/riders/audit/records/exact?kind=deliveries&rider_id="
                + target
                + "&limit=51&offset=0"
            )
            transactions = get(
                "/financial/transactions/exact/page?rider_id="
                + target
                + "&limit=51&offset=0"
            )
            for data in (order_records, delivery_records, transactions):
                assert (
                    data["snapshot_basis"] == "single_statement_visibility"
                    and not data["available_balance_included"]
                    and not data["bank_verified"]
                )
                assert (
                    data["viewer_user_id"] == exact["viewer_user_id"]
                    and data["viewer_role"] == role
                )
                assert all(r["rider_id"] == target for r in data["items"])
            assert all(
                r["currency"] is None and r["currency_recorded"] is None
                for r in delivery_records["items"]
            )
            assert all(
                (
                    r["amount"] is None
                    if r["price_review"]
                    else isinstance(r["amount"], str)
                )
                for r in order_records["items"]
            )
            passed(
                role
                + ": exact scoped order prices, locked bonuses and ledger records remain independent"
            )
            with page.expect_download() as export:
                page.get_by_role(
                    "button", name="Exportar tablas CSV", exact=True
                ).click()
            export_file = out / (role.lower() + "-audit-tables.csv")
            export.value.save_as(str(export_file))
            exported = list(
                csv.DictReader(io.StringIO(export_file.read_text(encoding="utf-8-sig")))
            )
            originals = {
                k: {r["id"]: r for r in values}
                for k, values in [
                    ("orders", order_records["items"][:50]),
                    ("deliveries", delivery_records["items"][:50]),
                    ("transactions", transactions["items"][:50]),
                    ("support_orders", delivery_records["fallback"]),
                ]
            }
            assert len(exported) == sum(len(v) for v in originals.values())
            for r in exported:
                source = originals[r["clase_registro"]][r["id"]]
                for key, column in [
                    ("amount", "importe_registrado"),
                    ("locked_bonus_amount", "bono_conservado"),
                    ("balance_after", "saldo_posterior_registrado"),
                ]:
                    value = source.get(key) or ""
                    literal = "'" + value if value.startswith("-") else value
                    assert r[column] == literal
                assert (
                    r["moneda"] == (source["currency"] or "")
                    and r["rider_id"] == target
                )
                assert r["huella_sha256"] in detail.inner_text()
                assert (
                    r["saldo_disponible_incluido"]
                    == r["verificado_por_banco"]
                    == "false"
                )
            passed(
                role
                + ": table CSV preserves visible exact strings, source kind, missing units and per-table cut"
            )
            page.screenshot(
                path=str(out / (role.lower() + "-desktop.png")), full_page=True
            )
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator("aside")).to_have_class(re.compile("-translate-x-full"))
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1"
            )
            page.get_by_text(
                "Créditos USD registrados", exact=True
            ).scroll_into_view_if_needed()
            page.screenshot(
                path=str(out / (role.lower() + "-mobile.png")), full_page=False
            )
            passed(role + ": responsive mobile audit without document overflow")

            # Corrupt only a read response: a wrong exact total must preserve confirmed content.
            mode = {"bad": True, "injected": False}

            def corrupt(route):
                if route.request.method != "GET":
                    route.continue_()
                    return
                response = route.fetch()
                if not mode["bad"]:
                    route.fulfill(response=response)
                    return
                assert response.status == 200
                changed = response.json()
                changed["items"][0]["money"]["net_change_usd"] = "99999999.99"
                route.fulfill(response=response, json=changed)
                mode["injected"] = True

            page.route(re.compile(r"/api/v1/riders/audit/summary/exact\?"), corrupt)
            page.get_by_role("button", name="Actualizar auditoría", exact=True).click()
            audit_error = page.get_by_role("alert").filter(
                has_text="No se pudo comprobar el conjunto de auditoría"
            )
            expect(audit_error).to_be_visible()
            expect(detail).to_be_visible()
            passed(
                role
                + ": invalid exact response is rejected and previous confirmed set survives"
            )
            deadline = time.monotonic() + 10
            while not mode["injected"] and time.monotonic() < deadline:
                page.wait_for_timeout(20)
            assert mode["injected"]
            mode["bad"] = False
            page.get_by_role("button", name="Reintentar auditoría", exact=True).click()
            expect(detail).to_have_attribute("aria-busy", "false")
            expect(audit_error).to_have_count(0)
            expect(detail).to_be_visible()
            passed(role + ": clean response recovers without business writes")
            table_mode = {"bad": True}

            def corrupt_table(route):
                if route.request.method != "GET":
                    route.continue_()
                    return
                response = route.fetch()
                assert response.status == 200
                if table_mode["bad"]:
                    data = response.json()
                    data["amount_basis"] = "available_funds"
                    route.fulfill(response=response, json=data)
                else:
                    route.fulfill(response=response)

            page.route(
                re.compile(r"/api/v1/riders/audit/records/exact\?.*kind=orders"),
                corrupt_table,
            )
            page.get_by_role("button", name="Actualizar auditoría", exact=True).click()
            expect(audit_error).to_be_visible()
            expect(detail).to_be_visible()
            expect(
                page.get_by_role("button", name="Exportar tablas CSV", exact=True)
            ).to_be_disabled()
            table_mode["bad"] = False
            page.get_by_role("button", name="Reintentar auditoría", exact=True).click()
            expect(detail).to_have_attribute("aria-busy", "false")
            expect(audit_error).to_have_count(0)
            expect(
                page.get_by_role("button", name="Exportar tablas CSV", exact=True)
            ).to_be_enabled()
            passed(
                role
                + ": corrupt exact table retains every confirmed block and blocks export until explicit recovery"
            )
            ctx.close()
        browser.close()
    after = snapshot()
    assert after == before and not writes and not errors
    passed("all source tables preserved; zero business writes or JS exceptions")
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

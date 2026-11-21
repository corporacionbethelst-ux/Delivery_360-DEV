"""Explicit USD zone configuration in a marked lab; preserve original rows and money."""

import argparse, json, re, subprocess, sys, time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--wait-request-window", action="store_true")
    args = parser.parse_args()
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
    users = json.loads(local_test.ACCOUNTS.read_text())
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors, writes, unrelated = [], [], [], []
    target = None
    run = uuid4().hex[:12]
    code = "T" + run[:4].upper()
    name = "Tarifas109 " + run
    while sql("SELECT count(*) FROM zones WHERE code='" + code + "'") != "0":
        code = "T" + uuid4().hex[:4].upper()
    tables = (
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

    def snapshot():
        return {
            t: sql(
                "SELECT count(*)::text||':'||md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM "
                + t
                + " t"
            )
            for t in tables
        }

    before = snapshot()
    original_zones = json.loads(
        sql(
            "SELECT coalesce(jsonb_agg(to_jsonb(z) ORDER BY id),'[]'::jsonb)::text FROM zones z"
        )
    )

    def passed(text):
        checks.append(text)
        print("passed:", text, flush=True)

    passed(
        "marked laboratory and original table hashes captured before configuring a synthetic zone"
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True)

        def login(role):
            context = browser.new_context(
                viewport={"width": 1440, "height": 1100}, timezone_id="America/Caracas"
            )
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))

            def guard(route):
                request = route.request
                path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
                if request.method not in ("GET", "OPTIONS") and path not in (
                    "/auth/login",
                    "/auth/refresh",
                    "/auth/logout",
                    "/notifications/read",
                    "/notifications/read-all",
                ):
                    valid = (
                        role == "GERENTE"
                        and request.method == "POST"
                        and path == "/zones"
                        and request.post_data_json.get("name") == name
                        and request.post_data_json.get("code") == code
                    ) or (
                        role == "GERENTE"
                        and target is not None
                        and request.method == "PUT"
                        and path == f"/zones/{target}/tariff/exact"
                    )
                    (writes if valid else unrelated).append(
                        {"method": request.method, "path": path}
                    )
                    if not valid:
                        route.abort()
                        return
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
            return context, page, {"Authorization": "Bearer " + token}

        context, page, headers = login("GERENTE")
        page.goto(base + "/manager/fleet/zones", wait_until="domcontentloaded")
        page.get_by_role("button", name="Nueva Zona", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Nombre *", exact=True).fill(name)
        dialog.get_by_label("Código *", exact=True).fill(code)
        assert dialog.get_by_label("Tarifa Base", exact=True).count() == 0
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/api/v1/zones")
        ) as created:
            dialog.get_by_role("button", name="Crear Zona", exact=True).click()
        assert created.value.status == 201
        payload = created.value.request.post_data_json
        assert "delivery_fee_base" not in payload and "cost_per_km" not in payload
        target = created.value.json()["id"]
        assert re.fullmatch(r"[0-9a-f-]{36}", target)
        passed(
            "manager creates an operational zone without monetary input, implicit USD or a 4000 default"
        )
        path = f"/zones/{target}/tariff/exact"
        page.goto(
            base + "/manager/fleet/zones/" + target, wait_until="domcontentloaded"
        )
        panel = page.get_by_role("region", name="Tarifas USD de la zona")
        expect(panel).to_contain_text("Tarifas USD sin configurar", timeout=30000)
        expect(panel.get_by_label("Tarifa base USD", exact=True)).to_have_value("")
        expect(
            panel.get_by_label("Tarifa por kilómetro USD", exact=True)
        ).to_have_value("")
        assert panel.get_by_text("USD 0,00", exact=True).count() == 0
        passed(
            "unconfigured tariffs remain absent rather than a confirmed USD zero or relabelled historical amount"
        )
        start = len(writes)
        panel.get_by_label("Tarifa base USD", exact=True).fill("-1")
        panel.get_by_label("Tarifa por kilómetro USD", exact=True).fill("0.10")
        panel.get_by_role("button", name="Guardar tarifas USD", exact=True).click()
        expect(panel.get_by_role("alert")).to_contain_text("hasta dos decimales")
        assert len(writes) == start
        passed(
            "negative or incomplete input is rejected locally without a tariff mutation"
        )
        panel.get_by_label("Tarifa base USD", exact=True).fill("0,31")
        with page.expect_response(
            lambda r: r.request.method == "PUT" and r.url.endswith("/api/v1" + path)
        ) as changed:
            panel.get_by_role("button", name="Guardar tarifas USD", exact=True).click()
        assert changed.value.status == 200
        assert changed.value.request.post_data_json == dict(
            currency="USD", expected_revision=0, base_usd="0.31", per_km_usd="0.10"
        )
        expect(panel).to_contain_text("Tarifas USD guardadas y confirmadas")
        expect(panel).to_contain_text("USD 0,31")
        expect(panel).to_contain_text("USD 0,10")
        actual = page.request.get(api + path, headers=headers)
        assert actual.status == 200
        value = actual.json()
        assert (
            value["revision"] == 1
            and value["base_usd"] == "0.31"
            and value["per_km_usd"] == "0.10"
        )
        passed(
            "confirmed save uses exact decimal strings and the loaded revision, and the server returns matching USD cents"
        )
        evidence = json.loads(
            sql(
                "SELECT json_build_object('base',tariff_base_usd::text,'km',tariff_per_km_usd::text,'legacy_base',delivery_fee_base,'legacy_km',cost_per_km,'factor',bonus_multiplier)::text FROM zones WHERE id='"
                + target
                + "'"
            )
        )
        assert evidence == dict(
            base="0.31", km="0.10", legacy_base=0, legacy_km=0, factor=1
        )
        assert (
            sql(
                "SELECT count(*) FROM audit_logs WHERE resource_type='ZoneTariff' AND resource_id='"
                + target
                + "' AND old_values->>'revision'='0' AND new_values->>'revision'='1'"
            )
            == "1"
        )
        passed(
            "database stores exact cents and an atomic before/after audit without overwriting legacy fields or bonus factors"
        )
        stale = page.request.put(
            api + path,
            headers=headers,
            data=dict(
                currency="USD",
                expected_revision=0,
                base_usd="99.00",
                per_km_usd="99.00",
            ),
        )
        assert (
            stale.status == 409
            and page.request.get(api + path, headers=headers).json() == value
        )
        passed(
            "a stale revision is rejected with 409 and cannot replace the confirmed tariff"
        )

        def fail(route):
            route.fulfill(
                status=503, json={"detail": "synthetic ambiguous write response"}
            )

        context.route("**/api/v1" + path, fail)
        panel.get_by_role("button", name="Guardar tarifas USD", exact=True).click()
        expect(panel.get_by_role("alert")).to_contain_text(
            "consulta las tarifas actuales"
        )
        expect(
            panel.get_by_role("button", name="Guardar tarifas USD", exact=True)
        ).to_be_disabled()
        passed(
            "ambiguous save response blocks automatic resubmission and requires a fresh read"
        )
        context.unroute("**/api/v1" + path, fail)
        before_retry = len(writes)
        panel.get_by_role(
            "button", name="Consultar tarifas actuales", exact=True
        ).click()
        expect(
            panel.get_by_role("button", name="Guardar tarifas USD", exact=True)
        ).to_be_enabled()
        expect(panel.get_by_role("alert")).to_have_count(0)
        assert len(writes) == before_retry
        passed(
            "explicit recovery performs only GET and restores the current confirmed revision"
        )
        panel.scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "zone-tariffs-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        page.set_viewport_size({"width": 390, "height": 844})
        panel.scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
        page.screenshot(
            path=str(out / "zone-tariffs-mobile.png"), animations="disabled"
        )
        passed(
            "tariff cards and separate save controls remain readable on desktop and mobile without horizontal overflow"
        )
        page.reload(wait_until="domcontentloaded")
        expect(
            page.get_by_role("region", name="Tarifas USD de la zona")
        ).to_contain_text("USD 0,31", timeout=30000)
        passed(
            "a cold page reload reads the persisted USD tariff rather than an optimistic draft"
        )
        page.goto(base + "/manager/fleet/zones", wait_until="domcontentloaded")
        card = page.get_by_role("article", name="Zona " + name, exact=True)
        expect(card).to_contain_text("USD 0,31", timeout=30000)
        expect(card).to_contain_text("USD 0,10")
        expect(card).to_contain_text("rev. 1")
        passed(
            "the catalog batch read presents both exact configured rates and their revision"
        )
        context.close()
        for role in ("OPERADOR", "SUPERADMIN"):
            ctx, p, h = login(role)
            p.goto(
                base + "/manager/fleet/zones/" + target, wait_until="domcontentloaded"
            )
            section = p.get_by_role("region", name="Tarifas USD de la zona")
            expect(section).to_contain_text("USD 0,31", timeout=30000)
            button = section.get_by_role(
                "button", name="Guardar tarifas USD", exact=True
            )
            if role == "OPERADOR":
                expect(button).to_have_count(0)
                assert (
                    p.request.put(
                        api + path,
                        headers=h,
                        data=dict(
                            currency="USD",
                            expected_revision=1,
                            base_usd="99.00",
                            per_km_usd="99.00",
                        ),
                    ).status
                    == 403
                )
                passed(
                    "operator reads exact tariffs but has no save control and cannot bypass the server permission"
                )
            else:
                expect(button).to_be_enabled()
                passed(
                    "superadmin reads the same persisted revision with its authorized save control"
                )
            ctx.close()
        browser.close()
    current = json.loads(
        sql(
            "SELECT coalesce(jsonb_agg(to_jsonb(z) ORDER BY id),'[]'::jsonb)::text FROM zones z WHERE id<>'"
            + target
            + "'"
        )
    )
    assert current == original_zones
    passed(
        "all original zone rows remain identical; only the named synthetic zone was configured"
    )
    assert before == snapshot() and not errors and not unrelated
    assert len(writes) == 2 and [w["method"] for w in writes] == ["POST", "PUT"]
    passed(
        "all 16 operational and monetary table hashes are unchanged; zero unrelated writes, financial mutations or JS exceptions"
    )
    assert len(checks) == 16
    (out / "results.json").write_text(
        json.dumps(
            dict(
                checks=checks,
                errors=errors,
                writes=writes,
                unrelated_writes=unrelated,
                history_preserved=True,
                original_zones_preserved=True,
                financial_writes=0,
                instance=state["instance"],
                target_zone=target,
                run=run,
                bank_transfer_performed=False,
                external_messages_sent=False,
            ),
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

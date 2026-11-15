"""Manual refunds with two real staff accounts, original BCV and immutable reconciliation."""

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
    ), "Dedicated database marker required before writes"
    local_test.check(state, authenticate=False)
    if args.wait_request_window:
        print("Respecting the shared request window", flush=True)
        time.sleep(60)
        time.sleep(1)
    accounts = json.loads(local_test.ACCOUNTS.read_text())
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    run = uuid4().hex[:10].upper()

    def passed(name):
        checks.append(name)
        print("passed:", name, flush=True)

    def ledger():
        return {
            table: sql(
                "SELECT count(*)::text||':'||md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM "
                + table
                + " t"
            )
            for table in (
                "financials",
                "financial_transactions",
                "rider_wallets",
                "payouts",
                "payout_status_history",
            )
        }

    before = ledger()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        def session(role):
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                locale="es-VE",
                timezone_id="America/Caracas",
            )
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.locator("input[type=email]").fill(accounts[role]["email"])
            page.locator("input[type=password]").fill(accounts[role]["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(re.compile("/manager(?:/|$)"), timeout=30000)
            token = page.evaluate('localStorage.getItem("access_token")')
            assert token

            def call(method, path, body=None, status=200):
                response = page.request.fetch(
                    api + path,
                    method=method,
                    headers={"Authorization": "Bearer " + token},
                    data=body,
                )
                assert response.status == status, (
                    method,
                    path,
                    response.status,
                    response.text(),
                )
                return response.json()

            identity = call("GET", "/auth/me")
            email = accounts[role]["email"].replace("'", "''")
            assert (
                identity["id"]
                == sql("SELECT id FROM users WHERE email='" + email + "'")
                and identity["role"] == role
            )
            return ctx, page, call, identity

        admin_ctx, page, call, admin = session("SUPERADMIN")
        manager_ctx, manager, manager_call, supervisor = session("GERENTE")
        assert admin["id"] != supervisor["id"]
        passed(
            "two independent real staff identities and the dedicated database marker verified"
        )
        current = call("GET", "/currency/context")
        day = current["today"]
        reference = call(
            "POST",
            "/currency/rates",
            dict(
                request_key=str(uuid4()),
                previous_rate_id=(
                    current["current_rate"]["id"] if current["current_rate"] else None
                ),
                valid_on=day,
                reference_date=day,
                ves_per_usd="1.50000000",
                note="ENTREGA95 SYNTHETIC original BCV " + run,
                confirmed_bcv=True,
            ),
            201,
        )
        order = call(
            "POST",
            "/orders",
            dict(
                customer_name="Refund " + run,
                customer_phone="+584120000000",
                pickup_address="Synthetic origin",
                delivery_address="Synthetic destination",
                delivery_contact="Laboratory",
                items=[dict(product_name="Decimal", quantity="3", unit_price="0.10")],
                delivery_fee="0.20",
                currency="USD",
            ),
            201,
        )
        oid = order["id"]
        assert re.fullmatch(r"[0-9a-f-]{36}", oid)
        quote = call(
            "POST",
            "/currency/orders/" + oid + "/quotes",
            dict(
                request_key=str(uuid4()),
                rate_id=reference["id"],
                expected_pricing_revision=1,
            ),
            201,
        )
        collected = call(
            "POST",
            "/customer-collections/orders/" + oid,
            dict(
                request_key=str(uuid4()),
                expected_pricing_revision=1,
                expected_collection_revision=0,
                amount_usd="0.50",
                paid_amount="0.75",
                paid_currency="VES",
                method="TRANSFERENCIA",
                source_key="CAJA95-" + run,
                reference_key="COBRO95-" + run,
                received_on=day,
                quote_id=quote["id"],
                confirmed_received=True,
            ),
            201,
        )
        original = manager_call(
            "POST",
            "/customer-collections/" + collected["id"] + "/review",
            dict(
                request_key=str(uuid4()),
                expected_collection_revision=1,
                decision="VERIFICADO",
                note="Cobro sintético verificado en laboratorio",
                verified_evidence=True,
            ),
            201,
        )
        call("PATCH", "/orders/" + oid + "/status?new_status=CANCELADO")
        path = "/customer-refunds/orders/" + oid
        url = base + "/manager/operations/orders/" + oid
        page.goto(url, wait_until="domcontentloaded")
        panel = page.get_by_role("region", name="Devoluciones de clientes", exact=True)

        def fill(usd):
            panel.get_by_label("Importe a devolver en USD", exact=True).fill(usd)
            panel.get_by_label("Motivo de devolución", exact=True).fill(
                "ENTREGA95 SYNTHETIC devolución por cancelación " + run
            )
            panel.get_by_label(re.compile("Confirmo que solicito este importe")).check()
            panel.get_by_role(
                "button", name="Revisar solicitud de devolución", exact=True
            ).click()

        expect(
            panel.get_by_role(
                "button", name="Revisar solicitud de devolución", exact=True
            )
        ).to_be_disabled(timeout=20000)
        fill("0.01")
        modal = page.get_by_role("dialog", name="Confirmar solicitud de devolución")
        expect(modal.get_by_text("Bs. 0,02", exact=True)).to_be_visible()
        modal.get_by_role("button", name="Cancelar", exact=True).click()
        assert call("GET", path)["book_revision"] == 0
        passed(
            "original-currency preview uses exact cents and cancelling the review performs no write"
        )
        panel.get_by_role(
            "button", name="Revisar solicitud de devolución", exact=True
        ).click()
        lost = []

        def lose(route):
            if route.request.method != "POST" or lost:
                route.continue_()
                return
            result = route.fetch()
            assert result.status == 201, result.text()
            lost.append(result.json())
            route.abort("failed")

        page.route("**/api/v1" + path, lose)
        modal.get_by_role(
            "button", name="Confirmar y guardar devolución", exact=True
        ).click()
        expect(
            modal.get_by_role("button", name="Reintentar misma devolución", exact=True)
        ).to_be_enabled(timeout=20000)
        assert len(lost) == 1
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/api/v1" + path)
        ) as recovered:
            modal.get_by_role(
                "button", name="Reintentar misma devolución", exact=True
            ).click()
        first = recovered.value.json()
        assert (
            recovered.value.status == 201
            and first == lost[0]
            and recovered.value.request.post_data_json["request_key"]
            == first["request_key"]
        )
        page.unroute("**/api/v1" + path, lose)
        assert (
            first["return_amount"] == "0.02" and first["prior_refunded_usd"] == "0.00"
        )
        expect(panel.get_by_label("Devolución conservada")).to_contain_text(first["id"])
        assert "refund=" + first["id"] in page.url
        passed(
            "a committed refund request lost to the browser is recovered by the same key without duplicates"
        )

        def event(kind, revision, **extra):
            data = dict(
                request_key=str(uuid4()),
                expected_revision=revision,
                kind=kind,
                note="ENTREGA95 SYNTHETIC comprobación " + kind + " " + run,
                verified_evidence=kind
                in [
                    "VERIFICAR_DEVOLUCION",
                    "CONFIRMAR_NO_EJECUTADA",
                    "ANULAR_APROBACION",
                ],
                confirmed_no_execution=kind
                in ["CONFIRMAR_NO_EJECUTADA", "ANULAR_APROBACION"],
                confirmed_execution=kind == "DECLARAR_EJECUCION",
            )
            data.update(extra)
            return data

        def act(request, body, who=manager_call, status=201):
            return who(
                "POST", "/customer-refunds/" + request["id"] + "/events", body, status
            )

        def execution(request, revision, ref):
            return event(
                "DECLARAR_EJECUCION",
                revision,
                method="PAGO_MOVIL",
                source_key="SALIDAS95-" + run,
                reference_key=ref,
                paid_amount=request["return_amount"],
                paid_currency=request["return_currency"],
                executed_on=day,
            )

        act(first, event("APROBAR", 0), who=call, status=403)
        manager.goto(page.url, wait_until="domcontentloaded")
        review_panel = manager.get_by_role(
            "region", name="Devoluciones de clientes", exact=True
        )
        review_panel.get_by_role("button", name="Aprobar solicitud", exact=True).click()
        review_panel.get_by_label(
            "Motivo o comprobación de devolución", exact=True
        ).fill("Aprobación independiente de solicitud sintética")
        review_panel.get_by_role(
            "button", name="Revisar acción de devolución", exact=True
        ).click()
        review_modal = manager.get_by_role(
            "dialog", name="Confirmar acción de devolución"
        )
        with manager.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/" + first["id"] + "/events")
        ) as authorized:
            review_modal.get_by_role(
                "button", name="Confirmar y guardar devolución", exact=True
            ).click()
        assert (
            authorized.value.status == 201
            and authorized.value.json()["refund"]["state"] == "APROBADA"
        )
        assert call("GET", path)["summary"]["remaining_usd"] == "0.50"
        passed(
            "self authorization is rejected and independent approval reserves without recording a refund"
        )
        page.reload(wait_until="domcontentloaded")
        panel.get_by_role(
            "button", name="Registrar devolución realizada", exact=True
        ).click()
        panel.get_by_label("Motivo o comprobación de devolución", exact=True).fill(
            "Salida sintética registrada manualmente"
        )
        panel.get_by_role(
            "button", name="Revisar acción de devolución", exact=True
        ).click()
        expect(panel.get_by_role("alert")).to_contain_text("Confirma")
        for label, value in [
            ("Importe realmente devuelto", "0.02"),
            ("Alias de caja o cuenta de salida", "SALIDAS95-" + run),
            ("Referencia única de devolución", "SALIDA1-" + run),
        ]:
            panel.get_by_label(label, exact=True).fill(value)
        panel.get_by_label(re.compile("Confirmo que ya realicé la devolución")).check()
        panel.get_by_role(
            "button", name="Revisar acción de devolución", exact=True
        ).click()
        action_modal = page.get_by_role("dialog", name="Confirmar acción de devolución")
        with page.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/" + first["id"] + "/events")
        ) as declared:
            action_modal.get_by_role(
                "button", name="Confirmar y guardar devolución", exact=True
            ).click()
        assert (
            declared.value.status == 201
            and declared.value.json()["refund"]["state"] == "EJECUCION_DECLARADA"
        )
        assert call("GET", path)["summary"]["refunded_usd"] == "0.00"
        act(first, event("VERIFICAR_DEVOLUCION", 2), who=call, status=403)
        passed(
            "declaring a manual payout requires explicit actual execution and still does not reduce the liability"
        )
        manager.reload(wait_until="domcontentloaded")
        review_panel.get_by_role(
            "button", name="Verificar devolución", exact=True
        ).click()
        expect(review_panel.get_by_label("Ejecución a conciliar")).to_contain_text(
            "SALIDA1-" + run
        )
        review_panel.get_by_label(
            "Motivo o comprobación de devolución", exact=True
        ).fill("Salida comprobada por otra cuenta sintética")
        review_panel.get_by_label(re.compile("He comprobado el efectivo")).check()
        review_panel.get_by_role(
            "button", name="Revisar acción de devolución", exact=True
        ).click()
        with manager.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/" + first["id"] + "/events")
        ) as verified:
            review_modal.get_by_role(
                "button", name="Confirmar y guardar devolución", exact=True
            ).click()
        assert (
            verified.value.status == 201
            and verified.value.json()["refund"]["state"] == "DEVUELTA"
        )
        ctx = call("GET", path)
        assert (
            ctx["summary"]["remaining_usd"] == "0.49"
            and ctx["summary"]["refunded_usd"] == "0.01"
        )
        passed(
            "another supervisor verifies the payout and only that event reduces the pending refund"
        )
        current = call("GET", "/currency/context")
        call(
            "POST",
            "/currency/rates",
            dict(
                request_key=str(uuid4()),
                previous_rate_id=current["current_rate"]["id"],
                valid_on=day,
                reference_date=day,
                ves_per_usd="99.00000000",
                note="ENTREGA95 SYNTHETIC later BCV correction " + run,
                confirmed_bcv=True,
            ),
            201,
        )
        page.reload(wait_until="domcontentloaded")
        expect(
            panel.get_by_role(
                "button", name="Revisar solicitud de devolución", exact=True
            )
        ).to_be_visible(timeout=20000)
        fill("0.01")
        expect(modal.get_by_text("Bs. 0,01", exact=True)).to_be_visible()
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/api/v1" + path)
        ) as second_post:
            modal.get_by_role(
                "button", name="Confirmar y guardar devolución", exact=True
            ).click()
        second = second_post.value.json()
        assert (
            second_post.value.status == 201
            and second["return_amount"] == "0.01"
            and second["prior_refunded_usd"] == "0.01"
            and second["prior_refunded_paid"] == "0.02"
        )
        passed(
            "a later BCV correction cannot revalue the original payment; the next partial refund allocates one original cent"
        )
        act(second, event("APROBAR", 0))
        attempt = execution(second, 1, "SALIDA2-" + run)
        act(second, attempt, who=call)
        act(second, event("OBSERVAR_EJECUCION", 2))
        ctx = call("GET", path)
        assert (
            ctx["summary"]["remaining_usd"] == "0.49"
            and ctx["summary"]["in_progress_usd"] == "0.01"
        )
        body = dict(
            request_key=str(uuid4()),
            collection_id=original["id"],
            expected_book_revision=ctx["book_revision"],
            amount_usd="0.01",
            reason="Synthetic duplicate attempt blocked",
            confirmed_request=True,
        )
        call("POST", path, body, 409)
        act(second, execution(second, 3, "DUPLICATE-" + run), who=call, status=409)
        act(second, event("CONFIRMAR_NO_EJECUTADA", 3), who=call, status=403)
        passed(
            "an observed execution remains reserved and cannot trigger a second payout or self reconciliation"
        )
        print(
            "Respecting the request window before independent reconciliation",
            flush=True,
        )
        time.sleep(60)
        time.sleep(1)
        manager.goto(url + "?refund=" + second["id"], wait_until="domcontentloaded")
        review_panel.get_by_role(
            "button", name="Confirmar que no se ejecutó", exact=True
        ).click()
        review_panel.get_by_label(
            "Motivo o comprobación de devolución", exact=True
        ).fill("Comprobado sin salida en evidencia sintética")
        review_panel.get_by_label(re.compile("He comprobado el efectivo")).check()
        review_panel.get_by_label(
            re.compile("Confirmo expresamente que no hubo salida")
        ).check()
        review_panel.get_by_role(
            "button", name="Revisar acción de devolución", exact=True
        ).click()
        with manager.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/" + second["id"] + "/events")
        ) as reconciled:
            review_modal.get_by_role(
                "button", name="Confirmar y guardar devolución", exact=True
            ).click()
        assert (
            reconciled.value.status == 201
            and reconciled.value.json()["refund"]["state"] == "APROBADA"
        )
        act(second, execution(second, 4, "SALIDA2-" + run), who=call, status=409)
        act(second, execution(second, 4, "SALIDA3-" + run), who=call)
        act(second, event("VERIFICAR_DEVOLUCION", 5))
        passed(
            "independent evidence of no execution permits a new uniquely referenced attempt while preserving all earlier events"
        )
        ctx = call("GET", path)
        last = call(
            "POST",
            path,
            dict(
                request_key=str(uuid4()),
                collection_id=original["id"],
                expected_book_revision=ctx["book_revision"],
                amount_usd="0.48",
                reason="ENTREGA95 SYNTHETIC devolución final " + run,
                confirmed_request=True,
            ),
            201,
        )
        assert last["return_amount"] == "0.72"
        act(last, event("APROBAR", 0))
        act(last, execution(last, 1, "SALIDA4-" + run), who=call)
        act(last, event("VERIFICAR_DEVOLUCION", 2))
        ctx = call("GET", path)
        assert ctx["summary"] == dict(
            currency="USD",
            gross_verified_usd="0.50",
            refunded_usd="0.50",
            in_progress_usd="0.00",
            remaining_usd="0.00",
            requestable_now_usd="0.00",
        )
        assert (
            sql(
                "SELECT sum(r.return_amount)::text FROM customer_refunds r JOIN customer_collections c ON c.id=r.collection_id WHERE c.order_id='"
                + oid
                + "' AND customer_refund_status(r.id)='DEVUELTA'"
            )
            == "0.75"
        )
        passed(
            "all partial refunds settle the original 0.50 USD and exactly 0.75 VES without rounding overpayment"
        )
        page.goto(url + "?refund=" + last["id"], wait_until="domcontentloaded")
        expect(panel.get_by_label("Devolución conservada")).to_contain_text(
            last["id"], timeout=20000
        )
        expect(
            panel.get_by_role(
                "button", name="Revisar solicitud de devolución", exact=True
            )
        ).to_have_count(0)
        panel.locator("h2").scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "refunds-desktop.png"), full_page=True, animations="disabled"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        panel.locator("h2").scroll_into_view_if_needed()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.screenshot(
            path=str(out / "refunds-mobile.png"), full_page=True, animations="disabled"
        )
        passed(
            "the colorful refund balance, review and permanent history fit desktop and mobile"
        )
        assert call("GET", "/customer-collections/" + original["id"]) == original
        assert call("GET", "/customer-refunds/" + first["id"])["state"] == "DEVUELTA"
        after = ledger()
        assert before == after and not errors, errors
        passed(
            "original collections and rider ledgers remain unchanged; no bank calls or JavaScript exceptions"
        )
        admin_ctx.close()
        manager_ctx.close()
        browser.close()
    (out / "results.json").write_text(
        json.dumps(
            dict(
                checks=checks,
                errors=errors,
                instance=state["instance"],
                order_id=oid,
                collection_id=original["id"],
                refund_ids=[first["id"], second["id"], last["id"]],
                ledger_before=before,
                ledger_after=after,
                expected_lost_response_simulated=True,
                bank_transfer_performed=False,
            ),
            indent=2,
        )
    )
    print(json.dumps(dict(checks=len(checks), errors=errors)))


if __name__ == "__main__":
    main()

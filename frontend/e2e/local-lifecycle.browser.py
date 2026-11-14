"""Exercise real operational/ledger endpoints only in the marked local lab."""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", required=True)
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

    if sql("SELECT id FROM local_test_instance") != state["instance"]:
        raise SystemExit("Dedicated laboratory marker required; no writes performed")
    local_test.check(state, authenticate=False)
    users = json.loads(local_test.ACCOUNTS.read_text())
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors, orders, payouts, contexts = [], [], [], [], []
    run = uuid4().hex[:12]
    budget = {}

    def passed(message):
        checks.append(message)
        print("passed:", message, flush=True)

    def checkpoint():
        (out / "progress.json").write_text(
            json.dumps(
                {
                    "run": run,
                    "rider_id": rider_id,
                    "created_order_ids": orders,
                    "payout_ids": payouts,
                    "completed_checks": checks,
                },
                indent=2,
            )
            + "\n"
        )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        def login(account, home):
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            contexts.append(context)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.locator("input[type=email]").fill(account["email"])
            page.locator("input[type=password]").fill(account["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(base + home, timeout=30000)
            token = page.evaluate('localStorage.getItem("access_token")')
            assert isinstance(token, str) and token
            return page, {"Authorization": "Bearer " + token}

        def call(page, headers, method, path, *, expected=200, **kwargs):
            key = headers["Authorization"]
            remaining, reset = budget.get(key, (60, 0))
            if remaining <= 3 and reset > time.time():
                # Keep the application's real quotas, including during CI.
                time.sleep(min(60, reset - time.time() + 0.25))
            response = page.request.fetch(
                api + path, method=method, headers=headers, **kwargs
            )
            budget[key] = (
                int(response.headers.get("x-ratelimit-remaining", "60")),
                float(response.headers.get("x-ratelimit-reset", "0")),
            )
            assert (
                response.status == expected
            ), f"{method} {path}: {response.status} {response.text()}"
            return response.json()

        admin, staff = login(users["SUPERADMIN"], "/manager")
        identity = call(admin, staff, "GET", "/auth/me")
        assert identity["id"] == sql(
            "SELECT id FROM users WHERE email='admin.local-test@example.com'"
        )
        settings = call(admin, staff, "GET", "/settings")
        assert Decimal(str(settings["rider_delivery_bonus"])) == Decimal("2.5")
        assert Decimal(str(settings["rider_failed_attempt_bonus"])) == Decimal("1")
        passed(
            "API identity matches the marked database; canonical lab bonus fixtures verified"
        )

        account = {
            "email": "ciclo-" + run + "@example.com",
            "password": secrets.token_urlsafe(24),
        }
        rider = call(
            admin,
            staff,
            "POST",
            "/riders",
            expected=201,
            data={
                **account,
                "first_name": "Ciclo",
                "last_name": run,
                "phone": "+584120000000",
                "vehicle_type": "MOTO",
                "vehicle_plate": "TEST-" + run[:6],
                "vehicle_model": "Solo laboratorio",
            },
        )
        rider_id = rider["id"]
        checkpoint()
        operator, operations = login(users["OPERADOR"], "/operator")

        def create_order():
            order = call(
                operator,
                operations,
                "POST",
                "/orders",
                expected=201,
                data={
                    "customer_name": "Ciclo " + run,
                    "customer_phone": "+584120000000",
                    "pickup_address": "Origen sintético",
                    "delivery_address": "Destino sintético",
                    "delivery_contact": "Destinatario de pruebas",
                    "items": [
                        {
                            "product_name": "Producto de pruebas",
                            "quantity": 1,
                            "unit_price": "10.00",
                        }
                    ],
                    "subtotal": 10,
                    "delivery_fee": 2,
                    "total": 12,
                },
            )
            orders.append(order["id"])
            checkpoint()
            return order["id"]

        first_order = create_order()
        call(
            operator,
            operations,
            "PATCH",
            "/orders/" + first_order + "/assign",
            expected=400,
            data={"rider_id": rider_id},
        )
        assert (
            call(operator, operations, "GET", "/orders/" + first_order)["status"]
            == "PENDIENTE"
        )
        passed("operator cannot assign a rider before required documents are approved")

        for kind in ("LICENCIA", "DOCUMENTO_IDENTIDAD", "REGISTRO_VEHICULO", "SEGURO"):
            document = call(
                admin,
                staff,
                "POST",
                "/riders/" + rider_id + "/documents/upload",
                multipart={
                    "type": kind,
                    "file": {
                        "name": "test-" + kind + ".pdf",
                        "mimeType": "application/pdf",
                        "buffer": b"%PDF-1.4\n% Synthetic laboratory document, no legal validity\n%%EOF\n",
                    },
                },
            )
            call(
                admin,
                staff,
                "PATCH",
                "/riders/documents/" + document["id"] + "/status",
                data={"status": "APROBADO", "expected_revision": document["revision"]},
            )
        assert call(admin, staff, "GET", "/riders/" + rider_id)["status"] == "ACTIVO"
        passed(
            "four real uploads and conditional administrative reviews activate the dedicated test rider"
        )

        rider_page, own = login(account, "/rider")
        identity_rider = call(rider_page, own, "GET", "/auth/me")
        assert call(rider_page, own, "GET", "/riders/me")["id"] == rider_id
        call(rider_page, own, "GET", "/orders/" + first_order, expected=403)
        call(rider_page, own, "PATCH", "/riders/" + rider_id + "/online?online=true")
        assert (
            Decimal(str(call(rider_page, own, "GET", "/payouts/balance")["available"]))
            == 0
        )
        passed(
            "operator/rider logins reach their own areas; unassigned order access is denied and balance starts at zero"
        )

        def assigned(order_id):
            order = call(
                operator,
                operations,
                "PATCH",
                "/orders/" + order_id + "/assign",
                data={"rider_id": rider_id},
            )
            assert order["status"] == "ASIGNADO"
            return order["delivery"]["id"]

        def advance(delivery_id):
            call(
                rider_page,
                own,
                "PATCH",
                "/deliveries/" + delivery_id + "/status",
                data={"status": "EN_PICKUP"},
            )
            call(
                rider_page,
                own,
                "POST",
                "/deliveries/" + delivery_id + "/start",
                data={"lat": 0, "lng": 0},
            )

        for index in range(4):
            order_id = first_order if index == 0 else create_order()
            delivery_id = assigned(order_id)
            if index == 0:
                rider_page.goto(
                    base + "/rider/my-orders/" + order_id, wait_until="domcontentloaded"
                )
                for label, state_value in [
                    ("Recolectar Pedido", "RECOLECTADO"),
                    ("En Ruta", "EN_RUTA"),
                    ("Entregado", "ENTREGADO"),
                ]:
                    button = rider_page.get_by_role("button", name=label, exact=True)
                    expect(button).to_be_enabled(timeout=20000)
                    button.click()
                    expect(
                        rider_page.get_by_text("Orden: " + state_value, exact=True)
                    ).to_be_visible(timeout=20000)
                rider_page.set_viewport_size({"width": 390, "height": 844})
                rider_page.screenshot(
                    path=str(out / "rider-completed-mobile.png"),
                    full_page=True,
                    animations="disabled",
                )
                assert rider_page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth+1"
                )
                passed(
                    "rider completes pickup, route and delivery using the real interface, including a mobile receipt"
                )
            else:
                advance(delivery_id)
                assert (
                    call(operator, operations, "GET", "/orders/" + order_id)["status"]
                    == "EN_RUTA"
                )
                call(
                    rider_page,
                    own,
                    "POST",
                    "/deliveries/" + delivery_id + "/complete",
                    data={"customer_name_received": "Prueba"},
                )
            order = call(operator, operations, "GET", "/orders/" + order_id)
            assert (
                order["status"] == "ENTREGADO"
                and order["delivery"]["status"] == "COMPLETADA"
            )
            call(
                rider_page,
                own,
                "POST",
                "/deliveries/" + delivery_id + "/complete",
                expected=400,
                data={},
            )
        passed(
            "four completed orders agree with their deliveries; completion replay cannot pay twice"
        )

        for cause, reward in [
            ("COMERCIO_CERRADO", Decimal("1")),
            ("REPARTIDOR_ERROR_PROPIO", Decimal("0")),
        ]:
            order_id = create_order()
            delivery_id = assigned(order_id)
            if cause == "COMERCIO_CERRADO":
                rider_page.goto(
                    base + "/rider/my-orders/" + order_id, wait_until="domcontentloaded"
                )
                rider_page.get_by_role(
                    "button", name="Recolectar Pedido", exact=True
                ).click()
                expect(
                    rider_page.get_by_text("Orden: RECOLECTADO", exact=True)
                ).to_be_visible(timeout=20000)
                rider_page.get_by_role(
                    "button", name="Reportar Fallo", exact=True
                ).click()
                dialog = rider_page.get_by_role(
                    "dialog", name="Reportar Entrega Fallida"
                )
                expect(dialog).to_be_visible()
                expect(
                    dialog.get_by_role("button", name="Confirmar Reporte")
                ).to_be_disabled()
                dialog.get_by_role(
                    "combobox", name=re.compile("Causa del fallo")
                ).select_option(cause)
                rider_page.screenshot(
                    path=str(out / "rider-pickup-failure-mobile.png"),
                    full_page=True,
                    animations="disabled",
                )
                with rider_page.expect_response(
                    lambda response: response.url.endswith(
                        "/deliveries/" + delivery_id + "/fail"
                    )
                    and response.request.method == "POST"
                ) as report:
                    dialog.get_by_role(
                        "button", name="Confirmar Reporte", exact=True
                    ).click()
                assert report.value.status == 200
                failed = report.value.json()
                expect(
                    rider_page.get_by_text("Orden: FALLIDO", exact=True)
                ).to_be_visible(timeout=20000)
                assert not failed.get("left_pickup_at")
            else:
                advance(delivery_id)
                failed = call(
                    rider_page,
                    own,
                    "POST",
                    "/deliveries/" + delivery_id + "/fail",
                    data={"failure_cause": cause},
                )
            assert failed["status"] == "FALLIDA" and failed["is_bonificable"] == (
                reward > 0
            )
            if reward > 0:
                assert Decimal(str(failed["locked_bonus_amount"])) == reward
            else:
                assert failed["locked_bonus_amount"] is None
                assert failed["locked_bonus_type"] is None
            assert (
                call(operator, operations, "GET", "/orders/" + order_id)["status"]
                == "FALLIDO"
            )
            call(
                rider_page,
                own,
                "POST",
                "/deliveries/" + delivery_id + "/complete",
                expected=400,
                data={},
            )
        passed(
            "a closed business is reported from pickup in the real UI; its bonus is exact, rider-caused failure earns zero and neither can become success"
        )

        cancelled_order = create_order()
        cancelled_delivery = assigned(cancelled_order)
        call(
            operator,
            operations,
            "PATCH",
            "/orders/" + cancelled_order + "/cancel",
            expected=403,
            data={"reason": "Solo gerencia"},
        )
        call(
            admin,
            staff,
            "PATCH",
            "/orders/" + cancelled_order + "/cancel",
            data={"reason": "Cierre de laboratorio"},
        )
        call(
            rider_page,
            own,
            "POST",
            "/deliveries/" + cancelled_delivery + "/start",
            expected=409,
            data={},
        )
        passed(
            "operator cancellation is denied; administrative cancellation prevents further delivery progress"
        )

        def balance():
            return call(rider_page, own, "GET", "/payouts/balance")

        assert Decimal(str(balance()["available"])) == Decimal("11")
        passed(
            "real earned balance is 4 delivery bonuses plus 1 failed-attempt bonus, with no seeded funds"
        )
        first_key = "lifecycle-reject-" + run
        request = {"amount": 10, "idempotency_key": first_key}
        payout = call(
            rider_page, own, "POST", "/payouts/request", expected=201, data=request
        )
        payouts.append(payout["id"])
        checkpoint()
        replay = call(
            rider_page, own, "POST", "/payouts/request", expected=201, data=request
        )
        assert replay["id"] == payout["id"]
        assert Decimal(str(balance()["available"])) == 1
        call(
            rider_page,
            own,
            "POST",
            "/payouts/request",
            expected=400,
            data={"amount": 10, "idempotency_key": "lifecycle-overdraw-" + run},
        )
        call(
            admin,
            staff,
            "PATCH",
            "/payouts/" + payout["id"] + "/reject",
            data={"reason": "Prueba de liberación de reserva"},
        )
        assert Decimal(str(balance()["available"])) == 11
        passed(
            "payout replay preserves one reservation; overdraft is denied and rejection releases the full reservation"
        )

        payout = call(
            rider_page,
            own,
            "POST",
            "/payouts/request",
            expected=201,
            data={"amount": 10, "idempotency_key": "lifecycle-approve-" + run},
        )
        payouts.append(payout["id"])
        checkpoint()
        result = call(admin, staff, "PATCH", "/payouts/" + payout["id"] + "/approve")
        assert result["status"] == "EN_PROCESO"
        assert Decimal(str(balance()["available"])) == 1
        call(
            admin, staff, "PATCH", "/payouts/" + payout["id"] + "/approve", expected=400
        )
        assert Decimal(str(balance()["available"])) == 1
        receipts = call(rider_page, own, "GET", "/financial/riders/me/earnings")[
            "items"
        ]
        assert len(receipts) == 6 and not any(
            row.get("is_fallback") for row in receipts
        )
        credits = sum(
            Decimal(str(row["amount"]))
            for row in receipts
            if row["transaction_type"] != "RETIRO"
        )
        debits = sum(
            Decimal(str(row["amount"]))
            for row in receipts
            if row["transaction_type"] == "RETIRO"
        )
        assert credits == 11 and debits == 10
        assert len({row["idempotency_key"] for row in receipts}) == 6
        passed(
            "administrative approval posts one withdrawal; ledger reconciles 11 earned - 10 withdrawn = 1 available"
        )
        assert all(row["currency"] == "USD" for row in receipts)
        assert balance()["currency"] == "USD" and payout["currency"] == "USD"
        passed("new delivery earnings and withdrawal receipts explicitly preserve USD")

        # Deliberately unknown-unit synthetic fixtures, never a conversion/backfill.
        # The marker and real API identity were checked before any SQL writes.
        unknown_entry, unknown_payout = str(uuid4()), str(uuid4())
        sql(
            "INSERT INTO financials (id,rider_id,currency_code,amount,balance_before,balance_after,transaction_type,status,description,source_type,created_at) VALUES ('"
            + unknown_entry
            + "','"
            + rider_id
            + "',NULL,1000,0,1000,'INGRESO','PROCESADO','DATO SINTETICO: moneda no verificada','TEST_UNVERIFIED_CURRENCY',NOW())"
        )
        sql(
            "INSERT INTO payouts (id,rider_id,currency_code,amount,status,method,requested_at,requested_by_user_id) VALUES ('"
            + unknown_payout
            + "','"
            + rider_id
            + "',NULL,1000,'PENDIENTE','TRANSFERENCIA',NOW(),'"
            + identity_rider["id"]
            + "')"
        )
        after_unknown = balance()
        assert Decimal(str(after_unknown["available"])) == 1
        assert (
            after_unknown["unverified_financial_count"] == 1
            and after_unknown["unverified_payout_count"] == 1
        )
        call(
            rider_page,
            own,
            "POST",
            "/payouts/request",
            expected=400,
            data={"amount": 10, "idempotency_key": "unknown-funds-" + run},
        )
        call(
            admin,
            staff,
            "PATCH",
            "/payouts/" + unknown_payout + "/approve",
            expected=409,
        )
        passed(
            "unknown-unit income and reservations neither fund nor debit the real USD account"
        )

        rider_page.goto(base + "/rider/earnings", wait_until="domcontentloaded")
        expect(
            rider_page.get_by_role("heading", name="Mis Ganancias", exact=True)
        ).to_be_visible(timeout=20000)
        expect(
            rider_page.get_by_text(
                "1 movimientos anteriores requieren revisión de moneda.", exact=True
            )
        ).to_be_visible()
        expect(
            rider_page.get_by_text(
                "1 retiros anteriores conservan su moneda sin verificar.", exact=True
            )
        ).to_be_visible()
        expect(
            rider_page.get_by_role("button", name="Solicitar Retiro", exact=True)
        ).to_be_disabled()
        rider_page.set_viewport_size({"width": 390, "height": 844})
        rider_page.screenshot(
            path=str(out / "usd-earnings-mobile.png"),
            full_page=True,
            animations="disabled",
        )
        assert rider_page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        admin.goto(
            base + "/manager/financial/payouts/" + unknown_payout,
            wait_until="domcontentloaded",
        )
        expect(
            admin.get_by_role("button", name="Aprobar retiro", exact=True)
        ).to_be_disabled(timeout=20000)
        passed(
            "real colorful rider UI separates unverified history and staff cannot approve an unknown-unit withdrawal"
        )
        assert (
            sql(
                "SELECT amount::text || ':' || balance_before::text || ':' || balance_after::text FROM financials WHERE id='"
                + unknown_entry
                + "'"
            )
            == "1000.00:0.00:1000.00"
        )
        for context in contexts:
            context.close()
        browser.close()
    assert not errors, errors
    passed(
        "zero JavaScript exceptions; user actions use real authenticated endpoints and unknown-unit fixtures are explicitly synthetic"
    )
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "run": run,
                "rider_id": rider_id,
                "created_order_ids": orders,
                "payout_ids": payouts,
                "currency": "USD",
                "unverified_currency_fixture_ids": [unknown_entry, unknown_payout],
                "earned": "11.00",
                "withdrawal_posted": "10.00",
                "available": "1.00",
                "bank_transfer_performed": False,
                "external_messages_sent": False,
                "mode": "real isolated laboratory; administrative accounting, no bank settlement",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

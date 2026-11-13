"""Real HTTP/browser checks; writes only after verifying the dedicated lab marker."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    state = local_test.configuration()
    command = local_test.compose(state, local_test.local_docker())
    marker = subprocess.check_output(
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
            "SELECT id FROM local_test_instance",
        ],
        text=True,
        env=local_test.compose_environment(),
    ).strip()
    if marker != state["instance"]:
        raise SystemExit(
            "Not the dedicated local laboratory; no browser writes allowed"
        )
    local_test.check(state)
    users = json.loads(local_test.ACCOUNTS.read_text())
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []

    def passed(name):
        checks.append(name)
        print("passed:", name, flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        def login(role):
            context = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                locale="es-VE",
                timezone_id="America/Caracas",
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.locator("input[type=email]").first.fill(users[role]["email"])
            page.locator("input[type=password]").first.fill(users[role]["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(
                re.compile("/(?:manager|operator|rider)(?:/|$)"), timeout=30000
            )
            token = page.evaluate('localStorage.getItem("access_token")')
            assert isinstance(token, str) and token
            return context, page, {"Authorization": "Bearer " + token}

        context, page, headers = login("SUPERADMIN")
        passed("real browser login establishes the superadministrator session")
        page.goto(base + "/manager/admin/settings", wait_until="domcontentloaded")
        fee = page.get_by_role("textbox", name=re.compile("^Tarifa base de envío"))
        expect(fee).to_be_enabled(timeout=20000)
        saved = page.request.get(api + "/settings", headers=headers).json()
        original = saved["delivery_fee_base"]
        proposal = original + 0.25
        changed = page.request.patch(
            api + "/settings",
            headers={**headers, "If-Match": '"' + saved["revision"] + '"'},
            data={"delivery_fee_base": proposal},
        )
        assert changed.status == 200
        revision = changed.json()["revision"]
        try:
            assert (
                page.request.get(api + "/settings", headers=headers).json()[
                    "delivery_fee_base"
                ]
                == proposal
            )
            stale = page.request.patch(
                api + "/settings",
                headers={**headers, "If-Match": '"' + saved["revision"] + '"'},
                data={"delivery_fee_base": proposal + 1},
            )
            assert stale.status == 412
            assert (
                page.request.get(api + "/settings", headers=headers).json()[
                    "delivery_fee_base"
                ]
                == proposal
            )
            passed(
                "real conditional write persists and a stale revision cannot overwrite it"
            )
        finally:
            restored = page.request.patch(
                api + "/settings",
                headers={**headers, "If-Match": '"' + revision + '"'},
                data={"delivery_fee_base": original},
            )
            assert (
                restored.status == 200
            ), "The lab configuration changed concurrently; original value was not overwritten"
        page.reload(wait_until="domcontentloaded")
        expect(fee).to_have_value(str(original).removesuffix(".0"))
        page.get_by_role("textbox", name="Bono propuesto", exact=True).fill("0")
        page.get_by_role("textbox", name=re.compile("^Días de histórico")).fill("7")
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        region = page.get_by_role("region", name="Resultado confirmado de simulación")
        expect(region).to_be_visible(timeout=20000)
        expect(region).to_contain_text("Período histórico consultado")
        expect(region).to_contain_text("Sin entregas bonificadas en el período")
        passed(
            "real simulation reads the migrated DB and identifies the empty historical sample"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        region.scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "real-settings-mobile.png"),
            animations="disabled",
            full_page=True,
        )
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
        passed("real settings and simulation fit the mobile viewport")
        created = page.request.post(
            api + "/orders",
            headers=headers,
            data={
                "customer_name": "Prueba funcional " + uuid4().hex[:8],
                "customer_phone": "+584120000000",
                "pickup_address": "Origen de laboratorio",
                "delivery_address": "Destino de laboratorio",
                "delivery_contact": "Destinatario de prueba",
                "items": [{"name": "Producto de prueba", "quantity": 1, "price": 10}],
                "subtotal": 10,
                "delivery_fee": 2,
                "total": 12,
                "declared_value": 10,
            },
        )
        assert created.status == 201
        order = created.json()
        order_id = order["id"]
        assert (
            page.request.get(api + "/orders/" + order_id, headers=headers).json()[
                "status"
            ]
            == "PENDIENTE"
        )
        cancelled = page.request.patch(
            api + "/orders/" + order_id + "/cancel",
            headers=headers,
            data={"reason": "Cierre de prueba funcional local"},
        )
        assert cancelled.status == 200
        assert (
            page.request.get(api + "/orders/" + order_id, headers=headers).json()[
                "status"
            ]
            == "CANCELADO"
        )
        passed(
            "a real test order is created, read back and cancelled with confirmed persisted status"
        )
        context.close()
        context, page, headers = login("GERENTE")
        page.goto(base + "/manager/admin/settings", wait_until="domcontentloaded")
        fee = page.get_by_role("textbox", name=re.compile("^Tarifa base de envío"))
        expect(fee).to_be_disabled(timeout=20000)
        expect(
            page.get_by_role("button", name="Revisar cambios", exact=True)
        ).to_have_count(0)
        current = page.request.get(api + "/settings", headers=headers).json()
        denied = page.request.patch(
            api + "/settings",
            headers={**headers, "If-Match": '"' + current["revision"] + '"'},
            data={"delivery_fee_base": 999},
        )
        assert denied.status == 403
        assert (
            page.request.get(api + "/settings", headers=headers).json()[
                "delivery_fee_base"
            ]
            == original
        )
        passed(
            "real manager session has a read-only form and backend rejects unauthorized writes"
        )
        context.close()
        browser.close()
    assert not errors, errors
    passed("no JavaScript exceptions and no mocked API responses")
    if args.restart:
        # The marker was checked before any changes; this is only this owned lab.
        def stored_counts():
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
                    "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM orders)",
                ],
                text=True,
                env=local_test.compose_environment(),
            ).strip()

        before = stored_counts()
        for action in (["down"], ["up", "--no-build"]):
            subprocess.run(
                [sys.executable, str(local_test.ROOT / "scripts/local_test.py")]
                + action,
                check=True,
            )
        assert (
            stored_counts() == before
        ), "Restart changed seeded account or order counts"
        code, tokens = local_test.api_request(
            api,
            "/auth/login",
            "POST",
            {
                "username": users["SUPERADMIN"]["email"],
                "password": users["SUPERADMIN"]["password"],
            },
            form=True,
        )
        assert code == 200
        code, persisted = local_test.api_request(
            api, "/orders/" + order_id, token=tokens["access_token"]
        )
        assert code == 200 and persisted["status"] == "CANCELADO"
        passed(
            "stop/start preserves credentials and the cancelled order without duplicating seed data"
        )
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "mode": "real isolated laboratory",
                "created_and_cancelled_order_id": order_id,
                "configuration_restored": True,
                "real_business_writes": "conditional config change and restoration, one order creation and cancellation",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

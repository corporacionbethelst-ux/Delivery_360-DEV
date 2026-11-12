"""Local settings review; synthetic reads/calculations, no persistent writes."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-platform-settings")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, reads, calculations, writes, errors, pending = [], [], [], [], [], []
    state = {
        "role": "GERENTE",
        "read_failure": False,
        "invalid": False,
        "fee": 0,
        "bonus": 0,
        "calculation_failure": False,
        "hold": False,
    }
    saved = {
        "delivery_fee_base": 0,
        "commission_percentage": 12.12345,
        "min_order_amount": None,
        "rider_delivery_bonus": 0,
        "rider_failed_attempt_bonus": None,
        "active_zones": ["Centro, Norte", "Sur"],
        "support_email": None,
        "maintenance_mode": False,
        "updated_at": "2026-11-09T12:00:00",
        "updated_by_user_id": "local-admin",
    }

    def passed(text):
        checks.append(text)
        print("passed:", text, flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1150},
            locale="es-VE",
            reduced_motion="reduce",
            service_workers="block",
        )
        context.set_default_timeout(15000)
        context.add_cookies(
            [{"name": "auth-token", "value": "synthetic-token", "url": base}]
        )
        context.add_init_script(
            "localStorage.setItem('app_version','1.2.1'); localStorage.setItem('access_token','synthetic-token'); localStorage.setItem('refresh_token','synthetic-refresh');"
        )
        context.route_web_socket("**/*", lambda socket: None)

        def intercept(route):
            target = urlparse(route.request.url)
            path = target.path
            business = (
                path.startswith("/api/v1/") or target.netloc != urlparse(base).netloc
            )
            headers = {
                "access-control-allow-origin": base,
                "access-control-allow-headers": "authorization,content-type",
                "access-control-allow-methods": "GET,POST,OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif (
                path == "/api/v1/settings/simulate-bonus"
                and route.request.method == "POST"
            ):
                request = route.request.post_data_json
                calculations.append(request)
                result = {
                    "current_monthly_cost": 100,
                    "projected_monthly_cost": 100 + request["new_base_bonus"] * 10,
                    "difference": request["new_base_bonus"] * 10,
                    "percentage_increase": request["new_base_bonus"] * 10,
                    "message": "Cálculo sintético del período",
                }
                if state["hold"]:
                    pending.append((route, result, headers))
                    page.evaluate("window.__settingsCalculationHeld = true")
                else:
                    route.fulfill(
                        status=503 if state["calculation_failure"] else 200,
                        json=(
                            {"detail": "Synthetic calculation failure"}
                            if state["calculation_failure"]
                            else result
                        ),
                        headers=headers,
                    )
            elif business and route.request.method != "GET":
                writes.append({"path": path, "method": route.request.method})
                route.abort()
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "settings-actor-85",
                        "role": state["role"],
                        "first_name": "Configuración",
                        "last_name": "Local",
                        "email": "staff@example.test",
                        "is_active": True,
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    headers=headers,
                )
            elif path == "/api/v1/settings":
                reads.append(path)
                row = {
                    **saved,
                    "delivery_fee_base": state["fee"],
                    "rider_delivery_bonus": state["bonus"],
                }
                if state["invalid"]:
                    row["maintenance_mode"] = "false"
                route.fulfill(
                    status=503 if state["read_failure"] else 200,
                    json=(
                        {"detail": "Synthetic read failure"}
                        if state["read_failure"]
                        else row
                    ),
                    headers=headers,
                )
            elif business:
                route.fulfill(
                    json=[] if "alerts" in path else {"items": [], "unread_count": 0},
                    headers=headers,
                )
            else:
                route.continue_()

        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/manager/admin/settings", wait_until="domcontentloaded")
        content = page.locator("main main")

        def field(name):
            return page.get_by_role("textbox", name=re.compile("^" + re.escape(name)))

        fee, commission, minimum = (
            field("Tarifa base de envío"),
            field("Comisión"),
            field("Pedido mínimo"),
        )
        proposal = page.get_by_role("textbox", name="Bono propuesto", exact=True)
        days = field("Días de histórico")
        result = page.get_by_role(
            "region", name="Resultado confirmado de simulación", exact=True
        )
        expect(fee).to_have_value("0")
        expect(fee).to_be_disabled()
        expect(commission).to_have_value("12.12345")
        expect(minimum).to_have_value("")
        expect(field("Email de soporte")).to_have_value("")
        expect(field("Zonas activas")).to_have_value("Centro, Norte\nSur")
        expect(
            page.get_by_role("button", name="Revisar cambios", exact=True)
        ).to_have_count(0)
        expect(proposal).to_have_value("0")
        passed(
            "manager reads actual zero, nulls, precision and comma-containing zones with no save control or invented baseline"
        )
        days.fill("7")
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        expect(result).to_be_visible()
        expect(result).to_contain_text("Resultado para bono 0 y 7 días")
        assert calculations[-1] == {"new_base_bonus": 0, "days_projection": 7}
        expect(result.get_by_text("COP", exact=False)).to_have_count(0)
        passed(
            "manager can calculate an explicit zero proposal for seven historical days without saving or converting currency"
        )
        state["role"] = "SUPERADMIN"
        page.reload(wait_until="domcontentloaded")
        expect(fee).to_be_enabled()
        expect(
            page.get_by_role("button", name="Revisar cambios", exact=True)
        ).to_be_disabled()
        expect(result).to_have_count(0)
        page.screenshot(
            path=str(out / "settings-desktop.png"),
            animations="disabled",
            full_page=True,
        )
        passed(
            "superadministrator has the actual edit form and reload starts from confirmed settings with no stale simulation"
        )
        fee.fill("")
        page.get_by_role("button", name="Revisar cambios", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text("vacío no equivale a cero")
        expect(page.get_by_role("dialog")).to_have_count(0)
        fee.fill("4")
        page.get_by_role("button", name="Revisar cambios", exact=True).click()
        confirmation = page.get_by_role(
            "dialog", name="Confirmar cambios de configuración", exact=True
        )
        expect(confirmation).to_contain_text("Guardado: 0")
        expect(confirmation).to_contain_text("Propuesto: 4")
        expect(confirmation.get_by_text("Comisión (%)", exact=True)).to_have_count(0)
        page.screenshot(
            path=str(out / "settings-review-desktop.png"), animations="disabled"
        )
        confirmation.get_by_role("button", name="Cancelar", exact=True).click()
        passed(
            "empty amount is rejected and save review shows only edited fields before any persistent write"
        )
        page.get_by_role("button", name="Recargar configuración", exact=True).click()
        reload_dialog = page.get_by_role(
            "dialog", name="Recargar configuración", exact=True
        )
        reload_dialog.get_by_role(
            "button", name="Conservar borrador", exact=True
        ).click()
        expect(fee).to_have_value("4")
        page.get_by_role("button", name="Recargar configuración", exact=True).click()
        reload_dialog.get_by_role(
            "button", name="Descartar borrador y recargar", exact=True
        ).click()
        expect(fee).to_have_value("0")
        passed(
            "reloading a dirty form explicitly preserves or discards its draft instead of silently losing edits"
        )
        fee.fill("4")
        page.get_by_role("button", name="Revisar cambios", exact=True).click()
        state["fee"] = 9
        confirmation.get_by_role(
            "button", name="Confirmar guardado", exact=True
        ).click()
        expect(confirmation.get_by_role("alert")).to_contain_text(
            "cambió desde la lectura"
        )
        assert not writes
        confirmation.get_by_role(
            "button", name="Recargar y revisar", exact=True
        ).click()
        expect(fee).to_have_value("9")
        state["fee"] = 0
        page.get_by_role("button", name="Recargar configuración", exact=True).click()
        expect(fee).to_have_value("0")
        passed(
            "preflight detects a changed target value and stops before PATCH, with a confirmed reload of the actual new value"
        )
        field("Email de soporte").fill("support@example.com")
        page.get_by_role("button", name="Revisar cambios", exact=True).click()
        expect(confirmation).to_contain_text("Email de soporte")
        expect(confirmation).to_contain_text("Sin configurar")
        expect(confirmation).to_contain_text("support@example.com")
        expect(
            confirmation.get_by_text("Tarifa base de envío", exact=True)
        ).to_have_count(0)
        confirmation.get_by_role("button", name="Cancelar", exact=True).click()
        passed(
            "configuring a missing email does not populate or overwrite unrelated financial values"
        )
        page.get_by_role("button", name="Recargar configuración", exact=True).click()
        reload_dialog.get_by_role(
            "button", name="Descartar borrador y recargar", exact=True
        ).click()
        expect(fee).to_have_value("0")
        days.fill("91")
        before = len(calculations)
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text("1 a 90")
        assert len(calculations) == before
        days.fill("30")
        proposal.fill("2,5")
        state["hold"] = True
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        page.wait_for_function("window.__settingsCalculationHeld === true")
        expect(proposal).to_be_disabled()
        expect(days).to_be_disabled()
        expect(
            page.get_by_role("button", name="Calculando…", exact=True)
        ).to_be_disabled()
        assert len(pending) == 1
        route, body, headers = pending.pop()
        state["hold"] = False
        route.fulfill(json=body, headers=headers)
        expect(result).to_contain_text("Resultado para bono 2.5 y 30 días")
        passed(
            "invalid history windows do not calculate and pending simulation locks controls until its exact response arrives"
        )
        state["calculation_failure"] = True
        proposal.fill("9")
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text(
            "No se pudo confirmar el cálculo"
        )
        expect(result).to_contain_text("Resultado para bono 2.5 y 30 días")
        state["calculation_failure"] = False
        page.set_viewport_size({"width": 390, "height": 844})
        result.scroll_into_view_if_needed()
        page.screenshot(path=str(out / "simulation-mobile.png"), animations="disabled")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        passed(
            "failed recalculation retains the old result with its actual parameters and the simulator fits mobile"
        )
        fee.fill("4")
        page.get_by_role("button", name="Revisar cambios", exact=True).click()
        expect(confirmation).to_be_visible()
        assert confirmation.bounding_box()["width"] <= 390
        page.screenshot(
            path=str(out / "settings-review-mobile.png"), animations="disabled"
        )
        confirmation.get_by_role("button", name="Cancelar", exact=True).click()
        fee.scroll_into_view_if_needed()
        page.screenshot(path=str(out / "settings-mobile.png"), animations="disabled")
        passed(
            "mobile settings and the exact-change confirmation remain bounded and cancelable"
        )
        state["read_failure"] = True
        page.reload(wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_contain_text(
            "No se pudo confirmar la configuración"
        )
        expect(fee).to_have_count(0)
        state["read_failure"] = False
        page.get_by_role("button", name="Reintentar configuración", exact=True).click()
        expect(fee).to_have_value("0")
        passed(
            "initial read failure exposes retry without an editable form of default values"
        )
        state["invalid"] = True
        page.reload(wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_contain_text(
            "No se pudo confirmar la configuración"
        )
        expect(fee).to_have_count(0)
        state["invalid"] = False
        state["bonus"] = None
        page.get_by_role("button", name="Reintentar configuración", exact=True).click()
        expect(proposal).to_have_value("")
        expect(
            page.get_by_role("button", name="Simular impacto", exact=True)
        ).to_be_disabled()
        passed(
            "malformed boolean data is rejected and an unconfigured saved bonus never becomes a fabricated simulation baseline"
        )
        assert not writes, writes
        assert not errors, errors
        passed(
            "zero persistent business writes and zero JavaScript exceptions; calculation POSTs are synthetic"
        )
        (out / "results.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "reads": reads,
                    "synthetic_calculations": calculations,
                    "writes": writes,
                    "errors": errors,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()


if __name__ == "__main__":
    main()

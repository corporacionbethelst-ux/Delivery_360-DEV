"""Local settings review; synthetic reads/updates/calculations, no real writes."""

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
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
    conditional_updates = []
    state = {
        "role": "GERENTE",
        "read_failure": False,
        "invalid": False,
        "fee": "0.00",
        "bonus": "0.00",
        "calculation_failure": False,
        "hold": False,
        "revision": "s2-" + "a" * 64,
        "save_outcome": "unexpected",
        "empty_history": False,
        "undated": 0,
        "wrong_calculation": False,
    }
    saved = {
        "version": 2,
        "currency": "USD",
        "units_basis": "prospective_usd_parameters",
        "field_issues": [],
        "legacy_revision": "s1-" + "a" * 64,
        "revision": "s2-" + "a" * 64,
        "delivery_fee_base": "0.00",
        "commission_percentage": "12.12345",
        "min_order_amount": None,
        "rider_delivery_bonus": "0.00",
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
                "access-control-allow-headers": "authorization,content-type,if-match",
                "access-control-allow-methods": "GET,POST,PATCH,OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif (
                path == "/api/v1/settings/exact/v2"
                and route.request.method == "PATCH"
                and state["save_outcome"] in ("conflict", "confirmed")
            ):
                body = route.request.post_data_json
                precondition = route.request.headers.get("if-match")
                assert body == {"delivery_fee_base": "4.00"}
                assert precondition == '"' + state["revision"] + '"'
                conflict = state["save_outcome"] == "conflict"
                conditional_updates.append(
                    {
                        "body": body,
                        "if_match": precondition,
                        "status": 412 if conflict else 200,
                    }
                )
                if not conflict:
                    state["fee"] = "4.00"
                    state["revision"] = "s2-" + "b" * 64
                route.fulfill(
                    status=412 if conflict else 200,
                    json=(
                        {"detail": "Synthetic revision conflict"}
                        if conflict
                        else {
                            **saved,
                            "delivery_fee_base": state["fee"],
                            "revision": state["revision"],
                        }
                    ),
                    headers=headers,
                )
            elif (
                path == "/api/v1/settings/simulate-bonus/exact/v2"
                and route.request.method == "POST"
            ):
                request = route.request.post_data_json
                assert isinstance(request["new_base_bonus"], str)
                calculations.append(request)
                assert request["expected_settings_revision"] == state["revision"]
                applied = Decimal(str(request["new_base_bonus"])).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                completed, failed = (0, 0) if state["empty_history"] else (10, 2)
                recorded_success, recorded_failed = (
                    (0, 0) if state["empty_history"] else (100, 10)
                )
                historical = recorded_success + recorded_failed
                scenario = applied * completed + recorded_failed
                difference = scenario - historical
                percentage = (
                    (difference / historical * 100).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    if historical
                    else None
                )
                end = datetime(2026, 11, 13, 2, tzinfo=timezone.utc)
                result = {
                    "version": 2,
                    "scope": "uniform_bonus_usd_scenario",
                    "currency": "USD",
                    "actor": {"user_id": "settings-actor-85", "role": state["role"]},
                    "snapshot_basis": "single_statement_visibility",
                    "bank_verified": False,
                    "comparison_basis": "flat_bonus_same_usd_deliveries",
                    "history_days": request["days_projection"],
                    "period_start": (end - timedelta(days=request["days_projection"]))
                    .isoformat(timespec="microseconds")
                    .replace("+00:00", "Z"),
                    "period_end": end.isoformat(timespec="microseconds").replace(
                        "+00:00", "Z"
                    ),
                    "generated_at": end.isoformat(timespec="microseconds").replace(
                        "+00:00", "Z"
                    ),
                    "completed_deliveries": completed,
                    "failed_bonus_deliveries": failed,
                    "recorded_completed_bonus": format(
                        Decimal(recorded_success), ".2f"
                    ),
                    "recorded_failed_bonus": format(Decimal(recorded_failed), ".2f"),
                    "historical_cost": format(Decimal(historical), ".2f"),
                    "scenario_cost": format(scenario, ".2f"),
                    "difference": format(difference, ".2f"),
                    "percentage_change": (
                        format(Decimal(str(percentage)), ".2f")
                        if percentage is not None
                        else None
                    ),
                    "applied_bonus": format(applied, ".2f"),
                    "current_base_bonus": state["bonus"],
                    "settings_revision": state["revision"],
                    "candidate_deliveries": completed + failed + state["undated"] + 2,
                    "exclusions": {
                        "undated": state["undated"],
                        "unknown_currency": 2,
                        "other_currency": 0,
                        "no_bonus": 0,
                        "invalid_snapshot": 0,
                    },
                    "content_sha256": "e" * 64,
                }
                if state["wrong_calculation"]:
                    result["settings_revision"] = "s2-" + "c" * 64
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
            elif path == "/api/v1/settings/exact/v2":
                reads.append(path)
                row = {
                    **saved,
                    "revision": state["revision"],
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
        expect(fee).to_have_value("0.00")
        expect(fee).to_be_disabled()
        expect(commission).to_have_value("12.12345")
        expect(minimum).to_have_value("")
        expect(field("Email de soporte")).to_have_value("")
        expect(field("Zonas activas")).to_have_value("Centro, Norte\nSur")
        expect(
            page.get_by_role("button", name="Revisar cambios", exact=True)
        ).to_have_count(0)
        expect(proposal).to_have_value("0.00")
        passed(
            "manager reads actual zero, nulls, precision and comma-containing zones with no save control or invented baseline"
        )
        days.fill("7")
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        expect(result).to_be_visible()
        expect(result).to_contain_text("Resultado para bono USD 0,00 y 7 días")
        assert calculations[-1] == {
            "new_base_bonus": "0.00",
            "days_projection": 7,
            "expected_settings_revision": state["revision"],
        }
        expect(result.get_by_text("COP", exact=False)).to_have_count(0)
        passed(
            "manager can calculate an explicit zero proposal for seven historical days without saving or converting currency"
        )
        expect(result).to_contain_text("Período histórico consultado")
        expect(result).to_contain_text("No aplica multiplicadores de zona ni nivel")
        expect(result).to_contain_text("10 entregas × USD 0,00")
        page.screenshot(
            path=str(out / "scenario-desktop.png"),
            animations="disabled",
            full_page=True,
        )
        passed(
            "scenario identifies its actual historical bounds, flat-rate formula, sample counts and explicit USD-only exclusions"
        )
        state["wrong_calculation"] = True
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text("No se pudo confirmar")
        expect(result).to_contain_text("Resultado para bono USD 0,00 y 7 días")
        state["wrong_calculation"] = False
        passed(
            "response from another settings revision is rejected while the previous confirmed scenario remains visible"
        )
        state["empty_history"], state["undated"] = True, 3
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        expect(result).to_contain_text("Sin bonos USD elegibles en el período")
        expect(result).to_contain_text("Existen 3 cierres")
        expect(result).to_contain_text("histórico global")
        expect(result).to_contain_text("Sin base porcentual")
        state["empty_history"], state["undated"] = False, 0
        passed(
            "empty bounded history and globally undated records remain explicit, without a fabricated percentage denominator"
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
        expect(fee).to_have_value("0.00")
        passed(
            "reloading a dirty form explicitly preserves or discards its draft instead of silently losing edits"
        )
        fee.fill("4")
        page.get_by_role("button", name="Revisar cambios", exact=True).click()
        state["fee"] = "9.00"
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
        reload_dialog.get_by_role(
            "button", name="Descartar borrador y recargar", exact=True
        ).click()
        expect(fee).to_have_value("9.00")
        state["fee"] = "0.00"
        page.get_by_role("button", name="Recargar configuración", exact=True).click()
        expect(fee).to_have_value("0.00")
        passed(
            "preflight detects a changed target value and stops before PATCH, with a confirmed reload of the actual new value"
        )
        fee.fill("4")
        page.get_by_role("button", name="Revisar cambios", exact=True).click()
        state["save_outcome"] = "conflict"
        confirmation.get_by_role(
            "button", name="Confirmar guardado", exact=True
        ).click()
        expect(confirmation.get_by_role("alert")).to_contain_text("Otra persona cambió")
        expect(page.get_by_label(re.compile("^Tarifa base de envío"))).to_have_value(
            "4"
        )
        expect(
            confirmation.get_by_role("button", name="Confirmar guardado", exact=True)
        ).to_have_count(0)
        assert len(conditional_updates) == 1
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(
            path=str(out / "settings-conflict-mobile.png"), animations="disabled"
        )
        assert confirmation.bounding_box()["width"] <= 390
        confirmation.get_by_role(
            "button", name="Recargar y revisar", exact=True
        ).click()
        reload_dialog.get_by_role(
            "button", name="Conservar borrador", exact=True
        ).click()
        expect(fee).to_have_value("4")
        expect(
            page.get_by_role("button", name="Revisar cambios", exact=True)
        ).to_be_disabled()
        page.get_by_role("button", name="Recargar configuración", exact=True).click()
        reload_dialog.get_by_role(
            "button", name="Descartar borrador y recargar", exact=True
        ).click()
        expect(fee).to_have_value("0.00")
        page.set_viewport_size({"width": 1440, "height": 1150})
        passed(
            "synthetic server conflict preserves the mobile draft, blocks retries and asks before discarding edits"
        )
        fee.fill("4")
        page.get_by_role("button", name="Revisar cambios", exact=True).click()
        state["save_outcome"] = "confirmed"
        confirmation.get_by_role(
            "button", name="Confirmar guardado", exact=True
        ).click()
        expect(content.get_by_role("status")).to_contain_text(
            "Configuración guardada y confirmada"
        )
        expect(fee).to_have_value("4.00")
        assert len(conditional_updates) == 2
        state["save_outcome"] = "unexpected"
        state["fee"] = "0.00"
        page.get_by_role("button", name="Recargar configuración", exact=True).click()
        expect(fee).to_have_value("0.00")
        passed(
            "synthetic save sends the exact If-Match revision and minimal body, then confirms the returned values"
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
        expect(fee).to_have_value("0.00")
        days.fill("91")
        before = len(calculations)
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text("1 y 90")
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
        expect(result).to_contain_text("Resultado para bono USD 2,50 y 30 días")
        passed(
            "invalid history windows do not calculate and pending simulation locks controls until its exact response arrives"
        )
        state["calculation_failure"] = True
        proposal.fill("9")
        page.get_by_role("button", name="Simular impacto", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text(
            "No se pudo confirmar el cálculo"
        )
        expect(result).to_contain_text("Resultado para bono USD 2,50 y 30 días")
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
        expect(fee).to_have_value("0.00")
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
            "zero persistent business writes and zero JavaScript exceptions; PATCH and calculation POSTs are synthetic"
        )
        (out / "results.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "reads": reads,
                    "synthetic_calculations": calculations,
                    "synthetic_updates": conditional_updates,
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

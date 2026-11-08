"""Validate Next production routing and the Zod 4 form with synthetic API data."""

import argparse
import csv
import io
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-production-smoke")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Only a local preview is allowed")
    artifacts = Path(args.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    reads, writes, errors, checks = [], [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium, headless=True, args=["--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, accept_downloads=True
        )
        context.set_default_timeout(15000)
        context.add_cookies(
            [{"name": "auth-token", "value": "synthetic-token", "url": base}]
        )
        context.add_init_script(
            """if (!localStorage.getItem('production-smoke-initialized')) {
          localStorage.setItem('app_version','1.2.1'); localStorage.setItem('access_token','synthetic-token');
          localStorage.setItem('refresh_token','synthetic-refresh'); localStorage.setItem('production-smoke-initialized','yes'); }"""
        )
        context.route_web_socket("**/*", lambda socket: None)

        def intercept(route):
            target = urlparse(route.request.url)
            path = target.path
            if path.startswith("/api/v1/") or target.netloc != urlparse(base).netloc:
                if route.request.method == "OPTIONS":
                    route.fulfill(status=204)
                    return
                if route.request.method != "GET":
                    writes.append(path)
                    route.abort()
                    return
                reads.append(path)
                if path.endswith(("/auth/me", "/users/me")):
                    data = {
                        "id": "synthetic-user",
                        "email": "manager@example.test",
                        "role": "GERENTE",
                        "is_active": True,
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "created_at": "2026-11-01T00:00:00Z",
                    }
                elif path.endswith("/riders/audit/summary"):
                    query = parse_qs(target.query)
                    data = {
                        "limit": int(query.get("limit", ["51"])[0]),
                        "offset": 0,
                        "total": 1,
                        "items": [
                            {
                                "rider_id": "rider-local",
                                "user_id": "actual-user-local",
                                "full_name": "Prueba local",
                                "email": None,
                                "status": "ACTIVO",
                                "is_online": False,
                                "orders_assigned": 0,
                                "orders_delivered": 0,
                                "orders_active": 0,
                                "deliveries_total": 0,
                                "deliveries_completed": 0,
                                "deliveries_failed": 0,
                                "deliveries_in_progress": 0,
                                "sla_compliant": 0,
                                "sla_compliance_rate": 0,
                                "total_earned": 0,
                                "pending_payouts": 0,
                                "available_to_payout": 0,
                                "last_lat": 0,
                                "last_lng": 0,
                                "last_location_at": None,
                            }
                        ],
                    }
                elif path.endswith("/riders"):
                    data = []
                else:
                    data = [] if "alerts" in path else {"items": [], "unread_count": 0}
                route.fulfill(
                    json=data,
                    headers={
                        "access-control-allow-origin": base,
                        "access-control-allow-headers": "authorization, content-type",
                    },
                )
            else:
                route.continue_()

        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/manager/fleet/riders/new", wait_until="domcontentloaded")
        expect(
            page.get_by_text("Registrar Nuevo Repartidor", exact=True)
        ).to_be_visible()
        page.get_by_label("Nombre Completo", exact=True).fill("A")
        page.get_by_label("Email", exact=True).fill("valid@example.test")
        page.get_by_label("Teléfono", exact=True).fill("12")
        page.get_by_label("CPF / Documento", exact=True).fill("123")
        page.get_by_label("Zona de Operación", exact=True).fill("Centro")
        page.get_by_label("Contraseña Temporal", exact=True).fill("a")
        page.get_by_role("button", name="Registrar Repartidor", exact=True).click()
        expect(
            page.get_by_text("El nombre completo es requerido", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("Teléfono inválido", exact=True)).to_be_visible()
        expect(
            page.get_by_text(
                "La contraseña debe tener al menos 8 caracteres", exact=True
            )
        ).to_be_visible()
        assert not writes
        checks.append("zod4_resolver_validates_form_without_business_write")
        page.screenshot(
            path=str(artifacts / "registration-validation.png"), full_page=True
        )
        page.goto(
            base + "/manager/operations/rider-audit", wait_until="domcontentloaded"
        )
        expect(
            page.get_by_role("article", name="Auditoría de rider-local")
        ).to_be_visible()
        expect(
            page.get_by_text("ID usuario: actual-user-local", exact=True)
        ).to_be_visible()
        assert "/api/v1/riders/audit/summary" in reads
        with page.expect_download() as event:
            page.get_by_role("button", name="Exportar página CSV", exact=True).click()
        path = artifacts / "production-csv.csv"
        event.value.save_as(str(path))
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
        assert (
            len(rows) == 1
            and rows[0]["id_rider"] == "rider-local"
            and rows[0]["creditos_procesado"] == "0"
            and rows[0]["moneda"] == ""
        )
        checks.append("same_origin_api_session_and_actual_csv_on_next15")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(artifacts / "production-mobile.png"), full_page=True)
        assert not writes and not errors
        checks.append("production_bundle_mobile_without_runtime_exceptions")
        result = {
            "checks_passed": checks,
            "api_reads": reads,
            "write_requests": writes,
            "page_errors": errors,
        }
        (artifacts / "browser-results.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print(json.dumps(result), flush=True)
        browser.close()


if __name__ == "__main__":
    main()

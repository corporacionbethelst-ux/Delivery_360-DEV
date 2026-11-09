"""Rider catalog and registration regression with synthetic local reads only."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-riders-browser")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    artifacts = Path(args.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    checks, requests, writes, errors = [], [], [], []
    state = {
        "rider_failure": False,
        "vehicle_failure": True,
        "empty": False,
        "bad_revision": True,
    }
    vehicle_id = "123e4567-e89b-42d3-a456-000000000800"
    rows = [
        {
            "id": "rider-1",
            "user_id": "user-1",
            "first_name": "José",
            "last_name": "Pérez",
            "email": "jose@example.test",
            "phone": "04121234567",
            "status": "ACTIVO",
            "is_online": True,
            "vehicle_ownership_type": "PROPIO",
            "vehicle_type": "MOTO",
            "vehicle_plate": "OWN-1",
        },
        {
            "id": "rider-2",
            "user_id": "user-2",
            "first_name": "Ana",
            "last_name": "Local",
            "email": "ana@example.test",
            "phone": "04127654321",
            "status": "PENDIENTE",
            "is_online": False,
            "vehicle_ownership_type": "EMPRESA",
            "assigned_vehicle_id": vehicle_id,
            "vehicle_plate": "OLD-PLATE",
            "assigned_vehicle": {
                "id": vehicle_id,
                "type": "AUTO",
                "plate": "ASSIGNED-78",
            },
        },
        {
            "id": "rider-3",
            "user_id": "user-3",
            "first_name": None,
            "last_name": None,
            "email": None,
            "phone": None,
            "status": None,
            "is_online": None,
        },
    ]

    def passed(name):
        checks.append(name)
        print("passed: " + name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium, headless=True, args=["--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="es-VE",
            service_workers="block",
        )
        context.set_default_timeout(10000)
        context.add_cookies(
            [{"name": "auth-token", "value": "synthetic-token", "url": base}]
        )
        context.add_init_script(
            """localStorage.setItem('app_version','1.2.1'); localStorage.setItem('access_token','synthetic-token'); localStorage.setItem('refresh_token','synthetic-refresh');"""
        )
        context.route_web_socket("**/*", lambda socket: None)

        def intercept(route):
            target = urlparse(route.request.url)
            path = target.path
            headers = {
                "access-control-allow-origin": base,
                "access-control-allow-headers": "authorization, content-type",
                "access-control-allow-methods": "GET, OPTIONS",
            }
            business = (
                path.startswith("/api/v1/") or target.netloc != urlparse(base).netloc
            )
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif business and route.request.method != "GET":
                writes.append({"path": path, "method": route.request.method})
                route.abort()
            elif path == "/api/v1/riders":
                requests.append(path)
                route.fulfill(
                    status=503 if state["rider_failure"] else 200,
                    json=(
                        {"detail": "Fallo sintético"}
                        if state["rider_failure"]
                        else rows
                    ),
                    headers=headers,
                )
            elif path == "/api/v1/vehicles/available":
                requests.append(path)
                vehicle = {
                    "id": vehicle_id,
                    "plate": "COMPANY-78",
                    "type": "MOTO",
                    "model": "Modelo",
                    "color": "Azul",
                    "year": 2026,
                    "status": "ACTIVO",
                    "revision": None if state["bad_revision"] else "a" * 64,
                    "created_at": "2026-01-01T00:00:00Z",
                }
                route.fulfill(
                    status=503 if state["vehicle_failure"] else 200,
                    json=(
                        {"detail": "Disponibilidad no comprobada"}
                        if state["vehicle_failure"]
                        else [] if state["empty"] else [vehicle]
                    ),
                    headers=headers,
                )
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "rider-manager",
                        "role": "GERENTE",
                        "is_active": True,
                        "email": "manager@example.test",
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
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
        page.goto(base + "/manager/fleet/riders", wait_until="domcontentloaded")
        expect(page.get_by_role("article")).to_have_count(3)
        assigned = page.get_by_role("article", name="Repartidor rider-2", exact=True)
        expect(assigned).to_contain_text("ASSIGNED-78")
        expect(assigned).not_to_contain_text("OLD-PLATE")
        unknown = page.get_by_role("article", name="Repartidor rider-3", exact=True)
        expect(unknown).to_contain_text("Estado no informado")
        expect(unknown).to_contain_text("Disponibilidad no informada")
        assert "/api/v1/vehicles/available" not in requests
        expect(
            page.get_by_role("link", name="Ver documentos de rider-1", exact=True)
        ).to_have_attribute("href", "/manager/fleet/riders/rider-1/documents")
        passed(
            "rider identities and assigned vehicle are displayed without fabricated status or availability"
        )

        count = len(requests)
        search = page.get_by_label(
            "Buscar por nombre, contacto, placa o ID", exact=True
        )
        search.fill("jose")
        expect(page.get_by_role("article")).to_have_count(1)
        search.fill("")
        page.get_by_role(
            "combobox", name="Estado registrado", exact=True
        ).select_option("PENDIENTE")
        expect(page.get_by_role("article")).to_have_count(1)
        expect(assigned).to_be_visible()
        page.get_by_role(
            "combobox", name="Estado registrado", exact=True
        ).select_option("ALL")
        assert len(requests) == count
        passed(
            "accent search and status filters stay local and do not classify unknown riders as pending"
        )

        state["rider_failure"] = True
        page.get_by_role("button", name="Actualizar", exact=True).click()
        retry = page.get_by_role("button", name="Reintentar consulta", exact=True)
        expect(retry).to_be_visible()
        expect(page.get_by_role("article")).to_have_count(3)
        state["rider_failure"] = False
        retry.click()
        expect(retry).to_have_count(0)
        page.screenshot(
            path=str(artifacts / "riders-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        passed("failed refresh preserves the confirmed catalog and supports retry")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(
            path=str(artifacts / "riders-mobile.png"), animations="disabled"
        )
        passed("rider cards and actual profile actions fit the mobile viewport")

        page.set_viewport_size({"width": 1440, "height": 1100})
        page.goto(base + "/manager/fleet/riders/new", wait_until="domcontentloaded")
        expect(page.get_by_label("Fecha de Nacimiento", exact=True)).to_have_count(0)
        for label, value in [
            ("Nombre Completo", "Monónimo"),
            ("Email", "rider@example.test"),
            ("Teléfono", "04121234567"),
            ("CPF / Documento", "123456789012345"),
            ("Zona de Operación", "Centro"),
            ("Contraseña Temporal", "1234567"),
        ]:
            page.get_by_label(label, exact=True).fill(value)
        page.get_by_role("button", name="Registrar Repartidor", exact=True).click()
        expect(
            page.get_by_text("Incluye nombre y apellido", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text(
                "La contraseña debe tener al menos 8 caracteres", exact=True
            )
        ).to_be_visible()
        expect(
            page.get_by_text("El documento debe tener hasta 14 caracteres", exact=True)
        ).to_be_visible()
        for label, value in [
            ("Nombre Completo", "José Pérez"),
            ("CPF / Documento", "123456789"),
            ("Contraseña Temporal", "DemoPass78!"),
        ]:
            page.get_by_label(label, exact=True).fill(value)
        passed(
            "registration validates real name, document storage limit and eight-character password without collecting an unsupported birth date"
        )

        page.get_by_label("Propiedad del vehículo", exact=True).click()
        page.get_by_role("option", name=re.compile("Vehículo de Empresa")).click()
        expect(
            page.get_by_role("alert").filter(
                has_text="No se pudo comprobar la disponibilidad"
            )
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Registrar Repartidor", exact=True)
        ).to_be_disabled()
        state["vehicle_failure"] = False
        state["empty"] = True
        page.get_by_role("button", name="Recargar vehículos", exact=True).click()
        expect(
            page.get_by_role("alert").filter(
                has_text="No se pudo comprobar la disponibilidad"
            )
        ).to_have_count(0)
        page.get_by_label("Vehículo de Empresa Asignado", exact=True).click()
        expect(
            page.get_by_role("option", name="No hay vehículos disponibles", exact=True)
        ).to_be_visible()
        page.keyboard.press("Escape")
        passed(
            "company vehicle lookup failure is distinct from a confirmed empty catalog"
        )

        state["empty"] = False
        page.get_by_role("button", name="Recargar vehículos", exact=True).click()
        expect(
            page.get_by_label("Vehículo de Empresa Asignado", exact=True)
        ).to_contain_text("COMPANY-78")
        page.get_by_role("button", name="Registrar Repartidor", exact=True).click()
        expect(
            page.get_by_role("alert").filter(
                has_text="Recarga los vehículos y revisa la ficha"
            )
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Registrar Repartidor", exact=True)
        ).to_be_disabled()
        state["bad_revision"] = False
        page.get_by_role("button", name="Recargar vehículos", exact=True).click()
        expect(
            page.get_by_role("button", name="Registrar Repartidor", exact=True)
        ).to_be_enabled()
        expect(
            page.get_by_label("Vehículo de Empresa Asignado", exact=True)
        ).to_contain_text("COMPANY-78")
        expect(
            page.get_by_text(
                "Recarga los vehículos y revisa la ficha antes de seleccionarlo de nuevo",
                exact=True,
            )
        ).to_have_count(0)
        page.evaluate(
            "document.querySelector('main > div.overflow-auto').scrollTo({top:0,behavior:'instant'})"
        )
        page.screenshot(
            path=str(artifacts / "registration-desktop.png"),
            full_page=True,
            animations="disabled",
        )
        passed(
            "an invalid vehicle revision blocks creation until explicit reload provides a fresh candidate"
        )

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(
            path=str(artifacts / "registration-mobile.png"), animations="disabled"
        )
        passed("registration sections and labeled vehicle selection fit mobile")
        assert writes == [], writes
        assert errors == [], errors
        passed("zero business mutations and zero JavaScript exceptions")
        (artifacts / "results.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "requests": requests,
                    "writes": writes,
                    "errors": errors,
                },
                indent=2,
            )
            + "\n"
        )
        browser.close()


if __name__ == "__main__":
    main()

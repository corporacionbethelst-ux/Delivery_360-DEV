"""User administration on a local build: synthetic reads, no business writes."""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-users")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, reads, writes, errors = [], [], [], []
    state = {"failure": False, "invalid": False, "detail": "valid", "role": "GERENTE"}
    actor_id = "123e4567-e89b-42d3-a456-000000000820"
    target_id = "123e4567-e89b-42d3-a456-000000000821"
    root_id = "123e4567-e89b-42d3-a456-000000000822"
    rows = [
        {
            "id": f"123e4567-e89b-42d3-a456-{index + 820:012}",
            "user_revision": f"{index:064x}",
            "first_name": "José" if index == 1 else f"Usuario {index}",
            "last_name": "Local",
            "email": f"user{index}@example.test",
            "phone": "+584120000000",
            "role": (
                "GERENTE"
                if index == 0
                else (
                    "SUPERADMIN"
                    if index == 2
                    else "AUDITOR" if index == 3 else "OPERADOR"
                )
            ),
            "is_active": index != 3,
            "created_at": "2026-11-09T12:00:00Z",
        }
        for index in range(54)
    ]
    rows[4].update(role="FUTURE_ROLE", is_active=None)

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
            path, query = target.path, parse_qs(target.query)
            business = (
                path.startswith("/api/v1/") or target.netloc != urlparse(base).netloc
            )
            headers = {
                "access-control-allow-origin": base,
                "access-control-allow-headers": "authorization,content-type",
                "access-control-allow-methods": "GET,OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif business and route.request.method != "GET":
                writes.append({"path": path, "method": route.request.method})
                route.abort()
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(json={**rows[0], "role": state["role"]}, headers=headers)
            elif path == "/api/v1/users":
                reads.append(query)
                filtered = [
                    row
                    for row in rows
                    if ("role" not in query or row["role"] == query["role"][0])
                    and (
                        "is_active" not in query
                        or row["is_active"] is (query["is_active"][0] == "true")
                    )
                ]
                skip, limit = int(query.get("skip", [0])[0]), int(
                    query.get("limit", [51])[0]
                )
                body = (
                    {"detail": "Synthetic read error"}
                    if state["failure"]
                    else (
                        [rows[0], rows[0]]
                        if state["invalid"]
                        else filtered[skip : skip + limit]
                    )
                )
                route.fulfill(
                    status=503 if state["failure"] else 200, json=body, headers=headers
                )
            elif path.startswith("/api/v1/users/"):
                identity = path.rsplit("/", 1)[-1]
                row = next(
                    (dict(row) for row in rows if row["id"] == identity), dict(rows[1])
                )
                if state["detail"] == "wrong-id":
                    row["id"] = "another-user"
                elif state["detail"] == "no-revision":
                    row.pop("user_revision", None)
                route.fulfill(
                    status=503 if state["detail"] == "failure" else 200,
                    json=(
                        {"detail": "Synthetic error"}
                        if state["detail"] == "failure"
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
        catalog_url = base + "/manager/admin/users"
        page.goto(catalog_url, wait_until="domcontentloaded")
        content = page.locator("main main")
        table = page.get_by_role("region", name="Tabla de usuarios", exact=True)
        expect(table.get_by_role("row")).to_have_count(51)
        assert reads[-1] == {"limit": ["51"], "skip": ["0"]}
        expect(
            page.get_by_text("El servidor no informa un total global.", exact=False)
        ).to_be_visible()
        passed(
            "catalog shows 50 records from a 51-record lookahead and labels the partial scope"
        )
        expect(table.get_by_text("Estado no informado", exact=True)).to_be_visible()
        expect(table.get_by_text("FUTURE_ROLE", exact=True)).to_be_visible()
        expect(
            table.get_by_role(
                "button", name=f"Desactivar usuario {actor_id}", exact=True
            )
        ).to_be_disabled()
        expect(
            table.get_by_role(
                "button", name=f"Desactivar usuario {root_id}", exact=True
            )
        ).to_be_disabled()
        passed(
            "unknown role/state stay explicit and own and superadministrator accounts cannot be deactivated by a manager"
        )
        search = page.get_by_role("textbox", name="Buscar en esta página", exact=True)
        count = len(reads)
        search.fill("jose")
        expect(table.get_by_role("row")).to_have_count(2)
        expect(
            table.get_by_role("link", name=f"Ver ficha de {target_id}", exact=True)
        ).to_have_attribute("href", f"/manager/admin/users/{target_id}")
        assert len(reads) == count
        search.fill("")
        page.screenshot(
            path=str(out / "users-desktop.png"), animations="disabled", full_page=True
        )
        passed(
            "accent-insensitive search stays local and profile links preserve the actual ID"
        )
        page.get_by_role("button", name="Página siguiente", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(5)
        assert reads[-1] == {"limit": ["51"], "skip": ["50"]}
        expect(
            page.get_by_role("button", name="Página siguiente", exact=True)
        ).to_be_disabled()
        page.get_by_role("button", name="Página anterior", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(51)
        passed(
            "pagination advances by 50 actual records and respects the final confirmed page"
        )
        role = page.get_by_role("combobox", name="Rol registrado", exact=True)
        status = page.get_by_role("combobox", name="Estado de cuenta", exact=True)
        role.select_option("AUDITOR")
        expect(table.get_by_role("row")).to_have_count(2)
        status.select_option("false")
        expect(page.get_by_text("Consulta confirmada:", exact=False)).to_contain_text(
            "Inactivo"
        )
        assert reads[-1] == {
            "role": ["AUDITOR"],
            "is_active": ["false"],
            "limit": ["51"],
            "skip": ["0"],
        }
        passed(
            "Auditor and inactive filters use the server contract with explicit false"
        )
        before = page.get_by_text("Consulta confirmada:", exact=False).inner_text()
        state["failure"] = True
        role.select_option("ALL")
        expect(content.get_by_role("alert")).to_contain_text("No se pudo confirmar")
        expect(page.get_by_text("Consulta confirmada:", exact=False)).to_have_text(
            before
        )
        expect(table.get_by_role("row")).to_have_count(2)
        state["failure"] = False
        page.get_by_role("button", name="Reintentar usuarios", exact=True).click()
        expect(page.get_by_text("Consulta confirmada:", exact=False)).to_contain_text(
            "rol Todos"
        )
        status.select_option("ALL")
        expect(table.get_by_role("row")).to_have_count(51)
        passed(
            "failed filters preserve the previous confirmed scope and explicit retry confirms the requested query"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        table.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "document.querySelector('[aria-label=\"Tabla de usuarios\"]').scrollLeft > 0"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(
            path=str(out / "users-mobile.png"), animations="disabled", full_page=True
        )
        passed(
            "mobile catalog stays within the viewport and its table scrolls with the keyboard"
        )
        table.get_by_role(
            "button", name=f"Desactivar usuario {target_id}", exact=True
        ).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text(target_id)
        expect(dialog).to_contain_text("user1@example.test")
        expect(
            dialog.get_by_role("button", name="Sí, desactivar", exact=True)
        ).to_be_enabled()
        assert dialog.bounding_box()["width"] <= 390
        page.screenshot(path=str(out / "deactivate-mobile.png"), animations="disabled")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        passed(
            "bounded mobile confirmation identifies the exact account and cancellation sends no mutation"
        )
        state["invalid"] = True
        page.reload(wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_contain_text("No se pudo confirmar")
        expect(table).to_have_count(0)
        expect(
            page.get_by_text("La página consultada no contiene usuarios.", exact=True)
        ).to_have_count(0)
        state["invalid"] = False
        page.get_by_role("button", name="Reintentar usuarios", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(51)
        passed(
            "duplicate initial identities fail visibly instead of presenting an invented empty catalog"
        )

        page.goto(catalog_url + "/new", wait_until="domcontentloaded")
        first = page.get_by_role("textbox", name="Nombre *", exact=True)
        last = page.get_by_role("textbox", name="Apellido *", exact=True)
        email = page.get_by_role("textbox", name="Email *", exact=True)
        phone = page.get_by_role("textbox", name="Teléfono", exact=True)
        expect(first).to_be_visible()
        email.fill("manual@example.test")
        first.fill("Ana")
        last.fill("Local")
        phone.fill("+584120000000")
        first.focus()
        last.focus()
        expect(email).to_have_value("manual@example.test")
        assigned = page.get_by_role("combobox", name="Rol asignado", exact=True)
        assert assigned.locator('option[value="SUPERADMIN"]').count() == 0
        assert assigned.locator('option[value="AUDITOR"]').count() == 1
        expect(content.locator("textarea")).to_have_count(0)
        expect(phone).to_be_visible()
        passed(
            "create preserves manual email and exposes real phone and Auditor fields without unsupported notes"
        )
        page.get_by_label("Contraseña *", exact=True).fill("short")
        page.get_by_label("Confirmar Contraseña", exact=True).fill("short")
        page.get_by_role("button", name="Crear Usuario", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text("8 y 128")
        assert not writes
        page.get_by_label("Contraseña *", exact=True).fill("")
        page.get_by_label("Confirmar Contraseña", exact=True).fill("")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(
            path=str(out / "create-user-mobile.png"),
            animations="disabled",
        )
        page.get_by_role(
            "button", name="Crear Usuario", exact=True
        ).scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "create-user-mobile-credentials.png"), animations="disabled"
        )
        page.set_viewport_size({"width": 1440, "height": 1150})
        page.screenshot(
            path=str(out / "create-user-desktop.png"),
            animations="disabled",
            full_page=True,
        )
        passed(
            "password validation prevents an invalid POST and the colored create form fits mobile and desktop"
        )
        state["detail"] = "failure"
        page.goto(catalog_url + "/" + target_id, wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_contain_text("No se pudo cargar")
        expect(first).to_have_count(0)
        state["detail"] = "wrong-id"
        page.get_by_role("button", name="Recargar usuario", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text("no corresponde")
        expect(first).to_have_count(0)
        state["detail"] = "no-revision"
        page.get_by_role("button", name="Recargar usuario", exact=True).click()
        expect(first).to_have_value("José")
        expect(
            page.get_by_role("button", name="Guardar Cambios", exact=True)
        ).to_be_disabled()
        expect(first).to_be_disabled()
        state["detail"] = "valid"
        page.get_by_role("button", name="Recargar usuario", exact=True).click()
        expect(first).to_be_enabled()
        page.get_by_role("switch", name="Cambiar contraseña", exact=True).click()
        expect(page.get_by_label("Nueva Contraseña", exact=True)).to_be_visible()
        page.screenshot(
            path=str(out / "edit-user-desktop.png"),
            animations="disabled",
            full_page=True,
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(
            path=str(out / "edit-user-mobile.png"),
            animations="disabled",
        )
        page.get_by_role(
            "button", name="Guardar Cambios", exact=True
        ).scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "edit-user-mobile-credentials.png"), animations="disabled"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        passed(
            "read errors and wrong identities show no editable defaults; missing revision disables saving and confirmed reload restores editing"
        )
        page.goto(catalog_url + "/" + root_id, wait_until="domcontentloaded")
        expect(
            page.get_by_text(
                "Solo un superadministrador puede modificar esta cuenta.", exact=True
            )
        ).to_be_visible()
        expect(first).to_be_disabled()
        expect(
            page.get_by_role("button", name="Guardar Cambios", exact=True)
        ).to_be_disabled()
        page.goto(catalog_url + "/" + actor_id, wait_until="domcontentloaded")
        expect(first).to_be_enabled()
        expect(assigned).to_be_disabled()
        expect(
            page.get_by_role("switch", name="Cuenta activa", exact=True)
        ).to_be_disabled()
        passed(
            "manager views superadministrator accounts read-only and own role and active state stay locked"
        )
        state["role"] = "SUPERADMIN"
        page.goto(catalog_url + "/new", wait_until="domcontentloaded")
        expect(first).to_be_enabled()
        expect(assigned.locator("option")).to_have_count(6)
        page.goto(catalog_url + "/" + root_id, wait_until="domcontentloaded")
        expect(first).to_be_enabled()
        expect(assigned).to_be_enabled()
        passed(
            "superadministrator has all six role choices and can edit another superadministrator"
        )
        assert not writes, writes
        assert not errors, errors
        passed("zero business mutations and zero JavaScript exceptions")
        (out / "results.json").write_text(
            json.dumps(
                {"checks": checks, "reads": reads, "writes": writes, "errors": errors},
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()


if __name__ == "__main__":
    main()

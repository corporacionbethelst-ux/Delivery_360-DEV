"""Local role review with synthetic reads and browser-generated comparison CSV."""

import argparse
import csv
import io
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-role-catalog")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, reads, writes, errors = [], [], [], []
    state = {
        "roles_failure": False,
        "permissions_failure": False,
        "invalid": False,
        "removed": False,
        "empty": False,
        "role": "GERENTE",
    }
    permissions = [
        {
            "id": "orders.read",
            "name": "Ver órdenes",
            "module": "orders",
            "description": "Consultar órdenes",
        },
        {
            "id": "users.manage",
            "name": "Gestionar usuarios",
            "module": "users",
            "description": "Administrar cuentas",
        },
        {"id": "financial.read", "name": "Ver finanzas", "module": "financial"},
        {"id": "future.read", "name": "=SUM(1,1)", "module": "__proto__"},
    ]
    roles = [
        {
            "id": identity,
            "slug": identity,
            "name": name,
            "description": (
                "Gestión operativa"
                if identity == "GERENTE"
                else "Capacidades de la cuenta"
            ),
            "permissions": grants,
            "users_count": count,
            "is_system": True,
            "created_at": None,
        }
        for identity, name, grants, count in [
            ("SUPERADMIN", "Superadministrador", [row["id"] for row in permissions], 2),
            (
                "GERENTE",
                "Gerente",
                ["orders.read", "users.manage", "unknown.feature"],
                0,
            ),
            ("OPERADOR", "Operador", ["orders.read"], 3),
            ("REPARTIDOR", "Repartidor", [], 5),
            ("CLIENTE", "Cliente", [], 4),
            ("AUDITOR", "Auditor", ["orders.read", "financial.read"], 1),
        ]
    ]

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
            accept_downloads=True,
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
                "access-control-allow-methods": "GET,OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif business and route.request.method != "GET":
                writes.append({"path": path, "method": route.request.method})
                route.abort()
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "role-manager-84",
                        "role": state["role"],
                        "first_name": "Roles",
                        "last_name": "Local",
                        "email": "manager@example.test",
                        "is_active": True,
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    headers=headers,
                )
            elif path == "/api/v1/roles":
                reads.append(path)
                rows = (
                    []
                    if state["empty"]
                    else [
                        row
                        for row in roles
                        if not state["removed"] or row["id"] != "OPERADOR"
                    ]
                )
                if state["invalid"]:
                    rows = [roles[0], roles[0]]
                route.fulfill(
                    status=503 if state["roles_failure"] else 200,
                    json=(
                        {"detail": "Synthetic role failure"}
                        if state["roles_failure"]
                        else rows
                    ),
                    headers=headers,
                )
            elif path == "/api/v1/roles/permissions":
                reads.append(path)
                route.fulfill(
                    status=503 if state["permissions_failure"] else 200,
                    json=(
                        {"detail": "Synthetic permission failure"}
                        if state["permissions_failure"]
                        else [] if state["empty"] else permissions
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
        page.goto(base + "/manager/admin/roles", wait_until="domcontentloaded")
        content = page.locator("main main")
        manager = page.get_by_role("article", name="Rol GERENTE", exact=True)
        role_cards = page.get_by_role(
            "region", name="Roles de la consulta confirmada", exact=True
        )
        sheets = page.get_by_role(
            "region", name="Catálogo de permisos confirmado", exact=True
        )
        matrix = page.get_by_role("region", name="Matriz de comparación", exact=True)
        expect(role_cards.get_by_role("article")).to_have_count(6)
        expect(manager.get_by_text("0", exact=True)).to_be_visible()
        expect(
            sheets.get_by_role("region", name="Módulo __proto__", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text(
                "La autorización se comprueba en cada operación.", exact=False
            )
        ).to_be_visible()
        expect(
            page.get_by_role("link", name="Gestionar cuentas", exact=True)
        ).to_have_attribute("href", "/manager/admin/users")
        passed(
            "six confirmed system roles preserve zero assignments and describe declared capabilities with the actual account-management link"
        )
        expect(
            page.get_by_text("Hay 1 referencia declarada", exact=False)
        ).to_be_visible()
        expect(sheets.get_by_text("=SUM(1,1)", exact=True)).to_be_visible()
        manager.locator("summary").click()
        expect(manager.get_by_text("unknown.feature", exact=True)).to_be_visible()
        expect(manager.get_by_text("Sin ficha disponible", exact=True)).to_be_visible()
        page.screenshot(
            path=str(out / "roles-desktop.png"), animations="disabled", full_page=True
        )
        passed(
            "unlisted grants keep their actual IDs, unknown module names stay literal and native role details expand without fabricated sheets"
        )
        before = len(reads)
        role_search = page.get_by_role("textbox", name="Buscar roles", exact=True)
        role_search.fill("gestion")
        expect(role_cards.get_by_role("article")).to_have_count(2)
        expect(manager).to_be_visible()
        expect(
            role_cards.get_by_role("article", name="Rol SUPERADMIN", exact=True)
        ).to_be_visible()
        assert len(reads) == before
        role_search.fill("")
        expect(role_cards.get_by_role("article")).to_have_count(6)
        passed(
            "accent-insensitive role search operates locally without another HTTP request"
        )
        page.get_by_role(
            "checkbox", name="Comparar Gerente [GERENTE]", exact=True
        ).check()
        expect(matrix).to_have_count(0)
        page.get_by_role(
            "checkbox", name="Comparar Operador [OPERADOR]", exact=True
        ).check()
        expect(matrix.get_by_role("row")).to_have_count(6)
        unknown = matrix.get_by_role("row").filter(
            has=page.get_by_text("unknown.feature", exact=True)
        )
        expect(unknown.get_by_text("Declarado", exact=True)).to_be_visible()
        expect(unknown.get_by_text("No declarado", exact=True)).to_be_visible()
        page.get_by_role(
            "checkbox", name="Comparar Auditor [AUDITOR]", exact=True
        ).check()
        expect(
            page.get_by_role("checkbox", name="Comparar Cliente [CLIENTE]", exact=True)
        ).to_be_disabled()
        page.get_by_role("button", name="Quitar rol AUDITOR", exact=True).click()
        passed(
            "comparison requires two roles, caps at three and keeps declared versus undeclared labels for unlisted IDs"
        )
        role_search.fill("Auditor")
        expect(role_cards.get_by_role("article")).to_have_count(1)
        expect(matrix).to_be_visible()
        role_search.fill("")
        mode = page.get_by_role("combobox", name="Vista de comparación", exact=True)
        mode.select_option("COMMON")
        expect(matrix.get_by_role("row")).to_have_count(2)
        expect(matrix.get_by_text("orders.read", exact=True)).to_be_visible()
        mode.select_option("DIFFERENT")
        expect(matrix.get_by_role("row")).to_have_count(3)
        expect(matrix.get_by_text("orders.read", exact=True)).to_have_count(0)
        mode.select_option("ALL")
        matrix.scroll_into_view_if_needed()
        page.screenshot(path=str(out / "comparison-desktop.png"), animations="disabled")
        passed(
            "local role filtering preserves selected columns and common/different views use the actual declared lists"
        )
        permission_search = page.get_by_role(
            "textbox", name="Buscar permisos", exact=True
        )
        module = page.get_by_role("combobox", name="Módulo de permisos", exact=True)
        permission_search.fill("ordenes")
        expect(matrix.get_by_role("row")).to_have_count(2)
        expect(sheets.get_by_role("region")).to_have_count(1)
        permission_search.fill("")
        module.select_option("missing")
        expect(matrix.get_by_role("row")).to_have_count(2)
        expect(matrix.get_by_text("unknown.feature", exact=True)).to_be_visible()
        expect(
            sheets.get_by_text(
                "No hay fichas que coincidan con los filtros locales de permisos.",
                exact=True,
            )
        ).to_be_visible()
        module.select_option("all")
        passed(
            "permission and module filters scope both the sheet catalog and matrix and keep unavailable references explicit"
        )
        export_button = page.get_by_role(
            "button", name="Descargar comparación (CSV)", exact=True
        )
        with page.expect_download() as download_info:
            export_button.click()
        download = download_info.value
        download.save_as(out / "comparison-all.csv")
        rows = list(
            csv.DictReader(
                io.StringIO(Path(download.path()).read_text(encoding="utf-8-sig"))
            )
        )
        assert len(rows) == 5
        assert (
            next(row for row in rows if row["Permiso"] == "future.read")["Nombre"]
            == "'=SUM(1,1)"
        )
        assert (
            next(row for row in rows if row["Permiso"] == "unknown.feature")[
                "Rol 2: Operador [OPERADOR]"
            ]
            == "No declarado"
        )
        assert all(
            row["Consulta roles (Caracas)"] and row["Consulta permisos (Caracas)"]
            for row in rows
        )
        assert len(reads) == before
        passed(
            "actual browser CSV contains the visible matrix, source timestamps and literal spreadsheet text with no export API call"
        )
        module.select_option("module:users")
        expect(matrix.get_by_role("row")).to_have_count(2)
        with page.expect_download() as filtered_info:
            export_button.click()
        filtered = filtered_info.value
        filtered.save_as(out / "comparison-users.csv")
        filtered_rows = list(
            csv.DictReader(
                io.StringIO(Path(filtered.path()).read_text(encoding="utf-8-sig"))
            )
        )
        assert len(filtered_rows) == 1 and filtered_rows[0]["Permiso"] == "users.manage"
        module.select_option("all")
        passed(
            "filtered CSV contains precisely the displayed permission rows and the selected role columns"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        matrix.scroll_into_view_if_needed()
        matrix.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "document.querySelector('[aria-label=\"Matriz de comparación\"]').scrollLeft > 0"
        )
        page.wait_for_function("""() => {
            const rect = document.querySelector('[aria-label="Matriz de comparación"]').getBoundingClientRect();
            return rect.top >= 60 && rect.bottom <= innerHeight + 1;
        }""")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=str(out / "comparison-mobile.png"), animations="disabled")
        for _ in range(20):
            page.keyboard.press("ArrowRight")
        page.wait_for_function("""() => {
            const table = document.querySelector('[aria-label="Matriz de comparación"]');
            return table.scrollLeft >= table.scrollWidth - table.clientWidth - 1;
        }""")
        page.screenshot(
            path=str(out / "comparison-mobile-columns.png"), animations="disabled"
        )
        manager.scroll_into_view_if_needed()
        page.screenshot(path=str(out / "role-mobile.png"), animations="disabled")
        role_search.scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "role-filters-mobile.png"), animations="disabled"
        )
        passed(
            "mobile role cards fit the viewport and the matrix scrolls by keyboard with visible local controls"
        )
        state["roles_failure"] = True
        roles_at = page.get_by_text("Roles confirmados:", exact=False).inner_text()
        page.get_by_role("button", name="Actualizar catálogo", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text(
            "No se pudieron actualizar los roles"
        )
        expect(page.get_by_text("Roles confirmados:", exact=False)).to_have_text(
            roles_at
        )
        expect(role_cards.get_by_role("article")).to_have_count(6)
        expect(export_button).to_be_disabled()
        state["roles_failure"] = False
        page.get_by_role("button", name="Reintentar roles", exact=True).click()
        expect(content.get_by_role("alert")).to_have_count(0)
        expect(export_button).to_be_enabled()
        passed(
            "failed role refresh preserves records and reading time, blocks CSV and retries only the failed source"
        )
        state["permissions_failure"] = True
        page.reload(wait_until="domcontentloaded")
        expect(role_cards.get_by_role("article")).to_have_count(6)
        expect(content.get_by_role("alert")).to_contain_text(
            "No se pudo actualizar el catálogo"
        )
        expect(sheets).to_have_count(0)
        page.get_by_role(
            "checkbox", name="Comparar Gerente [GERENTE]", exact=True
        ).check()
        page.get_by_role(
            "checkbox", name="Comparar Operador [OPERADOR]", exact=True
        ).check()
        expect(matrix.get_by_text("orders.read", exact=True)).to_be_visible()
        expect(export_button).to_be_disabled()
        page.screenshot(
            path=str(out / "permissions-error-mobile.png"), animations="disabled"
        )
        state["permissions_failure"] = False
        page.get_by_role("button", name="Reintentar permisos", exact=True).click()
        expect(sheets).to_be_visible()
        expect(export_button).to_be_enabled()
        passed(
            "initial permission failure has no fallback sheets while confirmed role declarations remain inspectable by ID"
        )
        state["removed"] = True
        page.get_by_role("button", name="Actualizar catálogo", exact=True).click()
        expect(
            page.get_by_text(
                "Ya no figuran en los roles cargados: OPERADOR.", exact=False
            )
        ).to_be_visible()
        expect(matrix).to_have_count(0)
        expect(
            page.get_by_role("button", name="Quitar rol OPERADOR", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Quitar rol OPERADOR", exact=True).click()
        state["removed"] = False
        passed(
            "a removed selected role stays identified and never silently becomes another comparison column"
        )
        state["invalid"] = True
        page.reload(wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_contain_text(
            "No se pudieron actualizar los roles"
        )
        expect(role_cards).to_have_count(0)
        expect(
            page.get_by_text("La consulta confirmada no contiene roles.", exact=True)
        ).to_have_count(0)
        state["invalid"] = False
        page.get_by_role("button", name="Reintentar roles", exact=True).click()
        expect(role_cards.get_by_role("article")).to_have_count(6)
        passed(
            "duplicate initial role identities produce a read error rather than zero accounts or an empty role catalog"
        )
        state["empty"] = True
        page.get_by_role("button", name="Actualizar catálogo", exact=True).click()
        expect(
            page.get_by_text("La consulta confirmada no contiene roles.", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text("El catálogo confirmado no contiene permisos.", exact=True)
        ).to_be_visible()
        passed(
            "confirmed empty sources are distinguished from loading and failed reads"
        )
        state["empty"] = False
        state["role"] = "SUPERADMIN"
        page.reload(wait_until="domcontentloaded")
        expect(role_cards.get_by_role("article")).to_have_count(6)
        passed("superadministrator retains the same readonly role-review flow")
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

"""Administrative audit against a local build with synthetic reads and CSV."""

import argparse
import csv
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-system-audit")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks, reads, exports, writes, errors = [], [], [], [], []
    state = {
        "failure": False,
        "invalid": False,
        "summary_failure": False,
        "detail": "valid",
        "csv_failure": False,
        "csv_invalid": False,
        "role": "GERENTE",
    }
    actor_id = "123e4567-e89b-42d3-a456-000000000830"
    rows = [
        {
            "id": f"123e4567-e89b-42d3-a456-{index + 830:012}",
            "action": "UPDATE",
            "status": "SUCCESS" if index != 1 else "FAILURE",
            "success": index != 1,
            "user_id": actor_id,
            "user_email": None if index == 0 else f"actor{index}@example.test",
            "user_role": "GERENTE",
            "resource_type": "Rider",
            "resource_id": f"rider-{index}",
            "description": (
                'José, "revisión"\nsegunda línea'
                if index == 0
                else f"Evento sintético {index}"
            ),
            "ip_address": "192.0.2.83",
            "created_at": "2026-11-09T12:00:00",
            "new_values": {
                "occurred_at_utc": "2026-11-09T13:00:00Z",
                "is_active": False,
            },
            "old_values": {"is_active": True},
            "status_code": 200,
            "request_method": "PATCH",
            "request_path": f"/api/v1/riders/rider-{index}",
            "contains_personal_data": index == 0,
        }
        for index in range(54)
    ]
    rows[2].update(
        action="FUTURE", status="__proto__", created_at="invalid", new_values=None
    )
    header = "id,created_at,status,action,user_email,user_role,resource_type,resource_id,ip_address,status_code,description"

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
                route.fulfill(
                    json={
                        "id": actor_id,
                        "role": state["role"],
                        "first_name": "Auditoría",
                        "last_name": "Local",
                        "email": "manager@example.test",
                        "is_active": True,
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    headers=headers,
                )
            elif path == "/api/v1/audit/summary":
                route.fulfill(
                    status=503 if state["summary_failure"] else 200,
                    json=(
                        {"detail": "Synthetic summary failure"}
                        if state["summary_failure"]
                        else {
                            "period_start": "2026-11-02T12:00:00",
                            "period_days": 7,
                            "total": 54,
                            "by_action": {"UPDATE": 53, "FUTURE": 1},
                            "by_success": {"True": 0, "False": 54},
                        }
                    ),
                    headers=headers,
                )
            elif path == "/api/v1/audit/export":
                exports.append(query)
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=header.split(","))
                writer.writeheader()
                writer.writerow(
                    {
                        **{name: rows[0].get(name) for name in header.split(",")},
                        "description": "'=SUM(1,1)",
                    }
                )
                route.fulfill(
                    status=503 if state["csv_failure"] else 200,
                    body=(
                        "<html>Invalid CSV</html>"
                        if state["csv_invalid"] or state["csv_failure"]
                        else buffer.getvalue()
                    ),
                    content_type="text/csv",
                    headers=headers,
                )
            elif path == "/api/v1/audit":
                reads.append(query)
                filtered = [
                    row
                    for row in rows
                    if ("action" not in query or row["action"] == query["action"][0])
                    and ("status" not in query or row["status"] == query["status"][0])
                    and (
                        "search" not in query
                        or query["search"][0].lower()
                        in json.dumps(row, ensure_ascii=False).lower()
                    )
                ]
                offset, limit = int(query.get("offset", [0])[0]), int(
                    query.get("limit", [50])[0]
                )
                body = {
                    "items": filtered[offset : offset + limit],
                    "total": len(filtered),
                    "limit": limit,
                    "offset": offset,
                }
                if state["invalid"]:
                    body["items"] = [rows[0], rows[0]]
                route.fulfill(
                    status=503 if state["failure"] else 200,
                    json=(
                        {"detail": "Synthetic read failure"}
                        if state["failure"]
                        else body
                    ),
                    headers=headers,
                )
            elif path.startswith("/api/v1/audit/"):
                identity = path.rsplit("/", 1)[-1]
                row = dict(next(row for row in rows if row["id"] == identity))
                if state["detail"] == "wrong-id":
                    row["id"] = "other-event"
                route.fulfill(
                    status=503 if state["detail"] == "failure" else 200,
                    json=(
                        {"detail": "Synthetic detail failure"}
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
        page.goto(base + "/manager/admin/audit", wait_until="domcontentloaded")
        content = page.locator("main main")
        table = page.get_by_role("region", name="Tabla de auditoría", exact=True)
        expect(table.get_by_role("row")).to_have_count(51)
        assert reads[-1] == {"limit": ["50"], "offset": ["0"]}
        global_summary = page.get_by_role(
            "region", name="Resumen global de auditoría", exact=True
        )
        expect(global_summary.get_by_text("0", exact=True)).to_be_visible()
        expect(global_summary).to_contain_text("independiente")
        passed(
            "confirmed 50-record page and independent seven-day summary preserve a real zero success count"
        )
        expect(table.get_by_text(f"Usuario {actor_id}", exact=True)).to_be_visible()
        expect(table.get_by_text("SYSTEM", exact=True)).to_have_count(0)
        expect(table.get_by_text("__proto__", exact=True)).to_be_visible()
        expect(table.get_by_text("Fecha no disponible", exact=True)).to_be_visible()
        expect(
            table.get_by_text("9/11/2026, 9:00:00 a. m.", exact=True).first
        ).to_be_visible()
        passed(
            "identified human actors, unknown statuses and missing dates remain explicit and explicit event UTC renders in Caracas"
        )
        page.screenshot(
            path=str(out / "audit-desktop.png"), animations="disabled", full_page=True
        )
        search = page.get_by_role("textbox", name="Buscar en la auditoría", exact=True)
        search.fill("José")
        expect(
            page.get_by_text("Hay cambios sin aplicar.", exact=False)
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Exportar CSV", exact=True)
        ).to_be_disabled()
        assert len(reads) == 1
        page.get_by_role("button", name="Aplicar filtros", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(2)
        assert reads[-1]["search"] == ["José"]
        passed(
            "draft search makes no request until explicit apply and disables exports of unapplied filters"
        )
        search.fill("")
        page.get_by_label("Desde (Caracas)", exact=True).fill("2026-11-09")
        page.get_by_label("Hasta (Caracas)", exact=True).fill("2026-11-09")
        page.get_by_role("button", name="Aplicar filtros", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(51)
        assert reads[-1]["date_from"] == ["2026-11-09T04:00:00.000Z"]
        assert reads[-1]["date_to"] == ["2026-11-10T03:59:59.999999Z"]
        passed("calendar filters cover the complete Caracas day using exact UTC bounds")
        page.get_by_label("Desde (Caracas)", exact=True).fill("2026-11-10")
        count = len(reads)
        page.get_by_role("button", name="Aplicar filtros", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text("posterior")
        assert len(reads) == count
        page.get_by_role("button", name="Limpiar filtros", exact=True).click()
        expect(content.get_by_role("alert")).to_have_count(0)
        passed(
            "inverted date range is rejected locally and clearing restores the default query"
        )
        result_filter = page.get_by_role(
            "combobox", name="Resultado del evento", exact=True
        )
        result_filter.select_option("FAILURE")
        page.get_by_role("button", name="Aplicar filtros", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(2)
        assert reads[-1]["status"] == ["FAILURE"]
        expect(table.get_by_text("Fallo", exact=True)).to_be_visible()
        page.get_by_role("button", name="Limpiar filtros", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(51)
        passed(
            "result filters query the server and their labels match the displayed result"
        )
        page.get_by_role("button", name="Página siguiente", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(5)
        assert reads[-1] == {"limit": ["50"], "offset": ["50"]}
        expect(
            page.get_by_role("button", name="Página siguiente", exact=True)
        ).to_be_disabled()
        page.get_by_role("button", name="Exportar CSV", exact=True).click()
        export_dialog = page.get_by_role(
            "dialog", name="Exportar auditoría", exact=True
        )
        expect(export_dialog).to_contain_text("otras páginas")
        expect(export_dialog).to_contain_text("5000")
        export_dialog.get_by_role("button", name="Cancelar", exact=True).click()
        assert not exports
        passed(
            "real total controls pagination and CSV confirmation explains cross-page scope without silently downloading"
        )
        before = page.get_by_text("Consulta confirmada:", exact=False).inner_text()
        state["failure"] = True
        page.get_by_role("button", name="Actualizar auditoría", exact=True).click()
        expect(content.get_by_role("alert")).to_contain_text("No se pudo confirmar")
        expect(table.get_by_role("row")).to_have_count(5)
        expect(page.get_by_text("Consulta confirmada:", exact=False)).to_have_text(
            before
        )
        state["failure"] = False
        page.get_by_role("button", name="Reintentar eventos", exact=True).click()
        expect(content.get_by_role("alert")).to_have_count(0)
        assert reads[-1]["offset"] == ["50"]
        passed(
            "failed page refresh retains the prior records and query timestamp and retries the exact offset"
        )
        state["summary_failure"] = True
        page.get_by_role("button", name="Actualizar auditoría", exact=True).click()
        expect(global_summary.get_by_role("alert")).to_contain_text("resumen global")
        expect(table.get_by_role("row")).to_have_count(5)
        state["summary_failure"] = False
        global_summary.get_by_role(
            "button", name="Reintentar resumen", exact=True
        ).click()
        expect(global_summary.get_by_role("alert")).to_have_count(0)
        page.get_by_role("button", name="Página anterior", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(51)
        passed(
            "summary failures and retries are independent of the confirmed event page"
        )
        state["detail"] = "wrong-id"
        table.get_by_role(
            "button", name=f"Ver detalle del evento {rows[0]['id']}", exact=True
        ).click()
        detail = page.get_by_role("dialog", name="Detalle del evento", exact=True)
        expect(detail.get_by_role("alert")).to_contain_text("No se pudo confirmar")
        expect(
            detail.get_by_role("heading", name="Evento y actor", exact=True)
        ).to_have_count(0)
        state["detail"] = "valid"
        detail.get_by_role("button", name="Reintentar detalle", exact=True).click()
        expect(detail.get_by_label("Valores anteriores", exact=True)).to_contain_text(
            '"is_active": true'
        )
        expect(detail.get_by_label("Valores nuevos", exact=True)).to_contain_text(
            '"is_active": false'
        )
        expect(detail).to_contain_text("datos personales")
        page.screenshot(
            path=str(out / "event-detail-desktop.png"), animations="disabled"
        )
        passed(
            "wrong detail identity is rejected and an exact retry reveals source and original before/after values"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        assert detail.bounding_box()["width"] <= 390
        page.screenshot(
            path=str(out / "event-detail-mobile.png"), animations="disabled"
        )
        detail.get_by_role("button", name="Cerrar detalle", exact=True).click()
        table.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "document.querySelector('[aria-label=\"Tabla de auditoría\"]').scrollLeft > 0"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=str(out / "audit-mobile-table.png"), animations="disabled")
        search.scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "audit-mobile-filters.png"), animations="disabled"
        )
        passed(
            "mobile detail is bounded and the catalog table scrolls by keyboard without document overflow"
        )
        page.get_by_role("button", name="Exportar CSV", exact=True).click()
        state["csv_invalid"] = True
        export_dialog.get_by_role("button", name="Descargar CSV", exact=True).click()
        expect(export_dialog.get_by_role("alert")).to_contain_text(
            "No se pudo descargar"
        )
        state["csv_invalid"] = False
        page.screenshot(path=str(out / "export-mobile.png"), animations="disabled")
        with page.expect_download() as download_info:
            export_dialog.get_by_role(
                "button", name="Descargar CSV", exact=True
            ).click()
        download = download_info.value
        download.save_as(out / download.suggested_filename)
        downloaded = list(
            csv.DictReader(io.StringIO(Path(download.path()).read_text()))
        )
        assert downloaded[0]["description"] == "'=SUM(1,1)"
        assert exports[-1] == {"limit": ["5000"]}
        expect(
            page.get_by_text("Se inició la descarga del CSV", exact=False)
        ).to_be_visible()
        passed(
            "malformed CSV is rejected and explicit retry downloads the actual synthetic server CSV without an offset"
        )
        state["invalid"] = True
        page.reload(wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_contain_text("No se pudo confirmar")
        expect(table).to_have_count(0)
        expect(
            page.get_by_text(
                "No se encontraron eventos en la consulta confirmada.", exact=True
            )
        ).to_have_count(0)
        state["invalid"] = False
        page.get_by_role("button", name="Reintentar eventos", exact=True).click()
        expect(table.get_by_role("row")).to_have_count(51)
        passed(
            "invalid initial identities are a visible read failure rather than a fabricated empty audit"
        )
        state["role"] = "SUPERADMIN"
        page.reload(wait_until="domcontentloaded")
        expect(table.get_by_role("row")).to_have_count(51)
        passed("superadministrator retains the same administrative read access")
        assert not writes, writes
        assert not errors, errors
        passed("zero business mutations and zero JavaScript exceptions")
        (out / "results.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "reads": reads,
                    "exports": exports,
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

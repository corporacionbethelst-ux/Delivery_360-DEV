"""Profile and document UI against local synthetic reads; block business writes."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", default="/tmp/delivery360-profile-documents")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    rider_id = "123e4567-e89b-42d3-a456-000000000790"
    doc_id = "123e4567-e89b-42d3-a456-000000000791"
    second_doc = "123e4567-e89b-42d3-a456-000000000792"
    revision = "a" * 64
    profile_url = f"{base}/manager/fleet/riders/{rider_id}"
    state = {
        "role": "GERENTE",
        "profile_fail": False,
        "wrong_profile": False,
        "documents_fail": False,
    }
    checks, reads, writes, errors, downloads = [], [], [], [], []

    def passed(value):
        checks.append(value)
        print("passed:", value, flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1150},
            reduced_motion="reduce",
            locale="es-VE",
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
                "access-control-allow-headers": "authorization,content-type,if-match",
                "access-control-allow-methods": "GET,OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif business and route.request.method != "GET":
                writes.append({"path": path, "method": route.request.method})
                route.abort()
            elif path == f"/api/v1/riders/{rider_id}":
                reads.append(path)
                row = {
                    "id": "other-rider" if state["wrong_profile"] else rider_id,
                    "first_name": "José",
                    "last_name": "Pérez",
                    "email": "rider@example.test",
                    "phone": "04121234567",
                    "status": "PENDIENTE",
                    "is_online": False,
                    "created_at": None,
                    "last_lat": 0,
                    "last_lng": 0,
                    "last_location_at": None,
                    "vehicle_ownership_type": "EMPRESA",
                    "assigned_vehicle_id": "v-79",
                    "vehicle_plate": "OLD-PLATE",
                    "assigned_vehicle": {
                        "id": "v-79",
                        "type": "MOTO",
                        "plate": "ASSIGNED-79",
                        "model": "Modelo",
                        "color": "Azul",
                        "year": 2026,
                    },
                }
                route.fulfill(
                    status=503 if state["profile_fail"] else 200,
                    json=(
                        {"detail": "Fallo sintético del perfil"}
                        if state["profile_fail"]
                        else row
                    ),
                    headers=headers,
                )
            elif path == f"/api/v1/riders/{rider_id}/documents":
                reads.append(path)
                rows = [
                    {
                        "id": doc_id,
                        "rider_id": rider_id,
                        "type": "LICENCIA",
                        "status": "PENDIENTE",
                        "revision": revision,
                        "created_at": "2026-11-08T12:00:00",
                        "updated_at": None,
                        "file_url": f"/api/v1/riders/documents/{doc_id}/download",
                    },
                    {
                        "id": second_doc,
                        "rider_id": rider_id,
                        "type": "SEGURO",
                        "status": None,
                        "revision": None,
                        "created_at": "invalid",
                        "updated_at": None,
                        "file_url": "#",
                    },
                ]
                route.fulfill(
                    status=503 if state["documents_fail"] else 200,
                    json=(
                        {"detail": "Fallo sintético documental"}
                        if state["documents_fail"]
                        else rows
                    ),
                    headers=headers,
                )
            elif path == f"/api/v1/riders/documents/{doc_id}/download":
                downloads.append(
                    {
                        "path": path,
                        "if_match": route.request.headers.get("if-match"),
                        "authenticated": route.request.headers.get("authorization")
                        == "Bearer synthetic-token",
                    }
                )
                route.fulfill(
                    status=200,
                    content_type="application/pdf",
                    body=b"%PDF-1.4\n% synthetic Delivery360 test\n%%EOF",
                    headers={**headers, "cache-control": "private, no-store"},
                )
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "manager-79",
                        "role": state["role"],
                        "is_active": True,
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "email": "manager@example.test",
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
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.goto(profile_url, wait_until="domcontentloaded")
        content = page.locator("main main")
        identity = page.get_by_role("region", name="Identidad del repartidor")
        expect(identity.get_by_text("José Pérez", exact=True)).to_be_visible()
        expect(identity.get_by_text("Desconectado", exact=True)).to_be_visible()
        expect(page.get_by_text("ASSIGNED-79", exact=True)).to_be_visible()
        expect(page.get_by_text("OLD-PLATE", exact=True)).to_have_count(0)
        expect(page.get_by_text("Nivel no informado", exact=True)).to_be_visible()
        expect(page.get_by_text("Entregas: No informado", exact=True)).to_be_visible()
        expect(
            page.get_by_text("Registro: Fecha no informada", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("0.000000, 0.000000", exact=True)).to_be_visible()
        expect(
            page.get_by_text("Reportada: Fecha no informada", exact=True)
        ).to_be_visible()
        passed(
            "profile preserves unknown metrics, dates and tier, actual assigned vehicle and zero coordinates while offline"
        )
        page.screenshot(
            path=str(out / "profile-desktop.png"), animations="disabled", full_page=True
        )

        state["profile_fail"] = True
        page.get_by_role("button", name="Actualizar perfil", exact=True).click()
        expect(content.get_by_role("alert")).to_be_visible()
        expect(identity.get_by_text("José Pérez", exact=True)).to_be_visible()
        expect(
            page.get_by_role("button", name="Aprobar Repartidor", exact=True)
        ).to_be_disabled()
        state["profile_fail"] = False
        page.get_by_role("button", name="Reintentar perfil", exact=True).click()
        expect(content.get_by_role("alert")).to_have_count(0)
        passed(
            "profile read failure retains confirmed data and explicit retry restores actions"
        )

        page.get_by_role("button", name="Aprobar Repartidor", exact=True).click()
        confirmation = page.get_by_role("dialog")
        expect(confirmation).to_contain_text(rider_id)
        expect(confirmation).to_contain_text("no lo conecta automáticamente")
        confirmation.get_by_role("button", name="Cancelar", exact=True).click()
        passed(
            "activation confirmation identifies the rider without claiming automatic availability and cancels without a write"
        )

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(out / "profile-mobile.png"), animations="disabled")
        page.get_by_role(
            "region", name="Última ubicación reportada"
        ).scroll_into_view_if_needed()
        page.screenshot(
            path=str(out / "profile-location-mobile.png"), animations="disabled"
        )
        passed("mobile profile cards and last-location presentation fit the viewport")

        state["wrong_profile"] = True
        page.reload(wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_contain_text("no corresponde")
        expect(
            page.get_by_role("region", name="Identidad del repartidor")
        ).to_have_count(0)
        state["wrong_profile"] = False
        page.get_by_role("button", name="Reintentar perfil", exact=True).click()
        expect(identity).to_be_visible()
        passed(
            "profile response for another identity is rejected before exposing actions"
        )

        page.get_by_role("link", name="Gestionar Documentos", exact=True).click()
        first = page.get_by_role("article", name=f"Documento {doc_id}", exact=True)
        second = page.get_by_role("article", name=f"Documento {second_doc}", exact=True)
        expect(first).to_be_visible()
        expect(second.get_by_text("Estado no informado", exact=True)).to_be_visible()
        expect(second.get_by_role("button", name="Aprobar", exact=True)).to_have_count(
            0
        )
        expect(
            second.get_by_text("Subido: Fecha no informada", exact=True)
        ).to_be_visible()
        expect(
            second.get_by_role("button", name="Descargar documento", exact=True)
        ).to_have_count(0)
        passed(
            "actual document navigation preserves unknown status and requires a revision for content"
        )

        page.set_viewport_size({"width": 1440, "height": 1150})
        with page.expect_download() as download:
            first.get_by_role("button", name="Descargar documento", exact=True).click()
        download.value.save_as(str(out / "synthetic-document.pdf"))
        assert downloads == [
            {
                "path": f"/api/v1/riders/documents/{doc_id}/download",
                "if_match": '"' + revision + '"',
                "authenticated": True,
            }
        ]
        assert (out / "synthetic-document.pdf").read_bytes().startswith(b"%PDF-")
        passed(
            "document download uses the authenticated endpoint and the displayed If-Match revision"
        )
        page.screenshot(
            path=str(out / "documents-desktop.png"),
            animations="disabled",
            full_page=True,
        )

        state["documents_fail"] = True
        page.get_by_role("button", name="Actualizar", exact=True).click()
        expect(content.get_by_role("alert")).to_be_visible()
        expect(first).to_be_visible()
        expect(first.get_by_role("button", name="Aprobar", exact=True)).to_be_disabled()
        state["documents_fail"] = False
        page.get_by_role("button", name="Reintentar documentos", exact=True).click()
        expect(content.get_by_role("alert")).to_have_count(0)
        passed(
            "document refresh failure retains the catalog and blocks mutations until a confirmed retry"
        )

        first.get_by_role("button", name="Aprobar", exact=True).click()
        assert not writes
        passed(
            "approval native confirmation can be cancelled without submitting business data"
        )
        first.get_by_role("button", name="Rechazar", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text(doc_id)
        expect(dialog).to_contain_text(rider_id)
        expect(
            dialog.get_by_label("Motivo del rechazo *", exact=True)
        ).to_have_attribute("maxlength", "2000")
        dialog.get_by_label("Motivo del rechazo *", exact=True).fill("   ")
        expect(
            dialog.get_by_role("button", name="Confirmar", exact=True)
        ).to_be_disabled()
        page.set_viewport_size({"width": 390, "height": 844})
        assert dialog.evaluate("e => e.getBoundingClientRect().width <= innerWidth")
        page.screenshot(path=str(out / "rejection-mobile.png"), animations="disabled")
        dialog.get_by_role("button", name="Cancelar", exact=True).click()
        passed(
            "rejection identifies both records, rejects blank reasons and keeps the mobile dialog bounded"
        )

        page.get_by_role("button", name="Subir Documento", exact=True).click()
        dialog = page.get_by_role("dialog")
        selector = dialog.get_by_label("Tipo de Documento", exact=True)
        assert selector.locator("option").count() == 5
        selector.select_option("LICENCIA")
        file_input = dialog.get_by_label("Archivo (PDF, JPG, PNG)", exact=True)
        file_input.set_input_files(
            {
                "name": "document.exe",
                "mimeType": "application/octet-stream",
                "buffer": b"synthetic",
            }
        )
        expect(dialog.get_by_role("alert")).to_contain_text("Solo se admiten")
        expect(dialog.get_by_role("button", name="Subir", exact=True)).to_be_disabled()
        passed(
            "upload lists only supported document types and rejects invalid files locally"
        )
        file_input.set_input_files(
            {
                "name": "document.pdf",
                "mimeType": "application/pdf",
                "buffer": b"synthetic",
            }
        )
        expect(dialog.get_by_role("button", name="Subir", exact=True)).to_be_enabled()
        expect(dialog.get_by_role("alert")).to_have_count(0)
        page.screenshot(path=str(out / "upload-mobile.png"), animations="disabled")
        dialog.get_by_role("button", name="Cancelar", exact=True).click()
        passed(
            "valid file selection restores upload controls and cancellation sends no file"
        )
        page.screenshot(path=str(out / "documents-mobile.png"), animations="disabled")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        passed(
            "document cards and visible review actions fit mobile without horizontal overflow"
        )

        state["documents_fail"] = True
        page.reload(wait_until="domcontentloaded")
        expect(content.get_by_role("alert")).to_be_visible()
        expect(
            page.get_by_text("Sin documentos registrados", exact=True)
        ).to_have_count(0)
        expect(page.get_by_role("article")).to_have_count(0)
        state["documents_fail"] = False
        page.get_by_role("button", name="Reintentar documentos", exact=True).click()
        expect(first).to_be_visible()
        passed("initial document read failure is distinct from an empty confirmed list")

        state["role"] = "OPERADOR"
        page.reload(wait_until="domcontentloaded")
        expect(first).to_be_visible()
        expect(
            page.get_by_role("button", name="Subir Documento", exact=True)
        ).to_have_count(0)
        expect(first.get_by_role("button", name="Aprobar", exact=True)).to_have_count(0)
        expect(
            first.get_by_role("button", name=f"Eliminar documento {doc_id}", exact=True)
        ).to_have_count(0)
        page.get_by_role("link", name="Volver al perfil", exact=True).click()
        expect(identity).to_be_visible()
        expect(
            page.get_by_role("button", name="Aprobar Repartidor", exact=True)
        ).to_have_count(0)
        passed("operator reads both screens without manager mutation controls")
        assert not writes, writes
        assert not errors, errors
        passed("zero business mutations and zero JavaScript exceptions")
        (out / "results.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "reads": reads,
                    "downloads": downloads,
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

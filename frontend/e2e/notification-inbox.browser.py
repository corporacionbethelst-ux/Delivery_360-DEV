"""Private inbox recovery and responsive controls with synthetic API only."""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3072")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Only a loopback preview is allowed")
    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    notice_id = "123e4567-e89b-42d3-a456-000000000801"
    title = "Comprobante de operación"
    rows = [
        dict(id=notice_id, title=title, body="Aviso personal de prueba. " + "X" * 160,
             channel="IN_APP", status="PENDIENTE", template_code=None,
             created_at="2026-11-27T12:00:00+00:00", read_at=None),
        dict(id="123e4567-e89b-42d3-a456-000000000802", title="Historial externo conservado",
             body="La aceptación externa se revisa por separado.", channel="SMS", status="PENDIENTE",
             template_code="payout_aprobado", created_at="2026-11-27T12:00:00+00:00", read_at=None),
    ]
    state = {"failure": False}
    mutations, errors, unrelated, checks = [], [], [], []

    def passed(message):
        checks.append(message)
        print("passed:", message, flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, timezone_id="America/Caracas", service_workers="block")
        context.add_cookies([{"name": "auth-token", "value": "synthetic-token", "url": base}])
        context.add_init_script("localStorage.setItem('app_version','1.2.1');localStorage.setItem('access_token','synthetic-token');localStorage.setItem('refresh_token','synthetic-refresh');")
        context.route_web_socket("**/*", lambda socket: None)

        def intercept(route):
            request = route.request
            target = urlparse(request.url)
            path = target.path
            headers = {"access-control-allow-origin": base, "access-control-allow-headers": "authorization,content-type", "access-control-allow-methods": "GET,PATCH,DELETE,OPTIONS"}
            if request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(json={"id": "staff-inbox-130", "role": "GERENTE", "email": "synthetic@example.test", "first_name": "Ana", "last_name": "Prueba", "is_active": True}, headers=headers)
            elif path == "/api/v1/notifications/inbox":
                if state["failure"]:
                    route.fulfill(status=503, json={"detail": "PRIVATE_INTERNAL_VALUE"}, headers=headers)
                    return
                visible = rows if parse_qs(target.query).get("include_all_channels") == ["true"] else [r for r in rows if r["channel"] == "IN_APP"]
                route.fulfill(json={"items": visible, "page": 1, "size": 10, "total": len(visible), "pages": 1 if visible else 0, "unread_count": sum(r["channel"] == "IN_APP" and r["status"] != "LEIDO" for r in rows)}, headers=headers)
            elif path == "/api/v1/notifications/" + notice_id + "/read" and request.method == "PATCH":
                mutations.append("read")
                rows[0].update(status="LEIDO", read_at="2026-11-27T12:01:00+00:00")
                route.fulfill(json={"status": "ok", "id": notice_id}, headers=headers)
            elif path == "/api/v1/notifications/" + notice_id and request.method == "DELETE":
                mutations.append("delete")
                rows[:] = [r for r in rows if r["id"] != notice_id]
                # Simulate a committed operation whose acknowledgement was lost.
                route.fulfill(status=503, json={"detail": "PRIVATE_INTERNAL_VALUE"}, headers=headers)
            elif request.method not in ("GET", "OPTIONS"):
                unrelated.append({"method": request.method, "path": path})
                route.abort()
            elif path == "/api/v1/notifications/unread-count":
                route.fulfill(json={"unread_count": 1}, headers=headers)
            elif path == "/api/v1/notifications/terminal-dispatch/review":
                route.fulfill(json={"items": [], "next_offset": None}, headers=headers)
            elif path.startswith("/api/") or target.netloc != urlparse(base).netloc:
                route.fulfill(json={}, headers=headers)
            else:
                route.continue_()

        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/notifications", wait_until="domcontentloaded")
        own = page.get_by_role("article", name=title, exact=True)
        expect(own).to_be_visible()
        protected = page.get_by_role("article", name="Historial externo conservado", exact=True)
        expect(protected.get_by_role("button")).to_have_count(0)
        passed("private page loads canonical DTOs and preserves protected external history")
        page.screenshot(path=str(args.artifacts_dir / "inbox-desktop.png"), full_page=True, animations="disabled")

        for width in (390, 320):
            page.set_viewport_size({"width": width, "height": 844})
            page.wait_for_function("document.querySelector('aside').getBoundingClientRect().right <= 1")
            for button in [page.get_by_role("button", name="Actualizar bandeja"), own.get_by_role("button", name="Marcar leído: " + title), own.get_by_role("button", name="Eliminar: " + title)]:
                button.scroll_into_view_if_needed()
                geometry = button.evaluate("e => {const r=e.getBoundingClientRect();const t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {ok:r.width>0&&r.x>=0&&r.right<=innerWidth+1&&(e===t||e.contains(t)),label:e.textContent,rect:{x:r.x,y:r.y,width:r.width,right:r.right,height:r.height},viewport:innerWidth,top:t?.outerHTML.slice(0,300)};}")
                if not geometry["ok"]:
                    page.screenshot(path=str(args.artifacts_dir / "inbox-obstruction.png"), full_page=True, animations="disabled")
                    raise AssertionError(json.dumps(geometry))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            if width == 390:
                page.screenshot(path=str(args.artifacts_dir / "inbox-mobile.png"), full_page=True, animations="disabled")
        passed("refresh, read and delete controls are unobstructed at 320/390px without horizontal overflow")

        own.get_by_role("button", name="Marcar leído: " + title).click()
        expect(own.get_by_text("LEIDO", exact=True)).to_be_visible()
        expect(own.get_by_role("button", name="Marcar leído: " + title)).to_have_count(0)
        toast = page.get_by_text("Notificación marcada como leída", exact=True)
        expect(toast).to_be_visible()
        assert page.locator("[data-sonner-toaster]").get_attribute("data-x-position") == "right"
        assert page.locator("[data-sonner-toaster]").get_attribute("data-y-position") == "bottom"
        passed("read updates only after acknowledgement and success uses the bottom-right toast")

        state["failure"] = True
        page.get_by_role("button", name="Actualizar bandeja").click()
        modal = page.get_by_role("dialog", name="No se pudo cargar la bandeja", exact=True)
        expect(modal).to_be_visible()
        rect = modal.bounding_box()
        assert rect and abs(rect["x"] + rect["width"] / 2 - 160) <= 2
        expect(page.get_by_text("PRIVATE_INTERNAL_VALUE", exact=True)).to_have_count(0)
        page.screenshot(path=str(args.artifacts_dir / "inbox-error-modal.png"), full_page=True, animations="disabled")
        modal.get_by_role("button", name="Volver", exact=True).click()
        expect(own).to_be_visible()
        expect(own.get_by_role("button", name="Eliminar: " + title)).to_be_disabled()
        state["failure"] = False
        page.get_by_role("button", name="Actualizar bandeja").click()
        expect(own.get_by_role("button", name="Eliminar: " + title)).to_be_enabled()
        passed("failed refresh preserves the last read and uses a centered safe modal with GET recovery")

        own.get_by_role("button", name="Eliminar: " + title).click()
        modal = page.get_by_role("dialog", name="Eliminar notificación", exact=True)
        expect(modal).to_be_visible()
        assert mutations == ["read"]
        modal.get_by_role("button", name="Confirmar eliminación").click()
        modal = page.get_by_role("dialog", name="No se pudo confirmar la acción", exact=True)
        expect(modal).to_be_visible()
        assert page.locator("article").filter(has_text=title).count() == 1
        modal.get_by_role("button", name="Consultar de nuevo").click()
        expect(own).to_have_count(0)
        expect(protected).to_be_visible()
        assert mutations == ["read", "delete"] and not unrelated and not errors
        passed("delete requires confirmation and a lost acknowledgement recovers by GET without repeating the write")
        (args.artifacts_dir / "results.json").write_text(json.dumps({"synthetic_api": True, "real_business_writes": False, "checks": checks, "allowed_mutations": mutations, "unrelated_requests": unrelated, "page_errors": errors}, indent=2))
        context.close()
        browser.close()


if __name__ == "__main__":
    main()

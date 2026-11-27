"""Real personal inbox actions on two disposable notices in the marked lab."""

import argparse
import json
from pathlib import Path
import re
import sys
import time
from uuid import UUID, uuid4
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from scripts.recovery import Recovery, FINANCIAL_TABLES
from scripts.local_read_benchmark import verify_target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    parser.add_argument("--wait-request-window", action="store_true")
    args = parser.parse_args()
    tool = Recovery()
    verify_target(tool)
    if args.wait_request_window:
        for _ in range(61):
            time.sleep(1)
    own = str(UUID(tool.source_sql("SELECT id FROM users WHERE email='admin.local-test@example.com' AND role='SUPERADMIN'")))
    other = str(UUID(tool.source_sql("SELECT id FROM users WHERE email='gerente.local-test@example.com' AND role='GERENTE'")))
    own_id, other_id = str(uuid4()), str(uuid4())
    run = uuid4().hex[:12]
    title, foreign_title = "Aviso propio130 " + run, "Aviso ajeno130 " + run
    body = "Fixture interna de bandeja130 " + run
    tables = FINANCIAL_TABLES | {"notification_logs"}
    before = {k: v for k, v in tool.source_tables().items() if k in tables}
    assert "notification_logs" in before
    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    account = json.loads(local_test.ACCOUNTS.read_text())["SUPERADMIN"]
    base = "http://localhost:" + str(tool.source["web_port"])
    mutations, rejected, errors, checks = [], [], [], []
    seeded = False

    def passed(message):
        checks.append(message)
        print("passed:", message, flush=True)

    try:
        tool.source_sql("INSERT INTO notification_logs (id,user_id,channel,status,retry_count,title,body,created_at) VALUES "
                        f"('{own_id}'::uuid,'{own}'::uuid,'IN_APP','PENDIENTE',0,'{title}','{body}',NOW() AT TIME ZONE 'UTC'),"
                        f"('{other_id}'::uuid,'{other}'::uuid,'IN_APP','PENDIENTE',0,'{foreign_title}','{body}',NOW() AT TIME ZONE 'UTC')")
        seeded = True
        foreign_before = tool.source_sql(f"SELECT row_to_json(n)::text FROM notification_logs n WHERE id='{other_id}'::uuid")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(viewport={"width": 1440, "height": 1100}, timezone_id="America/Caracas", service_workers="block")
            def guard(route):
                request = route.request
                path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
                if request.method not in ("GET", "OPTIONS"):
                    allowed = (request.method == "POST" and path in ("/auth/login", "/auth/refresh")) or (request.method == "PATCH" and path == "/notifications/" + own_id + "/read") or (request.method == "DELETE" and path == "/notifications/" + own_id)
                    if not allowed:
                        rejected.append({"method": request.method, "path": path})
                        route.abort()
                        return
                    if request.method in ("PATCH", "DELETE"):
                        mutations.append(request.method)
                route.continue_()
            context.route("**/api/v1/**", guard)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append("browser_exception"))
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.locator("input[type=email]").fill(account["email"])
            page.locator("input[type=password]").fill(account["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(base + "/manager", timeout=30000)
            page.goto(base + "/notifications", wait_until="domcontentloaded")
            notice = page.get_by_role("article", name=title, exact=True)
            expect(notice).to_be_visible()
            expect(page.get_by_role("article", name=foreign_title, exact=True)).to_have_count(0)
            passed("real authenticated inbox shows the owner's synthetic notice and excludes another account's notice")
            notice.get_by_role("button", name="Marcar leído: " + title).click()
            expect(notice.get_by_text("LEIDO", exact=True)).to_be_visible()
            assert tool.source_sql(f"SELECT status::text||':'||(read_at IS NOT NULL)::text FROM notification_logs WHERE id='{own_id}'::uuid") == "LEIDO:true"
            passed("one confirmed read persists LEIDO and its real timestamp without an optimistic date")
            page.screenshot(path=str(args.artifacts_dir / "real-inbox-desktop.png"), full_page=True, animations="disabled")
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function("document.querySelector('aside').getBoundingClientRect().right <= 1")
            delete = notice.get_by_role("button", name="Eliminar: " + title)
            delete.scroll_into_view_if_needed()
            assert delete.evaluate("e=>{const r=e.getBoundingClientRect();const t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.width>0&&r.x>=0&&r.right<=innerWidth+1&&(t===e||e.contains(t));}")
            delete.click()
            modal = page.get_by_role("dialog", name="Eliminar notificación", exact=True)
            expect(modal).to_be_visible()
            assert tool.source_sql(f"SELECT count(*) FROM notification_logs WHERE id='{own_id}'::uuid") == "1"
            page.screenshot(path=str(args.artifacts_dir / "real-inbox-delete-mobile.png"), full_page=True, animations="disabled")
            modal.get_by_role("button", name="Confirmar eliminación").click()
            expect(notice).to_have_count(0)
            assert tool.source_sql(f"SELECT count(*) FROM notification_logs WHERE id='{own_id}'::uuid") == "0"
            assert tool.source_sql(f"SELECT row_to_json(n)::text FROM notification_logs n WHERE id='{other_id}'::uuid") == foreign_before
            assert mutations == ["PATCH", "DELETE"] and not rejected and not errors
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            passed("mobile confirmation performs exactly one delete; foreign history remains identical")
            context.close()
            browser.close()
    finally:
        if seeded:
            tool.source_sql(f"DELETE FROM notification_logs WHERE id IN ('{own_id}'::uuid,'{other_id}'::uuid) AND template_code IS NULL AND body='{body}'")
        after = {k: v for k, v in tool.source_tables().items() if k in tables}
        assert before == after, "Original protected data or notification history changed"
    passed("synthetic rows removed; all original protected tables and original notification history are identical")
    (args.artifacts_dir / "results.json").write_text(json.dumps({"real_api": True, "checks": checks, "allowed_mutations": mutations, "rejected_mutations": rejected, "page_errors": errors, "original_data_unchanged": True}, indent=2))


if __name__ == "__main__":
    main()

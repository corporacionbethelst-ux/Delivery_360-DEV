"""Real, read-only role probes on an isolated restored laboratory."""

import json
import time


def login_with_budget(request, url, account):
    """Honor the restored API's login protection without changing its limits."""
    for attempt in range(3):
        response = request.post(
            url,
            form={"username": account["email"], "password": account["password"]},
            max_redirects=0,
        )
        if response.status != 429 or attempt == 2:
            return response
        try:
            delay = int(response.headers.get("retry-after", "60"))
        except (ValueError, TypeError):
            delay = 60
        time.sleep(max(1, min(delay, 60)))


def probe_roles(
    browser, base, api_port, accounts, guard, websocket, checks, page_errors
):
    from playwright.sync_api import expect

    for role in (
        "SUPERADMIN",
        "GERENTE",
        "OPERADOR",
        "REPARTIDOR",
        "AUDITOR",
        "CLIENTE",
    ):
        context = browser.new_context(service_workers="block")
        context.route("**/*", guard)
        context.route_web_socket("**/*", websocket)
        try:
            api = "http://127.0.0.1:" + str(api_port) + "/api/v1"
            login = login_with_budget(
                context.request, api + "/auth/login", accounts[role]
            )
            if login.status != 200:
                raise ValueError("Role login rejected")
            tokens = login.json()
            headers = {"Authorization": "Bearer " + tokens["access_token"]}
            identity = context.request.get(
                api + "/auth/me", headers=headers, max_redirects=0
            )
            if identity.status != 200 or identity.json()["role"] != role:
                raise ValueError("Role identity mismatch")
            checks.append("restored_verified_identity_" + role)
            payouts = context.request.get(
                api + "/payouts", headers=headers, max_redirects=0
            )
            expected = 200 if role in ("SUPERADMIN", "GERENTE", "REPARTIDOR") else 403
            if payouts.status != expected:
                raise ValueError("Role API boundary mismatch")
            checks.append("restored_payout_read_boundary_" + role)
            context.add_cookies(
                [{"name": "auth-token", "value": tokens["access_token"], "url": base}]
            )
            context.add_init_script(
                "localStorage.setItem('app_version','1.2.1');localStorage.setItem('access_token',"
                + json.dumps(tokens["access_token"])
                + ");localStorage.setItem('refresh_token',"
                + json.dumps(tokens.get("refresh_token", ""))
                + ");"
            )
            page = context.new_page()
            page.on(
                "pageerror",
                lambda error: page_errors.append("uncaught_role_browser_error"),
            )
            page.goto(
                base + "/manager/operations/orders", wait_until="domcontentloaded"
            )
            if role in ("SUPERADMIN", "GERENTE", "OPERADOR"):
                expect(
                    page.get_by_role("heading", name="Gestión de Órdenes", exact=True)
                ).to_be_visible(timeout=30000)
            else:
                destination = (
                    "/rider" if role == "REPARTIDOR" else "/access-unavailable"
                )
                expect(page).to_have_url(base + destination, timeout=30000)
                expect(
                    page.get_by_role("heading", name="Gestión de Órdenes", exact=True)
                ).to_have_count(0)
                if role != "REPARTIDOR":
                    expect(
                        page.get_by_role(
                            "heading",
                            name="Portal pendiente de habilitación",
                            exact=True,
                        )
                    ).to_be_visible(timeout=30000)
            checks.append("restored_cookie_independent_ui_boundary_" + role)
        finally:
            context.close()

"""Guarded browser acceptance against restored API/web images, never mocked data."""

import errno
import json
import os
from pathlib import Path
import re
import socket
from urllib.parse import urlsplit
from scripts.browser_layout import assert_order_controls


class PortGuards:
    """Detect conflicts and reserve IPv6 loopback while Docker publishes IPv4.

    Without the IPv6 guard, a compiled localhost API URL could hit another
    service on ::1 instead of the restored IPv4-only endpoint.
    """

    def __init__(self, api_port, web_port):
        self.ipv4 = {}
        self.ipv6 = []
        if api_port == web_port or any(
            type(p) is not int or not 1024 <= p <= 65535 for p in (api_port, web_port)
        ):
            raise ValueError("Distinct local laboratory ports required")
        try:
            for port in (api_port, web_port):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.ipv4[port] = sock
                if os.name == "posix":
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                elif hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind(("127.0.0.1", port))
                if socket.has_ipv6:
                    try:
                        guard = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                    except OSError as error:
                        if error.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                            continue
                        raise
                    try:
                        guard.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                        guard.bind(("::1", port))
                    except OSError as error:
                        guard.close()
                        if error.errno not in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                            raise
                    else:
                        self.ipv6.append(guard)
        except OSError:
            self.close()
            raise ValueError(
                "A restored frontend port is already occupied or unavailable"
            ) from None

    def release_ipv4(self, port):
        self.ipv4.pop(port).close()

    def close(self):
        for sock in [*self.ipv4.values(), *self.ipv6]:
            sock.close()
        self.ipv4.clear()
        self.ipv6.clear()


def local_target(url, port, schemes=("http",)):
    try:
        value = urlsplit(url)
        return (
            value.scheme in schemes
            and value.hostname in ("127.0.0.1", "localhost")
            and value.port == port
            and value.username is None
            and value.password is None
        )
    except ValueError:
        return False


def request_policy(url, method, api_port, web_port):
    try:
        value = urlsplit(url)
    except ValueError:
        return False
    if value.scheme in ("data", "blob", "about"):
        return True
    method = method.upper()
    if local_target(url, api_port) and value.path.startswith("/api/v1/"):
        if method in ("GET", "HEAD", "OPTIONS"):
            return True
        return method == "POST" and value.path in (
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/auth/logout",
            "/api/v1/notifications/read",
            "/api/v1/notifications/read-all",
        )
    if local_target(url, web_port):
        return method in ("GET", "HEAD") and not value.path.startswith("/api/")
    return False


def heartbeat(message):
    try:
        return json.loads(message) == {"type": "ping"}
    except (ValueError, TypeError):
        return False


def probe(
    *,
    web_port,
    api_port,
    account,
    accounts,
    sample_order,
    sample_zone,
    artifacts,
    chromium=None,
    run_id
):
    from playwright.sync_api import sync_playwright, expect

    artifacts = Path(artifacts)
    artifacts.mkdir(mode=0o700, parents=True, exist_ok=False)
    checks, violations, page_errors, observed_orders = [], [], [], []
    base = "http://127.0.0.1:" + str(web_port)
    phase = "browser_start"
    with sync_playwright() as pw:
        options = {
            "headless": True,
            "args": ["--host-resolver-rules=MAP localhost 127.0.0.1"],
        }
        if chromium:
            options["executable_path"] = str(chromium)
        browser = pw.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            timezone_id="America/Caracas",
            service_workers="block",
        )

        def guard(route):
            request = route.request
            if not request_policy(request.url, request.method, api_port, web_port):
                violations.append("unexpected_origin_or_mutation")
                route.abort()
            else:
                route.continue_()

        context.route("**/*", guard)

        def websocket(route):
            try:
                valid = (
                    local_target(route.url, api_port, ("ws",))
                    and urlsplit(route.url).path == "/api/v1/notifications/ws"
                )
                if not valid:
                    violations.append("unexpected_websocket_target")
                    route.close(code=1008, reason="Recovery boundary")
                    return
                server = None
                pending_ping = []

                def outbound(message):
                    try:
                        if heartbeat(message):
                            if server is not None:
                                server.send(message)
                            elif not pending_ping:
                                pending_ping.append(message)
                        else:
                            violations.append("unexpected_websocket_mutation")
                            route.close(code=1008, reason="Recovery boundary")
                    except Exception:
                        pass  # A socket may close during navigation; never log token URLs.

                def inbound(message):
                    try:
                        route.send(message)
                    except Exception:
                        pass

                route.on_message(outbound)
                server = route.connect_to_server()
                server.on_message(inbound)
                for message in pending_ping:
                    server.send(message)
            except Exception:
                violations.append("websocket_probe_error")
                try:
                    route.close(code=1008, reason="Recovery boundary")
                except Exception:
                    pass

        context.route_web_socket("**/*", websocket)
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append("uncaught_browser_error"))

        def response(value):
            if (
                local_target(value.url, api_port)
                and urlsplit(value.url).path == "/api/v1/orders"
                and value.status == 200
            ):
                try:
                    rows = value.json()
                    if isinstance(rows, list) and any(
                        str(r.get("id")) == sample_order["id"]
                        for r in rows
                        if isinstance(r, dict)
                    ):
                        observed_orders.append(True)
                except Exception:
                    pass

        page.on("response", response)
        screenshots = []

        def capture(name):
            page.screenshot(path=str(artifacts / name), full_page=False)
            screenshots.append(name)

        try:
            phase = "anonymous_boundary"
            page.goto(
                base + "/manager/operations/orders", wait_until="domcontentloaded"
            )
            expect(page).to_have_url(re.compile(r"/login(?:\?|$)"), timeout=30000)
            checks.append("anonymous_restored_manager_requires_login")
            expect(page.locator("input[type=email]")).to_be_visible()
            checks.append("restored_frontend_assets_and_login_loaded")
            phase = "login"
            page.locator("input[type=email]").fill(account["email"])
            page.locator("input[type=password]").fill(account["password"])
            page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
            page.wait_for_url(re.compile(r"/manager(?:/|$)"), timeout=30000)
            checks.append("real_superadmin_browser_login_on_copy")
            phase = "orders_desktop"
            page.goto(
                base + "/manager/operations/orders", wait_until="domcontentloaded"
            )
            expect(
                page.get_by_role("heading", name="Gestión de Órdenes", exact=True)
            ).to_be_visible()
            order = page.get_by_role(
                "article", name="Orden " + sample_order["label"], exact=True
            ).first
            expect(order).to_be_visible(timeout=30000)
            checks.append("restored_order_visible_desktop")
            if not observed_orders:
                raise ValueError("Restored order response not observed")
            checks.append("browser_order_identity_matches_backup")
            phase = "order_controls_responsive"
            for width in (320, 390, 768, 1024, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                # The sidebar transitions between mobile and desktop layouts.
                page.wait_for_function("""() => {
                        const aside = document.querySelector('aside');
                        const r = aside.getBoundingClientRect();
                        return innerWidth < 768 ? r.right <= 1 : r.left >= -1;
                    }""")
                assert_order_controls(page)
            checks.append("restored_order_controls_unclipped_at_five_viewports")
            page.get_by_role(
                "heading", name="Gestión de Órdenes", exact=True
            ).scroll_into_view_if_needed()
            capture("orders-desktop.png")
            phase = "zones_desktop"
            page.goto(base + "/manager/fleet/zones", wait_until="domcontentloaded")
            expect(
                page.get_by_role("heading", name="Zonas de Reparto", exact=True)
            ).to_be_visible()
            expect(
                page.get_by_text(sample_zone["name"], exact=True).first
            ).to_be_visible(timeout=30000)
            checks.append("restored_zone_visible_desktop")
            capture("zones-desktop.png")
            phase = "session_reload"
            page.reload(wait_until="domcontentloaded")
            expect(
                page.get_by_text(sample_zone["name"], exact=True).first
            ).to_be_visible(timeout=30000)
            checks.append("restored_browser_session_survives_reload")
            page.set_viewport_size({"width": 390, "height": 844})
            phase = "orders_mobile"
            page.goto(
                base + "/manager/operations/orders", wait_until="domcontentloaded"
            )
            expect(
                page.get_by_role(
                    "article", name="Orden " + sample_order["label"], exact=True
                ).first
            ).to_be_visible(timeout=30000)
            checks.append("restored_order_visible_mobile")
            capture("orders-mobile.png")
            overflow = page.evaluate(
                "document.documentElement.scrollWidth > innerWidth + 1"
            )
            phase = "zones_mobile"
            page.goto(base + "/manager/fleet/zones", wait_until="domcontentloaded")
            expect(
                page.get_by_text(sample_zone["name"], exact=True).first
            ).to_be_visible(timeout=30000)
            checks.append("restored_zone_visible_mobile")
            capture("zones-mobile.png")
            overflow = overflow or page.evaluate(
                "document.documentElement.scrollWidth > innerWidth + 1"
            )
            phase = "responsive_layout"
            if overflow:
                raise ValueError("Mobile horizontal overflow")
            checks.append("restored_pages_fit_mobile_viewport")
            phase = "restored_role_boundaries"
            from scripts.recovery_roles import probe_roles

            probe_roles(
                browser, base, api_port, accounts, guard, websocket, checks, page_errors
            )
            phase = "network_boundary"
            if violations:
                raise ValueError("Recovery network boundary rejected a request")
            checks.append("all_requests_bound_to_restored_endpoints")
            phase = "page_errors"
            if page_errors:
                raise ValueError("Restored page raised a browser error")
            checks.append("no_unapproved_mutation_or_browser_error")
        except Exception:
            try:
                page.screenshot(
                    path=str(artifacts / "failure.png"), mask=[page.locator("input")]
                )
                fd = os.open(
                    artifacts / "results.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                with os.fdopen(fd, "w") as output:
                    json.dump(
                        {
                            "checks": checks,
                            "errors": ["failed_at_" + phase],
                            "production_acceptance": False,
                        },
                        output,
                    )
            except Exception:
                pass
            raise ValueError("Restored frontend check failed at " + phase) from None
        finally:
            context.close()
            browser.close()
    return {
        "version": 1,
        "recovery_run_id": run_id,
        "checks": checks,
        "errors": [],
        "page_errors": [],
        "unapproved_requests": 0,
        "screenshots": screenshots,
        "real_backend": True,
        "mocked_responses": False,
        "production_acceptance": False,
    }

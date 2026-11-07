"""Verify a local production build with intercepted business HTTP/WebSocket.

Uses synthetic accounts, transactions and downloaded page CSV; refuses remote
preview URLs. Requires Playwright Python and Chromium. Never contacts a real API.
"""

import argparse
import csv
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect


def transaction(index, query=None):
    query = query or {}
    return dict(
        id=f"tx-{index}",
        rider_id="rider-1",
        amount=0 if index == 50 else 25,
        transaction_type=query.get("type", ["RETIRO"])[0],
        type=query.get("type", ["RETIRO"])[0],
        status=query.get("status", ["PROCESADO"])[0],
        description="=SUM(1,1)" if index == 50 else f'Movimiento José, "{index}"',
        reference_id=None,
        source_type="withdrawal",
        source_id=f"source-{index}",
        idempotency_key=None,
        created_by_user_id="actor-1",
        balance_before=0,
        balance_after=None,
        created_at="2026-11-07T12:00:00",
        updated_at=None,
    )


def batch(query):
    offset = int(query["offset"][0])
    end = min(offset + int(query["limit"][0]), 73)
    return [transaction(index, query) for index in range(offset, end)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3069")
    parser.add_argument(
        "--artifacts-dir", default="/tmp/delivery360-transactions-browser"
    )
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Use a local preview, never production")
    artifacts = Path(args.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    requests, writes, errors, downloads, checks = [], [], [], [], []
    state = {"mode": "normal", "pending": None}

    def passed(name):
        checks.append(name)
        print("passed: " + name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium, headless=True, args=["--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            accept_downloads=True,
            locale="es-VE",
            service_workers="block",
        )
        context.set_default_timeout(10000)
        context.add_cookies(
            [{"name": "auth-token", "value": "synthetic-token", "url": base}]
        )
        context.add_init_script(
            """if (!localStorage.getItem('transactions-browser-initialized')) {
          localStorage.setItem('app_version', '1.2.1');
          localStorage.setItem('access_token', 'synthetic-token');
          localStorage.setItem('refresh_token', 'synthetic-refresh');
          localStorage.setItem('transactions-browser-initialized', 'yes');
        }"""
        )
        context.route_web_socket("**/*", lambda socket: None)

        def intercept(route):
            target = urlparse(route.request.url)
            path, query = target.path, parse_qs(target.query)
            headers = {
                "access-control-allow-origin": base,
                "access-control-allow-headers": "authorization, content-type",
                "access-control-allow-methods": "GET, OPTIONS",
            }
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif (
                "/financial/transactions" in path
                and target.netloc != urlparse(base).netloc
            ):
                requests.append(
                    {"path": path, "query": query, "method": route.request.method}
                )
                if route.request.method != "GET":
                    writes.append(path)
                    route.abort()
                    return
                detail = not path.endswith("/transactions")
                if state["mode"] == "failure":
                    route.fulfill(
                        status=503,
                        json={"detail": "Synthetic failure"},
                        headers=headers,
                    )
                elif state["mode"] == "defer":
                    state["pending"] = (route, query, headers, path)
                elif detail:
                    index = int(path.rsplit("-", 1)[-1])
                    row = transaction(index)
                    if state["mode"] == "wrong_id":
                        row["id"] = "another-id"
                    route.fulfill(json=row, headers=headers)
                else:
                    route.fulfill(json=batch(query), headers=headers)
            elif path.endswith(("/auth/me", "/users/me")):
                route.fulfill(
                    json={
                        "id": "browser-user",
                        "email": "transactions@example.test",
                        "role": "GERENTE",
                        "is_active": True,
                        "first_name": "Prueba",
                        "last_name": "Local",
                        "created_at": "2026-11-01T00:00:00Z",
                    },
                    headers=headers,
                )
            elif route.request.url.startswith(base + "/"):
                route.continue_()
            else:
                if route.request.method != "GET":
                    writes.append(path)
                route.fulfill(
                    json=[] if "alerts" in path else {"items": [], "unread_count": 0},
                    headers=headers,
                )

        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("download", lambda download: downloads.append(download))
        history = base + "/manager/financial/transactions"
        page.goto(history, wait_until="domcontentloaded")
        confirmed = page.get_by_role("region", name="Página confirmada")
        expect(confirmed).to_be_visible()
        expect(
            page.get_by_role("link", name="Ver transacción tx-49", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("link", name="Ver transacción tx-50", exact=True)
        ).to_have_count(0)
        assert requests[-1]["query"] == {"limit": ["51"], "offset": ["0"]}
        assert (
            "COP" not in confirmed.inner_text() and "+25" not in confirmed.inner_text()
        )
        passed("bounded_first_page_and_neutral_positive_withdrawal")

        page.get_by_role("button", name="Siguiente", exact=True).click()
        expect(
            page.get_by_role("link", name="Ver transacción tx-50", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Siguiente", exact=True)
        ).to_be_disabled()
        assert requests[-1]["query"]["offset"] == ["50"]
        count = len(requests)
        page.get_by_label("Buscar solo en esta página", exact=True).fill("tx-50")
        expect(
            page.get_by_text(
                "23 filas cargadas; 1 coincidencias visibles.", exact=False
            )
        ).to_be_visible()
        assert len(requests) == count
        with page.expect_download() as event:
            page.get_by_role("button", name="Exportar página CSV", exact=True).click()
        download = event.value
        csv_path = artifacts / "transacciones-pagina-verificada.csv"
        download.save_as(str(csv_path))
        rows = list(
            csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8-sig")))
        )
        assert len(rows) == 1 and rows[0]["id"] == "tx-50"
        assert rows[0]["importe_registrado"] == "0" and rows[0]["moneda"] == ""
        assert rows[0]["descripcion"] == "'=SUM(1,1)"
        assert rows[0]["saldo_anterior"] == "0" and rows[0]["saldo_posterior"] == ""
        assert (
            rows[0]["desplazamiento_consulta"] == "50"
            and rows[0]["busqueda_local"] == "tx-50"
        )
        assert rows[0]["fecha_creacion_utc"] == "2026-11-07T12:00:00Z"
        assert "no es el historial completo" in rows[0]["alcance"]
        assert "pagina_2_1_filas" in download.suggested_filename
        passed("second_page_local_search_and_actual_partial_csv")

        state["mode"] = "failure"
        page.get_by_role("button", name="Actualizar consulta").click()
        expect(
            page.get_by_role("alert").filter(has_text="No se pudo comprobar")
        ).to_be_visible()
        expect(
            page.get_by_role("link", name="Ver transacción tx-50", exact=True)
        ).to_be_visible()
        expect(page.get_by_role("button", name="Exportar página CSV")).to_be_disabled()
        state["mode"] = "normal"
        page.get_by_role("button", name="Reintentar consulta").click()
        expect(page.get_by_role("button", name="Exportar página CSV")).to_be_enabled()
        assert requests[-1]["query"]["offset"] == ["50"]
        page.get_by_label("Buscar solo en esta página", exact=True).fill("")
        page.get_by_label("Tipo en el servidor", exact=True).select_option(
            "BANK_TRANSFER"
        )
        expect(
            page.get_by_text(
                "Consulta confirmada: tipo BANK_TRANSFER; estado ALL.", exact=True
            )
        ).to_be_visible()
        page.get_by_label("Estado en el servidor", exact=True).select_option("PAGADO")
        expect(
            page.get_by_text(
                "Consulta confirmada: tipo BANK_TRANSFER; estado PAGADO.", exact=True
            )
        ).to_be_visible()
        assert requests[-1]["query"] == {
            "type": ["BANK_TRANSFER"],
            "status": ["PAGADO"],
            "limit": ["51"],
            "offset": ["0"],
        }
        page.screenshot(
            path=str(artifacts / "transactions-desktop.png"), full_page=True
        )
        passed("failed_refresh_preserves_page_retry_and_server_filters")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right <= 1"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for label in (
            "Buscar solo en esta página",
            "Tipo en el servidor",
            "Estado en el servidor",
        ):
            box = page.get_by_label(label, exact=True).bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= 390
        page.screenshot(path=str(artifacts / "transactions-mobile.png"), full_page=True)
        passed("mobile_filters_fit_and_table_scrolls_locally")

        state["mode"] = "wrong_id"
        page.get_by_role("link", name="Ver transacción tx-0", exact=True).click()
        expect(
            page.get_by_role("alert").filter(has_text="No se pudo comprobar")
        ).to_be_visible()
        expect(page.get_by_role("region", name="Transacción confirmada")).to_have_count(
            0
        )
        expect(page.get_by_role("button", name="Imprimir registro")).to_be_disabled()
        state["mode"] = "normal"
        page.get_by_role("button", name="Reintentar lectura").click()
        expect(page.get_by_text("ID confirmado: tx-0", exact=True)).to_be_visible()
        expect(page.get_by_text("Fecha no informada", exact=True)).to_have_count(2)
        expect(page.get_by_text("Moneda", exact=True).locator("..")).to_contain_text(
            "No informada"
        )
        expect(
            page.get_by_role("region", name="Transacción confirmada")
        ).to_contain_text("no son una confirmación bancaria")
        page.evaluate(
            "() => { window.printCalls = 0; window.print = () => { window.printCalls += 1; }; }"
        )
        page.get_by_role("button", name="Imprimir registro").click()
        page.wait_for_function("window.printCalls === 1")
        page.screenshot(
            path=str(artifacts / "transaction-detail-mobile.png"), full_page=True
        )
        passed("detail_link_rejects_wrong_identity_retry_and_honest_print")

        state["mode"] = "defer"
        page.get_by_role("button", name="Consultar transacción").click()
        expect(
            page.get_by_role("status").filter(has_text="Consultando el registro")
        ).to_be_visible()
        old = state["pending"]
        state["mode"] = "normal"
        page.get_by_role("link", name="Volver al historial").click()
        expect(
            page.get_by_role("link", name="Ver transacción tx-1", exact=True)
        ).to_be_visible()
        page.get_by_role("link", name="Ver transacción tx-1", exact=True).click()
        expect(page.get_by_text("ID confirmado: tx-1", exact=True)).to_be_visible()
        old[0].fulfill(json=transaction(0), headers=old[2])
        state["pending"] = None
        page.wait_for_timeout(150)
        expect(page.get_by_text("ID confirmado: tx-0", exact=True)).to_have_count(0)
        passed("old_detail_response_cannot_replace_another_route")

        state["mode"] = "defer"
        page.get_by_role("button", name="Consultar transacción").click()
        expect(
            page.get_by_role("status").filter(has_text="Consultando el registro")
        ).to_be_visible()
        page.evaluate("window.dispatchEvent(new Event('delivery360-session-expired'))")
        page.wait_for_url("**/login")
        assert page.evaluate("localStorage.getItem('access_token')") is None
        pending = state["pending"]
        pending[0].fulfill(json=transaction(1), headers=pending[2])
        page.wait_for_timeout(150)
        expect(page.get_by_role("region", name="Transacción confirmada")).to_have_count(
            0
        )
        assert len(downloads) == 1 and not writes and not errors
        passed("logout_retires_pending_private_detail")
        result = {
            "checks_passed": checks,
            "transaction_requests": requests,
            "downloads": len(downloads),
            "write_requests": writes,
            "page_errors": errors,
        }
        (artifacts / "browser-results.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print(
            json.dumps(
                {
                    "checks_passed": len(checks),
                    "transaction_requests": len(requests),
                    "downloads": len(downloads),
                    "write_requests": len(writes),
                    "page_errors": errors,
                }
            ),
            flush=True,
        )
        browser.close()


if __name__ == "__main__":
    main()

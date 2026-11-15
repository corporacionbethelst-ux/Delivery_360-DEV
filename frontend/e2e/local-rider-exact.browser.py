"""Exact rider earnings: current ledger, private identity, complete CSV and no monetary writes."""

import argparse, csv, io, json, re, stat, subprocess, sys, time
from pathlib import Path
from decimal import Decimal
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from playwright.sync_api import sync_playwright, expect


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chromium", default="/usr/bin/chromium")
    p.add_argument("--artifacts-dir", required=True)
    p.add_argument("--lifecycle-results", required=True)
    p.add_argument("--wait-request-window", action="store_true")
    args = p.parse_args()
    state = local_test.configuration()
    cmd = local_test.compose(state, local_test.local_docker())
    env = local_test.compose_environment()

    def sql(q):
        return subprocess.check_output(
            cmd
            + [
                "exec",
                "-T",
                "test-db",
                "psql",
                "-U",
                "local_test",
                "-d",
                "test_delivery360_manual",
                "-Atc",
                q,
            ],
            env=env,
            text=True,
        ).strip()

    assert sql("SELECT id FROM local_test_instance") == state["instance"]
    local_test.check(state, authenticate=False)
    life = json.loads(Path(args.lifecycle_results).read_text())
    assert re.fullmatch("[0-9a-f]{12}", life["run"])
    path = local_test.STATE / ("lifecycle-rider-" + life["run"] + ".json")
    assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    context = json.loads(path.read_text())
    assert (
        context["instance"] == state["instance"]
        and context["rider_id"] == life["rider_id"]
    )
    account = context["account"]
    if args.wait_request_window:
        time.sleep(60)
        time.sleep(1)
    base = "http://localhost:" + str(state["web_port"])
    api = "http://localhost:" + str(state["api_port"]) + "/api/v1"
    out = Path(args.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    writes = []
    reads = []

    def passed(name):
        checks.append(name)
        print("passed:", name, flush=True)

    def snapshot():
        return {
            t: sql(
                "SELECT count(*)::text||':'||md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM "
                + t
                + " t"
            )
            for t in (
                "orders",
                "financials",
                "financial_transactions",
                "rider_wallets",
                "payouts",
                "payout_status_history",
                "bcv_rates",
                "customer_collections",
                "customer_collection_reviews",
                "customer_refunds",
                "customer_refund_events",
            )
        }

    before = snapshot()

    def money(value):
        whole, cents = value.split(".")
        return (
            ("−" if whole.startswith("-") else "")
            + "USD "
            + re.sub(r"(?<=\d)(?=(\d{3})+$)", ".", whole.lstrip("-"))
            + ","
            + cents
        )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="es-VE",
            timezone_id="America/Caracas",
            accept_downloads=True,
        )
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/login", wait_until="domcontentloaded")
        page.locator("input[type=email]").fill(account["email"])
        page.locator("input[type=password]").fill(account["password"])
        page.get_by_role("button", name=re.compile("Iniciar sesi", re.I)).click()
        page.wait_for_url(base + "/rider", timeout=30000)
        token = page.evaluate('localStorage.getItem("access_token")')
        assert token
        headers = {"Authorization": "Bearer " + token}

        def get(path, status=200):
            r = page.request.get(api + path, headers=headers)
            assert r.status == status, (path, r.status)
            return r.json()

        me = get("/auth/me")
        profile = get("/riders/me")
        assert profile["id"] == context["rider_id"] and me["id"] == sql(
            "SELECT user_id FROM riders WHERE id='" + profile["id"] + "'"
        )
        passed(
            "private lifecycle continuation authenticates the actual owner in the marked laboratory"
        )
        report = get("/financial/riders/me/report")
        balance = get("/payouts/balance/exact")
        assert (
            report["user_id"] == balance["user_id"] == me["id"]
            and report["rider_id"] == balance["rider_id"] == profile["id"]
        )
        assert (
            report["lifetime"]["credit_usd"] == life["earned"]
            and balance["available"] == life["available"]
        )
        assert (
            Decimal(balance["available"])
            == max(
                Decimal("0.00"),
                Decimal(balance["ledger_balance"]) - Decimal(balance["reserved"]),
            )
            and balance["reserved"] == "0.00"
            and not balance["bank_verified"]
        )
        passed(
            "server returns exact owner credits and canonical available balance without double reserving posted withdrawals"
        )

        def track(request):
            if "/api/v1/" not in request.url:
                return
            financial = "/financial/" in request.url or "/payouts/" in request.url
            if financial:
                if request.method not in ("GET", "OPTIONS"):
                    writes.append(request.method + " " + request.url)
                elif request.method == "GET":
                    reads.append(request.url)

        page.on("request", track)
        # Reload to observe every financial consumer on the dashboard.
        page.reload(wait_until="domcontentloaded")
        today = page.get_by_text("Ganado Hoy", exact=True).locator("..")
        expect(
            today.get_by_text(money(report["day"]["credit_usd"]), exact=True)
        ).to_be_visible(timeout=30000)
        week = page.get_by_text("Últimos 7 días", exact=True).locator("..")
        expect(
            week.get_by_text(money(report["week"]["credit_usd"]), exact=True)
        ).to_be_visible()
        passed(
            "rider dashboard shows registered day and seven-day credits rather than customer order amounts"
        )
        page.goto(base + "/rider/productivity", wait_until="domcontentloaded")
        income = page.get_by_text("Créditos USD registrados", exact=True).locator("..")
        expect(
            income.get_by_text(money(report["lifetime"]["credit_usd"]), exact=True)
        ).to_be_visible(timeout=30000)
        passed(
            "productivity uses the same exact recorded lifetime credit independently of delivery invoice value"
        )
        page.goto(base + "/rider/earnings", wait_until="domcontentloaded")
        region = page.get_by_role(
            "region", name="Ganancias exactas confirmadas", exact=True
        )
        expect(region).to_be_visible(timeout=30000)
        expect(
            page.get_by_role("heading", name="Mis Ganancias", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text(
                "1 movimientos anteriores requieren revisión de moneda.", exact=True
            )
        ).to_be_visible()
        expect(
            page.get_by_text(
                "1 retiros anteriores conservan su moneda sin verificar.", exact=True
            )
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Solicitar Retiro", exact=True)
        ).to_be_disabled()
        passed(
            "earnings separates original-unit exclusions and does not enable a withdrawal below the exact minimum"
        )
        initial = len(reads)
        with page.expect_download() as download:
            page.get_by_role("button", name="Exportar movimientos", exact=True).click()
        target = out / "own-earnings.csv"
        download.value.save_as(target)
        exported = list(
            csv.DictReader(io.StringIO(target.read_text(encoding="utf-8-sig")))
        )
        assert len(exported) == report["row_count"] and len(reads) == initial
        assert {r["id"] for r in exported} == {r["id"] for r in report["rows"]}
        assert all(
            r["rider_id"] == profile["id"] and r["usuario"] == me["id"]
            for r in exported
        )
        assert len({r["huella_sha256"] for r in exported}) == 1
        for source, row in zip(report["rows"], exported):
            for field in ("amount_usd", "delta_usd"):
                expected = source[field] or ""
                expected = "'" + expected if expected.startswith("-") else expected
                assert row[field] == expected
        passed(
            "CSV contains all owner movements and exclusions with exact signed amounts, one fingerprint and no second read"
        )
        assert all(
            "/financial/riders/me/report" in url or "/payouts/balance/exact" in url
            for url in reads
        ), reads
        passed(
            "all three rider screens stop requesting numeric legacy earnings and balance endpoints"
        )
        page.screenshot(path=str(out / "earnings-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.querySelector('aside').getBoundingClientRect().right<=1"
        )
        expect(
            page.get_by_role("heading", name="Mis Ganancias", exact=True)
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(out / "earnings-mobile.png"))
        passed(
            "exact earnings layout remains colorful and readable on desktop and mobile without viewport overflow"
        )
        page.route(
            "**/api/v1/payouts/balance/exact",
            lambda r: r.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "Saldo exacto temporalmente no disponible"}),
            ),
        )
        page.get_by_role("button", name="Actualizar", exact=True).click()
        expect(
            page.get_by_role("heading", name="Saldo USD por confirmar", exact=True)
        ).to_be_visible()
        expect(region).to_be_visible()
        expect(
            page.get_by_role("button", name="Solicitar Retiro", exact=True)
        ).to_be_disabled()
        expect(
            page.get_by_role("button", name="Exportar movimientos", exact=True)
        ).to_be_enabled()
        passed(
            "an unavailable balance disables withdrawal while preserving independently confirmed earnings and export"
        )
        page.unroute("**/api/v1/payouts/balance/exact")
        forged = {**report, "user_id": str(uuid4())}
        page.route(
            "**/api/v1/financial/riders/me/report",
            lambda r: r.fulfill(
                status=200, content_type="application/json", body=json.dumps(forged)
            ),
        )
        page.get_by_role("button", name="Actualizar", exact=True).click()
        expect(
            page.get_by_role("heading", name="Ganancias por confirmar", exact=True)
        ).to_be_visible()
        expect(region).not_to_be_visible()
        expect(
            page.get_by_role("button", name="Exportar movimientos", exact=True)
        ).to_be_disabled()
        expect(
            page.get_by_role("button", name="Solicitar Retiro", exact=True)
        ).to_be_disabled()
        passed(
            "a mismatched private owner response cannot publish figures, export or enable withdrawal"
        )
        get("/financial/riders/me/report?rider_id=" + str(uuid4()), 422)
        get("/payouts/balance/exact?rider_id=" + str(uuid4()), 422)
        passed(
            "private read endpoints reject foreign rider selectors instead of accepting client-chosen identities"
        )
        assert not errors and not writes, (errors, writes)
        ctx.close()
        browser.close()
    assert before == snapshot(), "Rider financial reads changed monetary history"
    passed(
        "orders, customer books, withdrawals and rider ledgers retain identical hashes; zero financial writes or JavaScript errors"
    )
    (out / "results.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "writes": writes,
                "history_preserved": True,
                "rider_id": context["rider_id"],
                "rows": report["row_count"],
                "currency": "USD",
                "context_credentials_exported": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

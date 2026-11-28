"""Real self profile partial writes and vehicle effects on disposable laboratory records."""
import argparse, json, re, sys, time
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import local_test
from scripts.recovery import Recovery, FINANCIAL_TABLES
from scripts.local_read_benchmark import verify_target

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--chromium', default='/usr/bin/chromium')
    p.add_argument('--artifacts-dir', required=True, type=Path)
    p.add_argument('--wait-request-window', action='store_true')
    args = p.parse_args()
    tool = Recovery()
    verify_target(tool)
    if args.wait_request_window:
        for _ in range(61):
            time.sleep(1)
    account = json.loads(local_test.ACCOUNTS.read_text())['REPARTIDOR']
    source_email = account['email'].replace("'", "''")
    assert tool.source_sql(f"SELECT count(*) FROM users WHERE email='{source_email}' AND role='REPARTIDOR' AND is_active") == '1'
    owner, rider, doc = (str(uuid4()), str(uuid4()), str(uuid4()))
    tag = uuid4().hex[:10]
    email = 'perfil132-' + tag + '@example.com'
    plate = 'T132' + tag.upper()
    new_plate = 'N132' + tag.upper()
    protected = FINANCIAL_TABLES | {'users', 'riders', 'audit_logs', 'notification_logs', 'notification_preferences'}
    before = {k: v for k, v in tool.source_tables().items() if k in protected}
    assert len(before) == 24
    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    puts = []
    rejected = []
    errors = []
    checks = []
    seeded = False

    def passed(message):
        checks.append(message)
        print('passed:', message, flush=True)
    base = 'http://localhost:' + str(tool.source['web_port'])
    try:
        seeded = True
        tool.source_sql(f"BEGIN;\nINSERT INTO users(id,email,hashed_password,first_name,last_name,phone,role,is_active,is_superuser,created_at,updated_at,token_version)\nSELECT '{owner}'::uuid,'{email}',hashed_password,'Perfil132','Prueba','+584121320000','REPARTIDOR',true,false,NOW() AT TIME ZONE 'UTC',NOW() AT TIME ZONE 'UTC',0 FROM users WHERE email='{source_email}';\nINSERT INTO riders(id,user_id,vehicle_type,vehicle_plate,vehicle_ownership_type,status,tier,is_online,version,created_at,updated_at,wallet_balance,pending_balance,wallet_currency)\nVALUES('{rider}'::uuid,'{owner}'::uuid,'MOTO','{plate}','PROPIO','ACTIVO','BRONCE',true,0,NOW() AT TIME ZONE 'UTC',NOW() AT TIME ZONE 'UTC',0,0,'USD');\nINSERT INTO rider_documents(id,rider_id,type,status) VALUES('{doc}'::uuid,'{rider}'::uuid,'REGISTRO_VEHICULO','APROBADO');\nCOMMIT;")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1100}, timezone_id='America/Caracas', service_workers='block')

            def guard(route):
                req = route.request
                path = req.url.split('/api/v1', 1)[-1].split('?', 1)[0]
                if req.method == 'PUT' and path == '/riders/me':
                    body = req.post_data_json
                    index = len(puts)
                    allowed = index == 0 and set(body) == {'phone', 'expected_profile_revision'} and (body['phone'] == '+584121329999') or (index == 1 and set(body) == {'vehicle_plate', 'expected_assignment_revision'} and (body['vehicle_plate'] == new_plate))
                    if not allowed:
                        rejected.append({'method': req.method, 'path': path})
                        route.abort()
                        return
                    assert all((re.fullmatch('[a-f0-9]{64}', v) for k, v in body.items() if k.startswith('expected_')))
                    puts.append(body)
                    response = route.fetch(max_redirects=0, max_retries=0)
                    assert response.status == 200
                    receipt = response.json()
                    assert receipt['id'] == rider and receipt['user_id'] == owner
                    if index == 0:
                        route.fulfill(status=503, json={'detail': 'Synthetic lost acknowledgement'})
                    else:
                        route.fulfill(response=response)
                    return
                if req.method not in ('GET', 'OPTIONS') and (not (req.method == 'POST' and path in ('/auth/login', '/auth/refresh'))):
                    rejected.append({'method': req.method, 'path': path})
                    route.abort()
                    return
                route.continue_()
            context.route('**/api/v1/**', guard)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append('browser_exception'))
            page.goto(base + '/login?callbackUrl=/rider/profile', wait_until='domcontentloaded')
            page.locator('input[type=email]').fill(email)
            page.locator('input[type=password]').fill(account['password'])
            page.get_by_role('button', name=re.compile('Iniciar sesi', re.I)).click()
            page.wait_for_url(base + '/rider/profile', timeout=30000)
            phone = page.get_by_label('Teléfono / WhatsApp', exact=True)
            field = page.get_by_label('Placa', exact=True)
            save = page.get_by_role('button', name='Guardar cambios', exact=True)
            expect(field).to_have_value(plate)
            expect(phone).to_have_value('+584121320000')
            expect(save).to_be_disabled()
            passed('real authenticated profile loads the disposable rider identity without using its user id as rider id')
            phone.fill('+584121329999')
            save.click()
            modal = page.get_by_role('dialog', name='No se pudo confirmar el guardado', exact=True)
            expect(modal).to_be_visible()
            assert len(puts) == 1
            assert tool.source_sql(f"SELECT phone FROM users WHERE id='{owner}'::uuid") == '+584121329999'
            assert tool.source_sql(f"SELECT vehicle_plate||':'||status::text||':'||is_online::text FROM riders WHERE id='{rider}'::uuid") == plate + ':ACTIVO:true'
            assert tool.source_sql(f"SELECT status::text FROM rider_documents WHERE id='{doc}'::uuid") == 'APROBADO'
            passed('one partial personal PUT commits while its reply is lost; vehicle, document and availability remain untouched')
            modal.get_by_role('button', name='Consultar de nuevo').click()
            expect(modal).to_have_count(0)
            expect(phone).to_have_value('+584121329999')
            expect(page.get_by_text('Estado actual verificado', exact=True)).to_be_visible()
            assert len(puts) == 1
            passed('GET recovery verifies the persisted personal value without resending PUT')
            field.fill(new_plate)
            save.click()
            modal = page.get_by_role('dialog', name='Confirmar cambio de vehículo', exact=True)
            expect(modal).to_be_visible()
            assert len(puts) == 1
            modal.get_by_role('button', name='Confirmar cambio', exact=True).click()
            done = page.get_by_role('dialog', name='Revisa la documentación del vehículo', exact=True)
            expect(done).to_be_visible()
            assert len(puts) == 2
            assert tool.source_sql(f"SELECT vehicle_plate||':'||status::text||':'||is_online::text FROM riders WHERE id='{rider}'::uuid") == new_plate + ':PENDIENTE:false'
            assert tool.source_sql(f"SELECT status::text FROM rider_documents WHERE id='{doc}'::uuid") == 'RECHAZADO'
            assert tool.source_sql(f"SELECT count(*) FROM audit_logs WHERE user_id='{owner}'::uuid AND resource_id='{rider}' AND new_values->>'source'='self_profile' AND new_values->>'documents_invalidated'='1'") == '1'
            page.screenshot(path=str(args.artifacts_dir / 'real-profile-vehicle-confirmed.png'), full_page=True, animations='disabled')
            done.get_by_role('button', name='Cerrar', exact=True).click()
            passed('explicitly confirmed vehicle delta closes availability, invalidates only the fixture document and records exactly one fleet audit')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.wait_for_function("document.querySelector('aside').getBoundingClientRect().right<=1")
            phone.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
            assert phone.evaluate('e=>{const r=e.getBoundingClientRect(),t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.x>=0&&r.right<=innerWidth+1&&(t===e||e.contains(t));}')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(args.artifacts_dir / 'real-profile-mobile.png'), full_page=True, animations='disabled')
            context.close()
            browser.close()
    finally:
        if seeded:
            tool.source_sql(f"BEGIN;\nDELETE FROM audit_logs WHERE user_id='{owner}'::uuid;\nDELETE FROM rider_documents WHERE id='{doc}'::uuid AND rider_id='{rider}'::uuid;\nDELETE FROM rider_wallets WHERE rider_id='{rider}'::uuid;\nDELETE FROM riders WHERE id='{rider}'::uuid AND user_id='{owner}'::uuid;\nDELETE FROM users WHERE id='{owner}'::uuid AND email='{email}';\nCOMMIT;")
        after = {k: v for k, v in tool.source_tables().items() if k in protected}
        assert before == after, 'Original user, rider, document, history or financial data changed'
    assert len(puts) == 2 and (not rejected) and (not errors)
    passed('all disposable records removed; original users, riders, documents, audit and protected monetary/history tables are identical')
    (args.artifacts_dir / 'results.json').write_text(json.dumps({'real_api': True, 'checks': checks, 'sparse_puts': puts, 'rejected_mutations': rejected, 'page_errors': errors, 'original_protected_data_unchanged': True, 'protected_tables': sorted(before), 'fixture_documents_invalidated': 1, 'fixture_fleet_audits': 1}, indent=2))
if __name__ == '__main__':
    main()

"""Private self profile deltas, revision conflicts and recovery with a synthetic API."""
import argparse, json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default='http://127.0.0.1:3072')
    p.add_argument('--chromium', default='/usr/bin/chromium')
    p.add_argument('--artifacts-dir', required=True, type=Path)
    args = p.parse_args()
    base = args.base_url.rstrip('/')
    assert urlparse(base).hostname in ('localhost', '127.0.0.1')
    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    owner = '123e4567-e89b-42d3-a456-426614174000'
    rider = '123e4567-e89b-42d3-a456-426614174001'
    vehicle = '123e4567-e89b-42d3-a456-426614174002'
    profile = dict(id=rider, user_id=owner, first_name='Ana', last_name='Pérez', email='ana@example.test', phone='+584121234567', vehicle_type='PATINETA', vehicle_plate='SELF-132', vehicle_ownership_type='PROPIO', assigned_vehicle_id=None, profile_revision='a' * 64, assignment_revision='a' * 64)
    state = dict(mode='lost', read_failure=False, next_owner=False)
    writes = []
    errors = []
    unrelated = []
    checks = []

    def passed(message):
        checks.append(message)
        print('passed:', message, flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = browser.new_context(viewport={'width': 1440, 'height': 1100}, timezone_id='America/Caracas', service_workers='block')
        context.add_cookies([{'name': 'auth-token', 'value': 'synthetic-token', 'url': base}])
        context.add_init_script("localStorage.setItem('app_version','1.2.1');localStorage.setItem('access_token','synthetic-token');localStorage.setItem('refresh_token','synthetic-refresh');localStorage.setItem('user',JSON.stringify({role:'GERENTE',vehicle_plate:'OBSOLETE-STORE'}));")
        context.route_web_socket('**/*', lambda socket: None)

        def intercept(route):
            req = route.request
            target = urlparse(req.url)
            path = target.path
            headers = {'access-control-allow-origin': base, 'access-control-allow-headers': 'authorization,content-type', 'access-control-allow-methods': 'GET,PUT,OPTIONS'}
            if req.method == 'OPTIONS':
                route.fulfill(status=204, headers=headers)
            elif path.endswith(('/auth/me', '/users/me')):
                route.fulfill(json={'id': vehicle if state['next_owner'] else owner, 'role': 'REPARTIDOR', 'email': 'ana@example.test', 'first_name': 'Ana', 'last_name': 'Pérez', 'is_active': True}, headers=headers)
            elif path == '/api/v1/riders/me' and req.method == 'GET':
                route.fulfill(status=503 if state['read_failure'] else 200, json={'detail': 'PRIVATE_INTERNAL_VALUE'} if state['read_failure'] else profile, headers=headers)
            elif path == '/api/v1/riders/me' and req.method == 'PUT':
                patch = req.post_data_json
                assert set(patch) <= {'first_name', 'last_name', 'phone', 'vehicle_type', 'vehicle_plate', 'expected_profile_revision', 'expected_assignment_revision'}
                writes.append(patch)
                if state['mode'] == 'conflict':
                    profile.update(first_name='Concurrente', phone='+584149999999', profile_revision='c' * 64)
                    route.fulfill(status=409, json={'detail': 'PRIVATE_INTERNAL_VALUE'}, headers=headers)
                    return
                profile.update({k: v for k, v in patch.items() if not k.startswith('expected_')})
                profile.update(profile_revision='b' * 64, assignment_revision='b' * 64)
                route.fulfill(status=503 if state['mode'] == 'lost' else 200, json={'detail': 'PRIVATE_INTERNAL_VALUE'} if state['mode'] == 'lost' else profile, headers=headers)
            elif req.method not in ('GET', 'OPTIONS'):
                unrelated.append(path)
                route.abort()
            elif path == '/api/v1/notifications/inbox':
                route.fulfill(json={'items': [], 'unread_count': 0}, headers=headers)
            elif path.startswith('/api/') or target.netloc != urlparse(base).netloc:
                route.fulfill(json={}, headers=headers)
            else:
                route.continue_()
        context.route('**/*', intercept)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/rider/profile', wait_until='domcontentloaded')
        name = page.get_by_label('Nombre', exact=True)
        phone = page.get_by_label('Teléfono / WhatsApp', exact=True)
        plate = page.get_by_label('Placa', exact=True)
        kind = page.get_by_label('Tipo de vehículo', exact=True)
        save = page.get_by_role('button', name='Guardar cambios', exact=True)
        expect(plate).to_have_value('SELF-132')
        expect(kind).to_have_value('PATINETA')
        expect(save).to_be_disabled()
        expect(page.get_by_text('OBSOLETE-STORE', exact=True)).to_have_count(0)
        page.screenshot(path=str(args.artifacts_dir / 'profile-desktop.png'), full_page=True, animations='disabled')
        passed('verified rider API profile keeps distinct user/rider identities and supports the historical PATINETA option')
        phone.fill('+584121110000')
        save.click()
        modal = page.get_by_role('dialog', name='No se pudo confirmar el guardado', exact=True)
        expect(modal).to_be_visible()
        assert writes == [{'phone': '+584121110000', 'expected_profile_revision': 'a' * 64}]
        page.wait_for_function("() => {const e=document.querySelector('[role=dialog]');if(!e)return false;const r=e.getBoundingClientRect();return Math.abs(r.x+r.width/2-innerWidth/2)<3&&Math.abs(r.y+r.height/2-innerHeight/2)<3;}")
        r = modal.bounding_box()
        assert abs(r['x'] + r['width'] / 2 - 720) < 3 and abs(r['y'] + r['height'] / 2 - 550) < 3, r
        page.screenshot(path=str(args.artifacts_dir / 'profile-recovery-modal.png'), full_page=True, animations='disabled')
        state['read_failure'] = True
        modal.get_by_role('button', name='Consultar de nuevo').click()
        expect(modal.get_by_role('button', name='Consultar de nuevo')).to_be_enabled()
        state['read_failure'] = False
        modal.get_by_role('button', name='Consultar de nuevo').click()
        expect(modal).to_have_count(0)
        expect(phone).to_have_value('+584121110000')
        expect(page.get_by_text('Estado actual verificado', exact=True)).to_be_visible()
        assert len(writes) == 1
        passed('one partial personal PUT omits fleet fields; lost acknowledgement and failed recovery preserve uncertainty until GET verifies the value')
        state['mode'] = 'ok'
        plate.fill('NEW-132')
        save.click()
        modal = page.get_by_role('dialog', name='Confirmar cambio de vehículo', exact=True)
        expect(modal).to_be_visible()
        assert len(writes) == 1
        modal.get_by_role('button', name='Revisar borrador').click()
        save.click()
        modal.get_by_role('button', name='Confirmar cambio', exact=True).click()
        done = page.get_by_role('dialog', name='Revisa la documentación del vehículo', exact=True)
        expect(done).to_be_visible()
        assert writes[1] == {'vehicle_plate': 'NEW-132', 'expected_assignment_revision': 'b' * 64}
        done.get_by_role('button', name='Cerrar', exact=True).click()
        passed('changing an owned vehicle needs an explicit central confirmation and sends only fleet deltas with the original assignment revision')
        profile.update(vehicle_ownership_type='EMPRESA', assigned_vehicle_id=vehicle, assigned_vehicle={'id': vehicle, 'revision': 'c' * 64, 'type': 'PATINETA', 'plate': 'NEW-132'})
        page.get_by_role('button', name='Recargar perfil', exact=True).click()
        expect(plate).to_be_disabled()
        expect(kind).to_be_disabled()
        name.fill('Cambio personal')
        save.click()
        expect(save).to_be_disabled()
        expect(page.get_by_text('0 cambios sin guardar', exact=True)).to_be_visible()
        expect(page.get_by_text('Perfil guardado y verificado', exact=True).last).to_be_visible()
        assert writes[2] == {'first_name': 'Cambio personal', 'expected_profile_revision': 'b' * 64}
        passed('a company vehicle stays read only and a personal edit never submits or overwrites its assignment')
        state['mode'] = 'conflict'
        name.fill('Borrador')
        save.click()
        modal = page.get_by_role('dialog', name='El perfil cambió', exact=True)
        expect(modal).to_be_visible()
        assert len(writes) == 4
        modal.get_by_role('button', name='Consultar de nuevo').click()
        review = page.get_by_role('dialog', name='Revisa el perfil actual', exact=True)
        expect(review).to_be_visible()
        expect(phone).to_have_value('+584149999999')
        review.get_by_role('button', name='Usar valores actuales').click()
        expect(name).to_have_value('Concurrente')
        expect(save).to_be_disabled()
        assert len(writes) == 4
        passed('a rejected stale revision is never automatically retried and explicit review keeps untouched fields current')
        for width in (390, 320):
            page.set_viewport_size({'width': width, 'height': 844})
            page.wait_for_function("document.querySelector('aside').getBoundingClientRect().right<=1")
            for control in (name, phone, page.get_by_role('button', name='Recargar perfil', exact=True)):
                control.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
                assert control.evaluate('e=>{const r=e.getBoundingClientRect(),t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.x>=0&&r.right<=innerWidth+1&&(t===e||e.contains(t));}')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            if width == 390:
                page.screenshot(path=str(args.artifacts_dir / 'profile-mobile.png'), full_page=True, animations='disabled')
        passed('controls remain visible and unobstructed on 320/390px with the actual dashboard sidebar')
        name.fill('No enviar')
        page.get_by_role('button', name='Recargar perfil', exact=True).click()
        modal = page.get_by_role('dialog', name='Revisar cambios sin guardar', exact=True)
        expect(modal).to_be_visible()
        modal.get_by_role('button', name='Conservar borrador').click()
        state['next_owner'] = True
        page.evaluate("() => {const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Guardar cambios');if(!b||b.disabled)throw Error('Missing save');localStorage.setItem('access_token','next-owner');localStorage.setItem('refresh_token','next-refresh');b.click();}")
        expect(save).to_be_disabled()
        assert len(writes) == 4 and (not unrelated) and (not errors)
        expect(page.get_by_text('PRIVATE_INTERNAL_VALUE', exact=True)).to_have_count(0)
        passed('dirty reload needs a decision and raw credential changes cannot submit an old private draft')
        (args.artifacts_dir / 'results.json').write_text(json.dumps({'synthetic_api': True, 'real_business_writes': False, 'checks': checks, 'sparse_puts': writes, 'unrelated_requests': unrelated, 'page_errors': errors}, indent=2))
        context.close()
        browser.close()
if __name__ == '__main__':
    main()

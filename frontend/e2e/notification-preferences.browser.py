"""Preferences delta, recovery and session scope on a synthetic local API."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:3072')
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    parser.add_argument('--artifacts-dir', required=True, type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    if urlparse(base).hostname not in ('localhost', '127.0.0.1'):
        raise ValueError('Only loopback previews are allowed')
    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    prefs = [dict(event_code='payout_aprobado', channel='EMAIL', enabled=False), dict(event_code='payout_aprobado', channel='IN_APP', enabled=False)]
    state = dict(read_failure=False, mode='lost', next_owner=False)
    writes, unrelated, errors, checks = [], [], [], []
    def passed(message):
        checks.append(message)
        print('passed:', message, flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = browser.new_context(viewport={'width':1440,'height':1200}, timezone_id='America/Caracas', service_workers='block')
        context.add_cookies([{'name':'auth-token','value':'synthetic-token','url':base}])
        context.add_init_script("localStorage.setItem('app_version','1.2.1');localStorage.setItem('access_token','synthetic-token');localStorage.setItem('refresh_token','synthetic-refresh');localStorage.setItem('user',JSON.stringify({role:'CLIENTE'}));")
        context.route_web_socket('**/*', lambda socket: None)
        def intercept(route):
            req=route.request;target=urlparse(req.url);path=target.path
            headers={'access-control-allow-origin':base,'access-control-allow-headers':'authorization,content-type','access-control-allow-methods':'GET,PUT,OPTIONS'}
            if req.method=='OPTIONS':route.fulfill(status=204,headers=headers)
            elif path.endswith(('/auth/me','/users/me')):route.fulfill(json={'id':'preferences-staff','role':'GERENTE','email':'synthetic@example.test','first_name':'Ana','last_name':'Prueba','is_active':True},headers=headers)
            elif path=='/api/v1/notifications/preferences' and req.method=='GET':
                route.fulfill(status=503 if state['read_failure'] else 200,json={'detail':'PRIVATE_INTERNAL_VALUE'} if state['read_failure'] else {'preferences':[] if state['next_owner'] else prefs},headers=headers)
            elif path=='/api/v1/notifications/templates':route.fulfill(json={'templates':[{'code':'payout_aprobado','channel':'EMAIL','is_active':True,'body_template':'PRIVATE_TEMPLATE_BODY'},{'code':'orden_cancelada','channel':'SMS','is_active':False}]},headers=headers)
            elif path=='/api/v1/notifications/preferences' and req.method=='PUT':
                rows=req.post_data_json['preferences']
                assert all(set(row)=={'event_code','channel','enabled'} and row['event_code']=='payout_aprobado' and row['channel'] in ('EMAIL','SMS') and type(row['enabled']) is bool for row in rows)
                writes.append(rows)
                for row in rows:
                    prefs[:]=[p for p in prefs if (p['event_code'],p['channel'])!=(row['event_code'],row['channel'])]+[row]
                if state['mode']=='concurrent':
                    prefs[:]=[p for p in prefs if p['channel']!='EMAIL']+[dict(event_code='payout_aprobado',channel='EMAIL',enabled=True)]
                route.fulfill(status=503 if state['mode']=='lost' else 200,json={'detail':'PRIVATE_INTERNAL_VALUE'} if state['mode']=='lost' else {'status':'ok','updated':len(rows)},headers=headers)
            elif req.method not in ('GET','OPTIONS'):
                unrelated.append({'path':path,'method':req.method});route.abort()
            elif path=='/api/v1/notifications/inbox':route.fulfill(json={'items':[],'unread_count':0},headers=headers)
            elif path.startswith('/api/') or target.netloc!=urlparse(base).netloc:route.fulfill(json={},headers=headers)
            else:route.continue_()
        context.route('**/*',intercept)
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(base+'/notifications/preferences',wait_until='domcontentloaded')
        email=page.get_by_role('checkbox',name='Retiro aprobado contablemente: Correo',exact=True)
        sms=page.get_by_role('checkbox',name='Retiro aprobado contablemente: SMS',exact=True)
        expect(email).not_to_be_checked();expect(sms).to_be_enabled()
        expect(page.get_by_role('checkbox',name='Bandeja interna',exact=True)).to_have_count(0)
        expect(page.get_by_text('PRIVATE_TEMPLATE_BODY',exact=True)).to_have_count(0)
        passed('verified role overrides obsolete user storage; historical internal values remain uneditable and template bodies are not rendered')
        page.screenshot(path=str(args.artifacts_dir/'preferences-desktop.png'),full_page=True,animations='disabled')
        email.check();sms.uncheck();page.get_by_role('button',name='Guardar cambios',exact=True).click()
        modal=page.get_by_role('dialog',name='No se pudo confirmar el guardado',exact=True)
        expect(modal).to_be_visible();assert len(writes)==1 and len(writes[0])==2 and all(row['channel']!='IN_APP' for row in writes[0])
        state['read_failure']=True;modal.get_by_role('button',name='Consultar de nuevo',exact=True).click()
        expect(modal).to_be_visible();expect(modal.get_by_role('button',name='Consultar de nuevo')).to_be_enabled()
        state['read_failure']=False;modal.get_by_role('button',name='Consultar de nuevo',exact=True).click()
        expect(modal).to_have_count(0);expect(email).to_be_checked();expect(sms).not_to_be_checked()
        expect(page.get_by_text('Estado actual verificado',exact=True)).to_be_visible()
        assert len(writes)==1 and prefs[0]['channel']=='IN_APP' and prefs[0]['enabled'] is False
        passed('one sparse PUT preserves the internal flag and a lost acknowledgement recovers by GET without repeating PUT')
        state['mode']='concurrent';email.uncheck();page.get_by_role('button',name='Guardar cambios',exact=True).click()
        modal=page.get_by_role('dialog',name='Revisa las preferencias actuales',exact=True)
        expect(modal).to_be_visible();assert len(writes)==2
        modal.get_by_role('button',name='Usar valores actuales').click();expect(email).to_be_checked()
        expect(page.get_by_role('button',name='Guardar cambios',exact=True)).to_be_disabled()
        passed('a concurrent value change is shown for review and never silently resubmitted')
        for width in (390,320):
            page.set_viewport_size({'width':width,'height':844})
            page.wait_for_function("document.querySelector('aside').getBoundingClientRect().right<=1")
            email.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
            assert email.evaluate("e=>{const r=e.getBoundingClientRect();const t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.x>=0&&r.right<=innerWidth+1&&(t===e||e.contains(t));}")
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            if width==390:page.screenshot(path=str(args.artifacts_dir/'preferences-mobile.png'),full_page=True,animations='disabled')
        passed('event controls fit and remain unobstructed at 320/390px with the real sidebar and sticky actions')
        email.uncheck();page.get_by_role('button',name='Consultar estado',exact=True).click()
        modal=page.get_by_role('dialog',name='Revisar cambios sin guardar',exact=True)
        expect(modal).to_be_visible();modal.get_by_role('button',name='Conservar borrador').click()
        state['next_owner']=True
        page.evaluate("""() => {
          const button=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Guardar cambios');
          if(!button||button.disabled)throw new Error('Missing active save');
          localStorage.setItem('access_token','synthetic-next-owner');localStorage.setItem('refresh_token','synthetic-next-refresh');button.click();
        }""")
        expect(page.get_by_role('button',name='Guardar cambios',exact=True)).to_be_disabled()
        assert len(writes)==2 and not unrelated and not errors
        expect(page.get_by_text('PRIVATE_INTERNAL_VALUE',exact=True)).to_have_count(0)
        passed('dirty refresh needs an explicit decision and raw credential changes cannot send an old draft')
        (args.artifacts_dir/'results.json').write_text(json.dumps({'synthetic_api':True,'real_business_writes':False,'checks':checks,'sparse_puts':writes,'unrelated_requests':unrelated,'page_errors':errors},indent=2))
        context.close();browser.close()


if __name__=='__main__':main()

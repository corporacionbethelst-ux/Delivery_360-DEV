"""One real sparse preference update with a lost acknowledgement in the marked lab."""
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
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium',default='/usr/bin/chromium')
    parser.add_argument('--artifacts-dir',required=True,type=Path)
    parser.add_argument('--wait-request-window',action='store_true')
    args=parser.parse_args()
    tool=Recovery();verify_target(tool)
    if args.wait_request_window:
        for _ in range(61):time.sleep(1)
    own=str(UUID(tool.source_sql("SELECT id FROM users WHERE email='admin.local-test@example.com' AND role='SUPERADMIN'")))
    other=str(UUID(tool.source_sql("SELECT id FROM users WHERE email='gerente.local-test@example.com' AND role='GERENTE'")))
    own_id,other_id=str(uuid4()),str(uuid4());event='prefs131_'+uuid4().hex[:12]
    protected=FINANCIAL_TABLES|{'notification_logs','notification_preferences'}
    before={k:v for k,v in tool.source_tables().items() if k in protected}
    assert {'notification_logs','notification_preferences'}<=before.keys()
    account=json.loads(local_test.ACCOUNTS.read_text())['SUPERADMIN']
    base='http://localhost:'+str(tool.source['web_port'])
    args.artifacts_dir.mkdir(parents=True,exist_ok=True)
    puts,rejected,errors,checks=[],[],[],[];seeded=False
    def passed(message):checks.append(message);print('passed:',message,flush=True)
    try:
        tool.source_sql("INSERT INTO notification_preferences(id,user_id,event_code,channel,enabled,created_at,updated_at) VALUES "
                        f"('{own_id}'::uuid,'{own}'::uuid,'{event}','EMAIL',false,NOW() AT TIME ZONE 'UTC',NOW() AT TIME ZONE 'UTC'),"
                        f"('{other_id}'::uuid,'{other}'::uuid,'{event}','EMAIL',true,NOW() AT TIME ZONE 'UTC',NOW() AT TIME ZONE 'UTC')")
        seeded=True
        foreign_before=tool.source_sql(f"SELECT row_to_json(p)::text FROM notification_preferences p WHERE id='{other_id}'::uuid")
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            context=browser.new_context(viewport={'width':1440,'height':1100},timezone_id='America/Caracas',service_workers='block')
            def guard(route):
                req=route.request;path=req.url.split('/api/v1',1)[-1].split('?',1)[0]
                if req.method=='PUT' and path=='/notifications/preferences':
                    changes=req.post_data_json.get('preferences')
                    expected=[{'event_code':event,'channel':'EMAIL','enabled':True}]
                    if changes!=expected or len(puts):
                        rejected.append({'method':req.method,'path':path});route.abort();return
                    puts.append(changes)
                    response=route.fetch(max_redirects=0,max_retries=0)
                    assert response.status==200 and response.json()=={'status':'ok','updated':1}
                    route.fulfill(status=503,json={'detail':'Synthetic lost acknowledgement'})
                    return
                if req.method not in ('GET','OPTIONS') and not(req.method=='POST' and path in ('/auth/login','/auth/refresh')):
                    rejected.append({'method':req.method,'path':path});route.abort();return
                route.continue_()
            context.route('**/api/v1/**',guard)
            page=context.new_page();page.on('pageerror',lambda error:errors.append('browser_exception'))
            page.goto(base+'/login',wait_until='domcontentloaded')
            page.locator('input[type=email]').fill(account['email']);page.locator('input[type=password]').fill(account['password'])
            page.get_by_role('button',name=re.compile('Iniciar sesi',re.I)).click();page.wait_for_url(base+'/manager',timeout=30000)
            page.goto(base+'/notifications/preferences',wait_until='domcontentloaded')
            card=page.get_by_role('article',name=event,exact=True)
            field=card.get_by_role('checkbox',name=event+': Correo',exact=True)
            expect(field).not_to_be_checked()
            passed('real preferences load the owner value, not the other account value for the same event/channel')
            field.check();page.get_by_role('button',name='Guardar cambios',exact=True).click()
            modal=page.get_by_role('dialog',name='No se pudo confirmar el guardado',exact=True)
            expect(modal).to_be_visible()
            assert tool.source_sql(f"SELECT enabled::text FROM notification_preferences WHERE id='{own_id}'::uuid")=='true'
            assert tool.source_sql(f"SELECT row_to_json(p)::text FROM notification_preferences p WHERE id='{other_id}'::uuid")==foreign_before
            passed('exactly one sparse PUT commits the own cell and keeps the foreign row unchanged before its reply is lost')
            page.screenshot(path=str(args.artifacts_dir/'real-preferences-lost-reply.png'),full_page=True,animations='disabled')
            modal.get_by_role('button',name='Consultar de nuevo',exact=True).click()
            expect(modal).to_have_count(0);expect(field).to_be_checked()
            expect(page.get_by_text('Estado actual verificado',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Guardar cambios',exact=True)).to_be_disabled()
            assert len(puts)==1
            passed('explicit GET recovery verifies the committed value and does not repeat PUT')
            page.set_viewport_size({'width':390,'height':844});page.wait_for_function("document.querySelector('aside').getBoundingClientRect().right<=1")
            field.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
            assert field.evaluate("e=>{const r=e.getBoundingClientRect();const t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.x>=0&&r.right<=innerWidth+1&&(t===e||e.contains(t));}")
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(args.artifacts_dir/'real-preferences-mobile.png'),full_page=True,animations='disabled')
            context.close();browser.close()
    finally:
        if seeded:tool.source_sql(f"DELETE FROM notification_preferences WHERE id IN ('{own_id}'::uuid,'{other_id}'::uuid) AND event_code='{event}'")
        after={k:v for k,v in tool.source_tables().items() if k in protected}
        assert before==after,'Original preferences, notification history or protected data changed'
    assert len(puts)==1 and not rejected and not errors
    passed('synthetic preferences removed; all original preferences, notification history and protected tables are identical')
    (args.artifacts_dir/'results.json').write_text(json.dumps({'real_api':True,'checks':checks,'sparse_puts':puts,'rejected_mutations':rejected,'page_errors':errors,'original_preferences_unchanged':True,'original_notification_history_unchanged':True,'original_protected_data_unchanged':True,'protected_tables':sorted(before)},indent=2))


if __name__=='__main__':main()

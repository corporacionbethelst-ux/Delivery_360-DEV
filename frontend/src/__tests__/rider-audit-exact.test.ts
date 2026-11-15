import { normalizeExactAuditPage, exactAuditCsv, auditExactMoney } from '@/lib/rider-audit-exact';
import { auditSummaryResponse, exactAuditEnvelope } from '../../test-fixtures/rider-audit';
const query={status:null,online:null,rider_id:null,limit:51,offset:0};
const fixture=()=>exactAuditEnvelope([auditSummaryResponse()]);
it('preserves exact strings beyond the safe integer range and formats without float conversion',()=>{
 const raw=fixture(), money=(raw.items[0] as ReturnType<typeof auditSummaryResponse>).money;
 money.credit_usd=money.net_change_usd='99999999999999999999.01';
 const page=normalizeExactAuditPage(raw,query),row=page.items[0];
 expect(auditExactMoney(row.money.credit_usd)).toBe('USD 99.999.999.999.999.999.999,01');
 expect(exactAuditCsv(page.items,{status:'ALL',online:'ALL',offset:0,search:''},page)[0]).toEqual(expect.objectContaining({creditos_usd:'99999999999999999999.01',moneda:'USD',saldo_disponible_incluido:false,verificado_por_banco:false,huella_sha256:'a'.repeat(64)}));
});
it.each([0.1,'0.1','01.00','-0.00','NaN','1e2',null])('rejects malformed exact amounts %s',value=>{
 const raw=fixture();(raw.items[0] as ReturnType<typeof auditSummaryResponse>).money.credit_usd=value as string;
 expect(()=>normalizeExactAuditPage(raw,query)).toThrow();
});
it('checks exact cent algebra and exclusions accounting',()=>{
 const raw=fixture(),m=(raw.items[0] as ReturnType<typeof auditSummaryResponse>).money;
 m.credit_usd='0.30';m.debit_usd='0.10';m.adjustment_usd='-0.03';m.net_change_usd='0.17';
 expect(normalizeExactAuditPage(raw,query).items[0].money.net_change_usd).toBe('0.17');
 m.net_change_usd='0.18';expect(()=>normalizeExactAuditPage(raw,query)).toThrow();m.net_change_usd='0.17';
 m.ledger_exclusions[0].count=1;expect(()=>normalizeExactAuditPage(raw,query)).toThrow();
});
it.each(['currency','scope','snapshot_basis','ledger_basis','payout_basis','viewer_role','generated_at','content_sha256','available_balance_included','bank_verified','wallet_cents_included'])('rejects wrong metadata %s',key=>{
 const raw:Record<string,unknown>=fixture();raw[key]='incorrect';expect(()=>normalizeExactAuditPage(raw,query)).toThrow();
});
it('rejects duplicate identities, foreign IDs and filters inconsistent with the captured query',()=>{
 const raw=fixture();raw.items.push(auditSummaryResponse());raw.total=2;expect(()=>normalizeExactAuditPage(raw,query)).toThrow();
 const other=fixture();expect(()=>normalizeExactAuditPage(other,{...query,rider_id:'other'})).toThrow();
 (other.filters as {online:boolean|null}).online=false;expect(()=>normalizeExactAuditPage(other,query)).toThrow();
});

it('exports location instants in UTC and leaves unknown location dates empty',()=>{
 for(const [input,expected] of [['2026-11-07T08:00:00-04:00','2026-11-07T12:00:00.000Z'],['2026-11-07T12:00:00','2026-11-07T12:00:00.000Z'],[null,'']] as const){
  const page=normalizeExactAuditPage(exactAuditEnvelope([auditSummaryResponse('rider-1',{last_location_at:input})]),query);
  expect(exactAuditCsv(page.items,{status:'ALL',online:'ALL',offset:0,search:''},page)[0].ubicacion_fecha_utc).toBe(expected);
 }
});

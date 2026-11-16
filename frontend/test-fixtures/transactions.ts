export const transactionResponse = (id = 'tx-1', changes: Record<string, unknown> = {}) => ({
  id, rider_id: 'rider-1', amount: 10.25, transaction_type: 'INGRESO', type: 'INGRESO', status: 'PROCESADO',
  created_at: '2026-11-07T12:00:00', updated_at: '2026-11-07T12:30:00',
  description: `Movimiento ${id}`, reference_id: `ref-${id}`, balance_before: 90, balance_after: 100.25,
  source_type: 'ORDER', source_id: 'order-1', created_by_user_id: 'actor-1', idempotency_key: null,
  ...changes,
});
export const transactionRows = (start: number, count: number, changes: Record<string, unknown> = {}) =>
  Array.from({ length: count }, (_, n) => transactionResponse(`tx-${start + n}`, changes));

// Synthetic HTTP adaptation only; the production reader never converts money via Number.
export function exactTransactionReply(value: unknown, url: string) {
 const p=new URL(url,'https://test.invalid');
 if(!p.pathname.startsWith('/financial/transactions/exact'))return value;
 if(!Array.isArray(value)&&(!value||typeof value!=='object'||!('id' in value)))return value;
 const rows=Array.isArray(value)?value:[value];
 const items=rows.map(raw=>{
  const r=raw as Record<string,unknown>,money=(v:unknown)=>v==null?null:typeof v==='string'?v:Number(v).toFixed(2);
  const time=(v:unknown)=>v==null?null:new Date(typeof v==='string'&&v.length===19?v+'Z':String(v)).toISOString().replace('Z','000Z');
  const original=r.currency??null,valid=typeof original==='string'&&/^[A-Z]{3}$/.test(original)?original:null;
  return {...r,amount:money(r.amount),balance_before:money(r.balance_before),balance_after:money(r.balance_after),currency:valid,currency_recorded:original,currency_review:original!==null&&valid===null,money_review:r.money_review??[],created_at:time(r.created_at),updated_at:time(r.updated_at),processed_at:time(r.processed_at)};
 });
 const q=p.searchParams,detail=!p.pathname.endsWith('/page');
 return{version:1,scope:'registered_financial_records',units_basis:'recorded_currency_no_conversion',balance_basis:'registered_snapshots_not_available_balance',snapshot_basis:'single_statement_visibility',available_balance_included:false,bank_verified:false,wallet_cents_included:false,customer_cashbook_included:false,viewer_user_id:'a',viewer_role:'GERENTE',generated_at:'2026-11-15T16:00:00.123456Z',content_sha256:'a'.repeat(64),filters:{transaction_id:detail?decodeURIComponent(p.pathname.split('/').at(-1)!):null,type:q.get('type'),status:q.get('status'),rider_id:q.get('rider_id'),date_from:q.has('date_from')?new Date(q.get('date_from')!).toISOString().replace('Z','000Z'):null,date_to:q.has('date_to')?new Date(q.get('date_to')!).toISOString().replace('Z','000Z'):null},limit:detail?1:Number(q.get('limit')??100),offset:detail?0:Number(q.get('offset')??0),total:items.length,items};
}

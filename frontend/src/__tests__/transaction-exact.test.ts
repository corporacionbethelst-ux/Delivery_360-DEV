import { normalizeExactTransactionPage,exactTransactionMoney,exactTransactionCsv } from '@/lib/transaction-exact';
import { prepareTransactionQuery } from '@/lib/transaction-contract';
import { transactionResponse,exactTransactionReply } from '../../test-fixtures/transactions';
const query=prepareTransactionQuery({limit:51,offset:0});
function fixture(){return exactTransactionReply([transactionResponse()],'/financial/transactions/exact/page?limit=51&offset=0') as {items:Record<string,unknown>[];[key:string]:unknown};}
it('keeps cent strings beyond Number safe range in display and CSV',()=>{
 const raw=fixture();raw.items[0].amount='99999999999999999999.01';raw.items[0].balance_after='-0.10';
 const page=normalizeExactTransactionPage(raw,query),r=page.items[0];
 expect(exactTransactionMoney(r.amount,null)).toBe('99.999.999.999.999.999.999,01 (moneda no informada)');
 expect(exactTransactionCsv(page.items,{type:'ALL',status:'ALL',offset:0,search:''},page.read_context)[0]).toEqual(expect.objectContaining({importe_registrado:'99999999999999999999.01',saldo_posterior:'-0.10',moneda:'',saldo_disponible_incluido:false}));
});
it.each([0.1,'0.1','01.00','1e2','-0.00','NaN',undefined])('rejects malformed decimal %s',value=>{const raw=fixture();raw.items[0].amount=value;expect(()=>normalizeExactTransactionPage(raw,query)).toThrow();});
it('keeps invalid recorded money visible without inventing zero and distinguishes missing balances',()=>{
 const raw=fixture();raw.items[0].amount=null;raw.items[0].balance_after=null;raw.items[0].money_review=[{field:'amount',reason:'IMPORTE_NO_VALIDO'}];
 const r=normalizeExactTransactionPage(raw,query).items[0];expect(exactTransactionMoney(r.amount,r.currency,true)).toBe('Importe por revisar');expect(exactTransactionMoney(r.balance_after,r.currency)).toBe('Monto no informado');
 raw.items[0].money_review=[];expect(()=>normalizeExactTransactionPage(raw,query)).toThrow();
});
it.each([null,'USD','VES','COP','usd',''])('preserves units without conversions (%s)',currency=>{
 const raw=exactTransactionReply([transactionResponse('tx-1',{currency})],'/financial/transactions/exact/page?limit=51&offset=0');const r=normalizeExactTransactionPage(raw,query).items[0];
 expect(r.currency_recorded).toBe(currency);expect(r.amount).toBe('10.25');expect(r.currency_review).toBe(currency!==null&&!/^[A-Z]{3}$/.test(currency));
});
it.each(['version','scope','units_basis','balance_basis','snapshot_basis','available_balance_included','bank_verified','wallet_cents_included','customer_cashbook_included','viewer_role','generated_at','content_sha256'])('rejects incorrect metadata %s',key=>{const raw=fixture();raw[key]='wrong';expect(()=>normalizeExactTransactionPage(raw,query)).toThrow();});
it('rejects changed filters, duplicate IDs, foreign detail IDs and contradictory review fields',()=>{
 let raw=fixture();expect(()=>normalizeExactTransactionPage(raw,{...query,type:'BONO'})).toThrow();raw.items.push(raw.items[0]);raw.total=2;expect(()=>normalizeExactTransactionPage(raw,query)).toThrow();
 raw=fixture();raw.items[0].money_review=[{field:'amount',reason:'IMPORTE_NO_VALIDO'}];expect(()=>normalizeExactTransactionPage(raw,query)).toThrow();
 raw=fixture();raw.items[0].currency='USD';expect(()=>normalizeExactTransactionPage(raw,query)).toThrow();
 expect(()=>normalizeExactTransactionPage(fixture(),{...query,limit:1},'wrong')).toThrow();
});
it('accepts actual zero and unknown status without deriving availability or process timestamps',()=>{
 const raw=exactTransactionReply([transactionResponse('tx-1',{amount:0,status:null,balance_before:null})],'/financial/transactions/exact/page?limit=51&offset=0');
 const r=normalizeExactTransactionPage(raw,query).items[0];expect(r.amount).toBe('0.00');expect(r.status).toBeNull();expect(r.balance_before).toBeNull();expect(r.processed_at).toBeNull();expect(r).not.toHaveProperty('available');
});

it('checks timestamp bounds without losing the recorded microseconds',()=>{
 const q=prepareTransactionQuery({limit:51,date_to:'2026-11-07T12:00:00.123Z'});
 const raw=exactTransactionReply([transactionResponse()],'/financial/transactions/exact/page?limit=51&offset=0&date_to=2026-11-07T12%3A00%3A00.123Z') as {items:Record<string,unknown>[]};
 raw.items[0].created_at='2026-11-07T12:00:00.123001Z';expect(()=>normalizeExactTransactionPage(raw,q)).toThrow();
 raw.items[0].created_at='2026-11-07T12:00:00.123000Z';expect(normalizeExactTransactionPage(raw,q).items).toHaveLength(1);
});

export const transactionResponse = (id = 'tx-1', changes: Record<string, unknown> = {}) => ({
  id, rider_id: 'rider-1', amount: 10.25, transaction_type: 'INGRESO', type: 'INGRESO', status: 'PROCESADO',
  created_at: '2026-11-07T12:00:00', updated_at: '2026-11-07T12:30:00',
  description: `Movimiento ${id}`, reference_id: `ref-${id}`, balance_before: 90, balance_after: 100.25,
  source_type: 'ORDER', source_id: 'order-1', created_by_user_id: 'actor-1', idempotency_key: null,
  ...changes,
});
export const transactionRows = (start: number, count: number, changes: Record<string, unknown> = {}) =>
  Array.from({ length: count }, (_, n) => transactionResponse(`tx-${start + n}`, changes));

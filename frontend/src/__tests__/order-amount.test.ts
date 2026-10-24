import { resolveOrderCollectAmount, OrderAmountSource } from '@/lib/order-amount';

it.each<[OrderAmountSource, number]>([
  [{ total_amount: '24.50', total: 100, delivery_fee: 5 }, 24.5],
  [{ total_amount: 0, total: '30' }, 30],
  [{ subtotal: '20', delivery_fee: '5' }, 25],
  [{ delivery_fee: 5, items: [{ quantity: 2, unit_price: 10 }] }, 25],
  [{ subtotal: 0, delivery_fee: 5, items: [{ subtotal: '20' }] }, 25],
  [{ delivery_fee: 5 }, 5],
  [{ items: [{ quantity: '3', unit_price: '2.50' }] }, 7.5],
  [{ items: [{ subtotal: 12, quantity: 100, unit_price: 100 }] }, 12],
  [{ total_amount: Infinity, total: 'NaN', subtotal: '15' }, 15],
  [{}, 0],
  [{ delivery_fee: -5 }, 0],
])('resolves the displayed order amount without dropping item costs: %j', (order, expected) => {
  expect(resolveOrderCollectAmount(order)).toBe(expected);
});

import * as finance from "@/lib/financial-utils";
import type { DeliveryPayment, PaymentTransaction } from "@/types/financial";
const payment = (changes: Partial<DeliveryPayment> = {}): DeliveryPayment => ({
  id: "local",
  deliveryId: "delivery-1",
  amount: 100,
  date: "2026-11-07T00:00:00Z",
  status: "PAGADO",
  ...changes,
});
const txn = (
  changes: Partial<PaymentTransaction> = {},
): PaymentTransaction => ({
  id: "local",
  amount: 100,
  currency: "USD",
  type: "INGRESO",
  status: "PROCESADO",
  createdAt: "2026-11-07T00:00:00Z",
  ...changes,
});
beforeEach(() => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date("2026-11-07T12:00:00Z"));
});
afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});
it.each([
  ["BRL", "R$"],
  ["USD", "$"],
  ["EUR", "€"],
] as const)("formats %s as a display amount", (currency, symbol) => {
  expect(finance.formatCurrency(0, currency)).toContain(symbol);
  expect(finance.formatCurrency(-12.5, currency)).toContain("12");
});
it("calculates a client-side estimate with and without surge/tip", () => {
  const args = {
    baseRate: 10,
    distanceKm: 3,
    durationMinutes: 5,
    perKmRate: 2,
    perMinuteRate: 1,
  };
  expect(finance.calculateDeliveryPayment(args)).toBe(21);
  expect(
    finance.calculateDeliveryPayment({ ...args, surgeMultiplier: 2, tip: 4 }),
  ).toBe(46);
});
it("keeps commission and optional bonus separate", () => {
  expect(finance.calculateRiderEarnings(100)).toBe(75);
  expect(finance.calculateRiderEarnings(100, 0, 0)).toBe(100);
  expect(finance.calculateRiderEarnings(100, 0.2, 5)).toBe(85);
});
it("handles no deliveries and separately sums tips/bonuses", () => {
  expect(finance.calculateDailyEarnings([])).toMatchObject({
    totalDeliveries: 0,
    averagePerDelivery: 0,
    netEarnings: 0,
  });
  expect(
    finance.calculateDailyEarnings([
      payment(),
      payment({ amount: 200, tip: 5, bonus: 10 }),
    ]),
  ).toMatchObject({
    totalDeliveries: 2,
    grossEarnings: 300,
    tips: 5,
    bonuses: 10,
    platformCommission: 75,
    netEarnings: 240,
    averagePerDelivery: 120,
  });
});
it("uses explicit estimated tax rates without marking an invoice as paid", () => {
  expect(finance.calculateTaxes(100)).toMatchObject({
    incomeTax: 15,
    serviceTax: 5,
    socialSecurity: 11,
    totalTaxes: 31,
    netAfterTaxes: 69,
  });
  expect(
    finance.calculateTaxes(100, {
      incomeTaxRate: 0,
      serviceTaxRate: 0,
      socialSecurityRate: 0,
    }),
  ).toMatchObject({ totalTaxes: 0, netAfterTaxes: 100 });
});
it("creates only a local PENDIENTE record with a timestamp ID", () => {
  const record = finance.processPaymentTransaction({
    amount: 100,
    type: "INGRESO",
    currency: "USD",
  });
  expect(record.status).toBe("PENDIENTE");
  expect(record.id).toMatch(/^txn_1794052800000_/);
  expect(record.id).not.toContain("function");
  expect(record.createdAt).toBe("2026-11-07T12:00:00.000Z");
});
it("keeps platform estimate fees visible and handles an empty period", () => {
  expect(finance.calculatePlatformRevenue([])).toEqual({
    totalRevenue: 0,
    totalCommission: 0,
    totalFees: 0,
    periodStart: "",
    periodEnd: "",
  });
  const result = finance.calculatePlatformRevenue(
    [payment(), payment({ amount: 200, date: "2026-11-08T00:00:00Z" })],
    0.2,
  );
  expect(result.totalCommission).toBe(60);
  expect(result.totalFees).toBeCloseTo(9.3);
  expect(result.totalRevenue).toBeCloseTo(50.7);
  expect(result.periodEnd).toBe("2026-11-08T00:00:00Z");
});
it("estimates a bounded report with signed adjustments and actual local statuses", () => {
  const rows = [
    txn(),
    txn({ amount: 20, type: "AJUSTE_MANUAL" }),
    txn({ amount: -10, type: "AJUSTE_MANUAL" }),
    txn({ amount: -5, type: "DESCUENTO" }),
    txn({ status: "PAGADO", type: "PAGO_ENTREGA", amount: 25 }),
    txn({ status: "PENDIENTE" }),
    txn({ status: "CANCELADO" }),
    txn({ status: "REEMBOLSADO" }),
    txn({ createdAt: "2020-01-01T00:00:00Z" }),
  ];
  const report = finance.generateFinancialReport(rows, {
    start: new Date("2026-11-07"),
    end: new Date("2026-11-08"),
  });
  expect(report.totalRevenue).toBe(130);
  expect(report.totalRiderPayments).toBe(145);
  expect(report.netProfit).toBe(-15);
  expect(report.metrics.averageTicket).toBe(26);
  expect(report.metrics.cancellationRate).toBe(2 / 8);
  expect(report.period.from).toEqual(new Date("2026-11-07"));
});
it("does not divide by zero for an empty report", () => {
  const report = finance.generateFinancialReport([], {
    start: new Date("2026-11-07"),
    end: new Date("2026-11-08"),
  });
  expect(report.totalRevenue).toBe(0);
  expect(report.profitMargin).toBe(0);
  expect(report.metrics.cancellationRate).toBe(0);
});
it.each([
  [1, 0, 1, 2],
  [1, 0, 3, 3],
  [4, 2, 1, 1],
  [6, 2, 1, 1.5],
  [20, 1, 1, 3],
])("bounds surge estimate for %s/%s", (orders, riders, base, expected) =>
  expect(finance.calculateSurgeMultiplier(orders, riders, base)).toBe(expected),
);
it.each([
  [NaN, false],
  [Infinity, false],
  [-Infinity, false],
  [0, false],
  [-1, false],
  [1000001, false],
  [1.234, false],
  [1.23, true],
  [1000000, true],
])("validates payment amount %s", (amount, expected) =>
  expect(finance.validatePaymentAmount(amount).isValid).toBe(expected),
);
it("splits estimated payment and computes partial refunds without a bank action", () => {
  expect(finance.splitPayment(100)).toEqual({
    riderAmount: 75,
    platformAmount: 25,
    commissionRate: 0.25,
  });
  expect(finance.splitPayment(0, 0)).toEqual({
    riderAmount: 0,
    platformAmount: 0,
    commissionRate: 0,
  });
  expect(finance.calculateRefund(100, 50)).toBe(50);
  expect(finance.calculateRefund(100, 50, 5)).toBe(45);
  expect(finance.calculateRefund(100, 0, 5)).toBe(0);
});
it.each([
  "TARJETA",
  "EFECTIVO",
  "PIX",
  "TRANSFERENCIA",
  "ONLINE",
  "credit_card",
  "debit_card",
  "cash",
  "wallet",
  "unknown",
])("labels payment method %s without replacing unknown values", (method) => {
  const result = finance.getPaymentMethodDetails(method);
  expect(result.label.length).toBeGreaterThan(0);
  if (method === "unknown")
    expect(result).toEqual({ label: "unknown", icon: "💰" });
});
it("keeps installment totals and interest explicit", () => {
  expect(finance.calculateInstallments(100, 0)).toEqual({
    installmentAmount: 0,
    totalWithInterest: 0,
    totalInterest: 0,
  });
  expect(finance.calculateInstallments(100, 2)).toEqual({
    installmentAmount: 50,
    totalWithInterest: 100,
    totalInterest: 0,
  });
  expect(
    finance.calculateInstallments(100, 2, 0.1).installmentAmount,
  ).toBeCloseTo(55);
});
it("generates local IDs using a clock value and preserves the requested prefix", () => {
  expect(finance.generateTransactionId("estimate")).toMatch(
    /^estimate_1794052800000_/,
  );
  const crypto = globalThis.crypto;
  Object.defineProperty(globalThis, "crypto", {
    value: undefined,
    configurable: true,
  });
  try {
    expect(finance.generateTransactionId()).toMatch(/^txn_1794052800000_/);
  } finally {
    Object.defineProperty(globalThis, "crypto", {
      value: crypto,
      configurable: true,
    });
  }
});
it.each(["PAGADO", "REEMBOLSADO", "CANCELADO"] as const)(
  "does not flag final payment status %s as overdue",
  (status) =>
    expect(finance.isPaymentOverdue("2020-01-01", status)).toBe(false),
);
it("distinguishes overdue pending estimates and invalid dates", () => {
  expect(finance.isPaymentOverdue("2020-01-01", "PENDIENTE")).toBe(true);
  expect(finance.isPaymentOverdue("2099-01-01", "PENDIENTE")).toBe(false);
  expect(finance.isPaymentOverdue("bad", "PENDIENTE")).toBe(false);
  expect(finance.daysUntilDue("2026-11-08T12:00:00Z")).toBe(1);
  expect(finance.daysUntilDue("2026-11-06T12:00:00Z")).toBe(-1);
  expect(Number.isNaN(finance.daysUntilDue("bad"))).toBe(true);
});

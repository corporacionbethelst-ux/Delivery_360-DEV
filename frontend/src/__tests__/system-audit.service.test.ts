import { api } from "@/lib/api";
import {
  auditService,
  type AuditFilters,
  type AuditLog,
} from "@/services/audit.service";
import {
  AUDIT_CSV_HEADER,
  auditDraftFilters,
  auditEventTime,
  auditQuery,
  auditTime,
  emptyAuditDraft,
  validateAuditLog,
  validateAuditPage,
  validateAuditSummary,
} from "@/lib/system-audit";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get),
  id = "123e4567-e89b-42d3-a456-000000000083";
const row: AuditLog = {
  id,
  action: "UPDATE",
  status: "SUCCESS",
  success: true,
  user_id: id,
  user_role: "GERENTE",
  created_at: "2026-11-09T12:00:00",
};
const page = { items: [row], total: 1, limit: 50, offset: 0 };
const summary = {
  total: 1,
  period_days: 7,
  period_start: "2026-11-02T12:00:00",
  by_action: { UPDATE: 1 },
  by_success: { True: 1 },
};
beforeEach(() => {
  jest.resetAllMocks();
});
afterEach(() => {
  clearStoredTokens();
});

it("keeps frozen filters intact and serializes false-free explicit pagination and trimmed filters", async () => {
  const filters = Object.freeze({
    limit: 50,
    offset: 100050,
    action: " UPDATE ",
    status: "SUCCESS" as const,
    resource_type: " User ",
    resource_id: "a/b?x=1",
    user_id: id,
    search: " José & IP ",
  });
  get.mockResolvedValue({ ...page, total: 100051, offset: 100050 });
  await auditService.getLogs(filters);
  const query = new URLSearchParams(String(get.mock.calls[0][0]).split("?")[1]);
  expect(Object.fromEntries(query)).toEqual({
    limit: "50",
    offset: "100050",
    action: "UPDATE",
    status: "SUCCESS",
    resource_type: "User",
    resource_id: "a/b?x=1",
    user_id: id,
    search: "José & IP",
  });
  expect(filters.search).toBe(" José & IP ");
});
it.each([NaN, Infinity, -1, 0, 501, 1.5])(
  "rejects invalid list limit %s without HTTP",
  async (limit) => {
    await expect(auditService.getLogs({ limit })).rejects.toThrow();
    expect(get).not.toHaveBeenCalled();
  },
);
it.each([NaN, Infinity, -1, 1.5])(
  "rejects invalid offset %s without HTTP",
  async (offset) => {
    await expect(auditService.getLogs({ offset })).rejects.toThrow();
    expect(get).not.toHaveBeenCalled();
  },
);
it.each([
  { action: "CUSTOM" },
  { status: "CUSTOM" },
  { user_id: "not-a-uuid" },
  { date_from: "2026-02-30" },
  { date_to: "invalid" },
  { date_from: "2026-11-10", date_to: "2026-11-09" },
])("rejects invalid query %j without HTTP", async (filters) => {
  await expect(auditService.getLogs(filters as AuditFilters)).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
});
it("normalizes explicit timezone offsets to UTC before the API drops timezone markers", () => {
  expect(
    new URLSearchParams(
      auditQuery({ date_from: "2026-11-09T00:00:00-04:00" }).slice(1),
    ).get("date_from"),
  ).toBe("2026-11-09T04:00:00.000Z");
});
it("converts entire Caracas days including the last millisecond of the end date", () => {
  expect(
    auditDraftFilters({
      ...emptyAuditDraft,
      date_from: "2026-11-09",
      date_to: "2026-11-09",
      search: " ALL ",
    }),
  ).toEqual({
    limit: 50,
    offset: 0,
    search: "ALL",
    date_from: "2026-11-09T04:00:00.000Z",
    date_to: "2026-11-10T03:59:59.999Z",
  });
});
it("uses the actual historical Caracas offset instead of hardcoding UTC-4", () => {
  expect(
    auditDraftFilters({
      ...emptyAuditDraft,
      date_from: "2008-11-09",
      date_to: "2008-11-09",
    }),
  ).toEqual({
    limit: 50,
    offset: 0,
    date_from: "2008-11-09T04:30:00.000Z",
    date_to: "2008-11-10T04:29:59.999Z",
  });
});
it.each([
  null,
  [],
  {},
  { ...page, total: -1 },
  { ...page, total: 0 },
  { ...page, limit: 51 },
  { ...page, offset: 50 },
  { ...page, items: [row, row], total: 2 },
  { ...page, items: [{ ...row, id: "" }] },
  { ...page, items: [{ ...row, success: null }] },
  { ...page, items: [{ ...row, user_email: {} }] },
  { ...page, items: [{ ...row, old_values: [] }] },
])(
  "rejects malformed page %j instead of inventing an empty result",
  async (value) => {
    get.mockResolvedValue(value);
    await expect(auditService.getLogs()).rejects.toThrow();
  },
);
it("rejects list records that disagree with the action or result filters", () => {
  expect(() => validateAuditPage(page, { status: "FAILURE" })).toThrow();
  expect(() => validateAuditPage(page, { action: "LOGIN" })).toThrow();
});
it("accepts a confirmed empty page beyond a shrunken total", () => {
  expect(
    validateAuditPage(
      { items: [], total: 10, limit: 50, offset: 50 },
      { offset: 50 },
    ),
  ).toEqual({ items: [], total: 10, limit: 50, offset: 50 });
});
it("preserves unknown statuses/actions and missing or invalid dates without SUCCESS defaults", () => {
  const value = {
    ...row,
    action: "FUTURE",
    status: "__proto__",
    created_at: "invalid",
    user_id: null,
    user_role: null,
    status_code: 0,
  };
  expect(validateAuditLog(value)).toEqual(value);
  expect(auditEventTime(value)).toBe("Fecha no disponible");
});
it.each([
  { ...row, status_code: -1 },
  { ...row, status_code: 1.5 },
  { ...row, contains_personal_data: "false" },
])("rejects invalid record fields %j", (value) => {
  expect(() => validateAuditLog(value)).toThrow();
});
it("prefers explicit event UTC, falls back to legacy UTC and uses absolute Caracas dates", () => {
  expect(
    auditEventTime({
      ...row,
      new_values: { occurred_at_utc: "2026-11-09T13:00:00Z" },
    }),
  ).toBe(auditTime("2026-11-09T13:00:00Z"));
  expect(
    auditEventTime({ ...row, new_values: { occurred_at_utc: "invalid" } }),
  ).toBe(auditTime("2026-11-09T12:00:00Z"));
  expect(auditTime("2099-11-09T12:00:00Z")).toContain("2099");
});
it("validates an independent summary and preserves explicit zero success", async () => {
  get.mockResolvedValue({ ...summary, by_success: { True: 0, False: 1 } });
  expect((await auditService.getSummary()).by_success.True).toBe(0);
  expect(get).toHaveBeenCalledWith("/audit/summary?days=7");
});
it.each([0, -1, 366, 1.5, NaN])(
  "rejects summary period %s without HTTP",
  async (days) => {
    await expect(auditService.getSummary(days)).rejects.toThrow();
    expect(get).not.toHaveBeenCalled();
  },
);
it.each([
  { ...summary, period_days: 30 },
  { ...summary, total: -1 },
  { ...summary, by_action: { UPDATE: 2 } },
  { ...summary, by_success: { True: "1" } },
  { ...summary, period_start: "invalid" },
  { ...summary, by_action: [] },
])("rejects incoherent summary %j", (value) => {
  expect(() => validateAuditSummary(value, 7)).toThrow();
});
it("encodes the complete detail ID and verifies the response identity", async () => {
  const identity = "a/b?x=1";
  get.mockResolvedValue({ ...row, id: identity });
  await auditService.getById(identity);
  expect(get).toHaveBeenCalledWith("/audit/a%2Fb%3Fx%3D1");
  get.mockResolvedValue(row);
  await expect(auditService.getById(identity)).rejects.toThrow(
    "no corresponde",
  );
});
it("rejects missing detail identity before HTTP", async () => {
  await expect(auditService.getById(" ")).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
});
it("exports filters across all pages with no offset and preserves the server CSV", async () => {
  const csv = AUDIT_CSV_HEADER + "\r\n";
  get.mockResolvedValue(csv);
  expect(
    await auditService.exportCsv({
      offset: 50,
      limit: 5000,
      status: "FAILURE",
      search: "x&y",
    }),
  ).toBe(csv);
  expect(get).toHaveBeenCalledWith(
    "/audit/export?limit=5000&status=FAILURE&search=x%26y",
    { responseType: "text" },
  );
});
it.each([
  null,
  {},
  "<html>Forbidden</html>",
  '{"error":"bad"}',
  "wrong,columns\r\n",
])("rejects a non-CSV download %j", async (value) => {
  get.mockResolvedValue(value);
  await expect(auditService.exportCsv()).rejects.toThrow();
});
it("accepts a BOM header-only CSV and rejects an export above the real limit", async () => {
  const csv = "\uFEFF" + AUDIT_CSV_HEADER + "\r\n";
  get.mockResolvedValue(csv);
  expect(await auditService.exportCsv()).toBe(csv);
  get.mockClear();
  await expect(auditService.exportCsv({ limit: 5001 })).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
});
it.each(["list", "summary", "detail", "export"])(
  "retires a %s response when credentials change",
  async (operation) => {
    let resolve!: (value: unknown) => void;
    get.mockReturnValue(
      new Promise((yes) => {
        resolve = yes;
      }),
    );
    const request =
      operation === "list"
        ? auditService.getLogs()
        : operation === "summary"
          ? auditService.getSummary()
          : operation === "detail"
            ? auditService.getById(id)
            : auditService.exportCsv();
    storeTokens({
      access_token: "another-session",
      refresh_token: "another-refresh",
    });
    resolve(
      operation === "list"
        ? page
        : operation === "summary"
          ? summary
          : operation === "detail"
            ? row
            : AUDIT_CSV_HEADER + "\n",
    );
    await expect(request).rejects.toThrow("sesión cambió");
  },
);

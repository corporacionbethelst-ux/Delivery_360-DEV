import { AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import client from "@/lib/api";
import { exactPayoutService } from "@/services/payout-exact.service";
import {
  clearStoredTokens,
  storeTokens,
  SessionChangedError,
} from "@/lib/auth-session";
import { payoutEnvelope } from "../../test-fixtures/payout-exact";
const original = client.defaults.adapter;
const reply = (config: InternalAxiosRequestConfig, data: unknown) => ({
  config,
  data,
  status: 200,
  statusText: "OK",
  headers: new AxiosHeaders(),
});
beforeEach(() => {
  clearStoredTokens();
  storeTokens({ access_token: "access-a", refresh_token: "refresh-a" });
});
afterEach(() => {
  clearStoredTokens();
  client.defaults.adapter = original;
});
it("requests parent and complete history in exactly one authorized GET", async () => {
  const requests: string[] = [];
  client.defaults.adapter = async (config) => {
    requests.push(String(config.url));
    expect(config.method).toBe("get");
    expect(config.headers.get("Authorization")).toBe("Bearer access-a");
    return reply(
      config,
      payoutEnvelope(
        {
          items: [{ id: "p", currency: "USD", amount: 0.1 }],
          next_cursor: null,
        },
        String(config.url),
      ),
    );
  };
  const result = await exactPayoutService.getDetail("p", "STAFF");
  expect(requests).toEqual(["/payouts/exact/p?audience=STAFF"]);
  expect(result.payout.amount).toBe("0.10");
  expect(result.history).toEqual([]);
});
it("uses the original cursor opaquely with explicit owner audience and no offset", async () => {
  const token = "position." + "a".repeat(64);
  let requested = "";
  client.defaults.adapter = async (config) => {
    requested = String(config.url);
    return reply(
      config,
      payoutEnvelope({ items: [], next_cursor: null }, requested),
    );
  };
  const input = {
    audience: "OWNER" as const,
    status: "COMPLETADO" as "COMPLETADO" | "PENDIENTE",
    limit: 50,
    cursor: token,
  };
  const promise = exactPayoutService.getPage(input);
  input.status = "PENDIENTE";
  await promise;
  const q = new URL(requested, "https://test.invalid").searchParams;
  expect(Object.fromEntries(q)).toEqual({
    audience: "OWNER",
    status: "COMPLETADO",
    limit: "50",
    cursor: token,
  });
});
it.each(["page", "detail"])(
  "fences %s after an accepted Axios response but before publication",
  async (kind) => {
    client.defaults.adapter = async (config) =>
      reply(
        config,
        payoutEnvelope(
          { items: [{ id: "p" }], next_cursor: null },
          String(config.url),
        ),
      );
    const hook = client.interceptors.response.use((response) => {
      storeTokens({ access_token: "access-b", refresh_token: "refresh-b" });
      return response;
    });
    try {
      await expect(
        kind === "page"
          ? exactPayoutService.getPage({ audience: "STAFF" })
          : exactPayoutService.getDetail("p", "STAFF"),
      ).rejects.toBeInstanceOf(SessionChangedError);
    } finally {
      client.interceptors.response.eject(hook);
    }
  },
);
it("rejects an incomplete history envelope rather than making an unscoped fallback request", async () => {
  const calls: string[] = [];
  client.defaults.adapter = async (config) => {
    calls.push(String(config.url));
    const p = payoutEnvelope(
      { items: [{ id: "p" }], next_cursor: null },
      String(config.url),
    );
    p.history_complete = false;
    return reply(config, p);
  };
  await expect(exactPayoutService.getDetail("p", "STAFF")).rejects.toThrow();
  expect(calls).toHaveLength(1);
});

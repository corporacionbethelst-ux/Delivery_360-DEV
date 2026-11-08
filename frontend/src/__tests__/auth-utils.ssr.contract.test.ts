/** @jest-environment node */
import * as auth from "@/lib/auth";
it("does not touch browser storage, events or token claims during SSR", async () => {
  expect(() =>
    auth.saveTokens({
      access_token: "a",
      refresh_token: "r",
      token_type: "bearer",
    }),
  ).not.toThrow();
  expect(auth.getTokens()).toBeNull();
  auth.clearTokens();
  expect(auth.decodeToken("a.b.c")).toBeNull();
  expect(auth.getCurrentUser()).toBeNull();
  expect(auth.isSessionActive()).toBe(false);
  expect(auth.setupAuthListeners({})()).toBeUndefined();
  expect(() => auth.logout()).not.toThrow();
  await expect(auth.hashPassword("local-only")).rejects.toThrow("Crypto API");
});

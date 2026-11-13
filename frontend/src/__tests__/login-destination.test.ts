import { getLoginDestination } from "@/lib/login-destination";

it.each([
  ["SUPERADMIN", "/manager"],
  ["GERENTE", "/manager"],
  ["OPERADOR", "/operator"],
  ["REPARTIDOR", "/rider"],
])("lands %s in its working area without a callback", (role, home) => {
  expect(getLoginDestination(role)).toBe(home);
});

it.each([
  ["OPERADOR", "/operator/orders?status=PENDIENTE"],
  ["REPARTIDOR", "/rider/deliveries"],
  ["GERENTE", "/manager/admin/settings#tarifas"],
  ["SUPERADMIN", "/manager"],
  ["OPERADOR", "/manager/orders"],
])("preserves an allowed local destination for %s", (role, destination) => {
  expect(getLoginDestination(role, destination)).toBe(destination);
});

it.each([
  "/manager",
  "/operator",
  "/rider-other",
  "/rider/../manager",
  "/rider/%2e%2e/manager",
  "//external.example/rider",
  "https://external.example/rider",
  "/\\external.example/rider",
  "javascript:alert(1)",
  "",
])("rejects a destination outside the rider area: %s", (destination) => {
  expect(getLoginDestination("REPARTIDOR", destination)).toBe("/rider");
});

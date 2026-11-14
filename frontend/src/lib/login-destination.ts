/** Choose a local landing page. API authorization remains authoritative. */
export function getLoginDestination(
  role: string,
  callback: string | null = null,
): string {
  const home =
    role === "REPARTIDOR"
      ? "/rider"
      : role === "OPERADOR"
        ? "/operator"
        : "/manager";
  const sections =
    role === "REPARTIDOR"
      ? ["/rider"]
      : ["SUPERADMIN", "GERENTE", "OPERADOR"].includes(role)
        ? ["/manager", "/operator"]
        : [];
  if (!callback?.startsWith("/") || callback.startsWith("//")) return home;
  try {
    const base = new URL("https://delivery360.invalid");
    const target = new URL(callback, base);
    if (
      target.origin !== base.origin ||
      !sections.some(
        (section) =>
          target.pathname === section ||
          target.pathname.startsWith(section + "/"),
      )
    )
      return home;
    return target.pathname + target.search + target.hash;
  } catch {
    return home;
  }
}

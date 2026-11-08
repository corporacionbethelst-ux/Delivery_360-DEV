/** Read supported API error envelopes without exposing request headers or bodies. */
export function apiDetail(data: unknown): string | undefined {
  if (!data || typeof data !== "object") return undefined;
  const value = data as Record<string, unknown>;
  if (typeof value.detail === "string") return value.detail;
  if (
    value.detail &&
    typeof value.detail === "object" &&
    !Array.isArray(value.detail) &&
    "message" in value.detail &&
    typeof value.detail.message === "string"
  )
    return value.detail.message;
  const fields = (rows: unknown[]) =>
    rows
      .filter(
        (item): item is Record<string, unknown> =>
          !!item && typeof item === "object",
      )
      .map((item) => {
        const field = Array.isArray(item.loc)
          ? item.loc.join(".")
          : typeof item.field === "string"
            ? item.field
            : "campo";
        const message =
          typeof item.msg === "string"
            ? item.msg
            : typeof item.message === "string"
              ? item.message
              : "inválido";
        return `${field}: ${message}`;
      })
      .join("; ");
  if (Array.isArray(value.detail)) return fields(value.detail) || undefined;
  if (typeof value.message === "string") {
    const details = Array.isArray(value.details) ? fields(value.details) : "";
    return details ? `${value.message}: ${details}` : value.message;
  }
  return undefined;
}

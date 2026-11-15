import { record } from "@/lib/operational-catalog";
import {
  normalizeAuditOperational,
  auditId,
  AUDIT_PAGE_SIZE,
} from "@/lib/rider-audit-contract";
import { cashCents, cashText } from "@/lib/customer-cashbook";
import {
  prepareAuditCatalogQuery,
  type AuditCatalogQuery,
} from "@/lib/rider-audit-catalog";
export { cashText as auditExactMoney };
const ledgerReasons = [
  "FECHA_NO_REGISTRADA",
  "MONEDA_NO_VERIFICADA",
  "FECHA_FUTURA",
  "ESTADO_NO_PROCESADO",
  "TIPO_NO_ADMITIDO",
];
const payoutReasons = [
  "FECHA_NO_REGISTRADA",
  "MONEDA_NO_VERIFICADA",
  "FECHA_FUTURA",
  "ESTADO_NO_PENDIENTE",
];
const fail = (): never => {
  throw new Error(
    "No se pudieron confirmar los totales USD exactos de auditoría. Vuelve a consultar.",
  );
};
const count = (v: unknown) =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : fail();
function moneyRow(value: unknown) {
  const m = record(value),
    credit = cashCents(m.credit_usd),
    debit = cashCents(m.debit_usd),
    adjustment = cashCents(m.adjustment_usd, true),
    net = cashCents(m.net_change_usd, true);
  cashCents(m.pending_usd);
  if (credit - debit + adjustment !== net) fail();
  const groups: Record<string, { reason: string; count: number }[]> = {};
  for (const [prefix, reasons] of [
    ["ledger", ledgerReasons],
    ["payout", payoutReasons],
  ] as const) {
    const raw = m[prefix + "_exclusions"];
    if (!Array.isArray(raw) || raw.length !== reasons.length) fail();
    const entries = (raw as unknown[]).map((v, i) => {
      const r = record(v);
      if (r.reason !== reasons[i]) fail();
      return { reason: reasons[i], count: count(r.count) };
    });
    const rows = count(m[prefix + "_rows"]),
      included = count(m[prefix + "_included"]);
    if (entries.reduce((n, r) => n + r.count, 0) + included !== rows) fail();
    groups[prefix] = entries;
  }
  if (
    m.ledger_included === 0 &&
    (credit !== BigInt(0) ||
      debit !== BigInt(0) ||
      adjustment !== BigInt(0) ||
      net !== BigInt(0))
  )
    fail();
  if (m.payout_included === 0 && cashCents(m.pending_usd) !== BigInt(0)) fail();
  return {
    credit_usd: m.credit_usd as string,
    debit_usd: m.debit_usd as string,
    adjustment_usd: m.adjustment_usd as string,
    net_change_usd: m.net_change_usd as string,
    pending_usd: m.pending_usd as string,
    ledger_rows: count(m.ledger_rows),
    ledger_included: count(m.ledger_included),
    payout_rows: count(m.payout_rows),
    payout_included: count(m.payout_included),
    ledger_exclusions: groups.ledger,
    payout_exclusions: groups.payout,
  };
}
export function normalizeExactAuditPage(
  value: unknown,
  query: {
    status: string | null;
    online: boolean | null;
    rider_id: string | null;
    limit: number;
    offset: number;
  },
) {
  const p = record(value);
  if (
    p.version !== 1 ||
    p.scope !== "operational_rider_audit_usd" ||
    p.currency !== "USD" ||
    p.snapshot_basis !== "single_statement_visibility" ||
    p.ledger_basis !== "processed_registered_movements" ||
    p.payout_basis !== "current_pending_requests" ||
    p.available_balance_included !== false ||
    p.bank_verified !== false ||
    p.wallet_cents_included !== false ||
    !["SUPERADMIN", "GERENTE"].includes(String(p.viewer_role))
  )
    return fail();
  auditId(p.viewer_user_id);
  if (
    typeof p.generated_at !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(p.generated_at) ||
    !Number.isFinite(Date.parse(p.generated_at)) ||
    new Date(p.generated_at).toISOString().slice(0, 10) !==
      p.generated_at.slice(0, 10) ||
    typeof p.content_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(p.content_sha256)
  )
    return fail();
  const f = record(p.filters);
  for (const key of ["status", "online", "rider_id"] as const)
    if (f[key] !== query[key]) return fail();
  if (
    p.limit !== query.limit ||
    p.offset !== query.offset ||
    !Array.isArray(p.items) ||
    p.items.length > query.limit ||
    p.total !== p.items.length
  )
    return fail();
  const riders = new Set<string>(),
    users = new Set<string>();
  const items = (p.items as unknown[]).map((value) => {
    const row = record(value),
      ops = normalizeAuditOperational(row);
    if (
      riders.has(ops.rider_id) ||
      users.has(ops.user_id) ||
      (query.rider_id !== null && ops.rider_id !== query.rider_id) ||
      (query.status !== null && ops.status !== query.status) ||
      (query.online !== null && ops.is_online !== query.online)
    )
      return fail();
    riders.add(ops.rider_id);
    users.add(ops.user_id);
    return { ...ops, money: moneyRow(row.money) };
  });
  return {
    items,
    generated_at: p.generated_at,
    content_sha256: p.content_sha256,
    viewer_user_id: p.viewer_user_id as string,
    viewer_role: p.viewer_role as string,
  };
}
export type ExactAuditSummary = ReturnType<
  typeof normalizeExactAuditPage
>["items"][number];
export function normalizeExactAuditCatalog(
  value: unknown,
  input: Readonly<AuditCatalogQuery>,
) {
  const query = prepareAuditCatalogQuery(input),
    page = normalizeExactAuditPage(value, {
      status: query.status === "ALL" ? null : query.status,
      online: query.online === "ALL" ? null : query.online === "true",
      rider_id: null,
      limit: AUDIT_PAGE_SIZE + 1,
      offset: query.offset,
    });
  return {
    ...page,
    query,
    rows: page.items.slice(0, AUDIT_PAGE_SIZE),
    hasNext: page.items.length > AUDIT_PAGE_SIZE,
  };
}
export type ExactAuditCatalogSnapshot = ReturnType<
  typeof normalizeExactAuditCatalog
>;
export function exactAuditCsv(
  rows: ExactAuditSummary[],
  context: AuditCatalogQuery & { search: string },
  snapshot: Pick<
    ExactAuditCatalogSnapshot,
    "generated_at" | "content_sha256" | "viewer_user_id"
  >,
) {
  return rows.map((r) => ({
    id_rider: r.rider_id,
    id_usuario: r.user_id,
    nombre: r.full_name ?? "",
    email: r.email ?? "",
    telefono: r.phone ?? "",
    estado: r.status ?? "",
    online: r.is_online,
    tipo_vehiculo: r.vehicle_type ?? "",
    placa: r.vehicle_plate ?? "",
    zona: r.operating_zone ?? "",
    id_zona: r.zone_id ?? "",
    id_orden_actual: r.current_order_id ?? "",
    latitud: r.last_lat,
    longitud: r.last_lng,
    ubicacion_fecha_utc: r.last_location_at
      ? new Date(r.last_location_at).toISOString()
      : "",
    ordenes_asignadas: r.orders_assigned,
    ordenes_entregadas: r.orders_delivered,
    ordenes_activas: r.orders_active,
    entregas_total: r.deliveries_total,
    entregas_completadas: r.deliveries_completed,
    entregas_fallidas: r.deliveries_failed,
    entregas_en_curso: r.deliveries_in_progress,
    sla_cumplidas: r.sla_compliant,
    sla_denominador: r.deliveries_total,
    sla_porcentaje_informado: r.sla_compliance_rate,
    creditos_usd: r.money.credit_usd,
    debitos_usd: r.money.debit_usd,
    ajustes_usd: r.money.adjustment_usd,
    cambio_neto_usd: r.money.net_change_usd,
    solicitudes_pendientes_usd: r.money.pending_usd,
    movimientos_incluidos: r.money.ledger_included,
    movimientos_excluidos: r.money.ledger_rows - r.money.ledger_included,
    solicitudes_incluidas: r.money.payout_included,
    solicitudes_excluidas: r.money.payout_rows - r.money.payout_included,
    exclusiones_movimientos: JSON.stringify(r.money.ledger_exclusions),
    exclusiones_solicitudes: JSON.stringify(r.money.payout_exclusions),
    moneda: "USD",
    corte_utc: snapshot.generated_at,
    huella_sha256: snapshot.content_sha256,
    consultado_por: snapshot.viewer_user_id,
    saldo_disponible_incluido: false,
    verificado_por_banco: false,
    filtro_estado: context.status,
    filtro_online: context.online,
    desplazamiento_consulta: context.offset,
    busqueda_local: context.search,
    alcance:
      "Solo coincidencias de la página cargada; no es el catálogo completo",
  }));
}

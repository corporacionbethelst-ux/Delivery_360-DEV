import { pricing, orderId, orderReceipt } from "./order-currency-fixtures";
import { actorId, nextId } from "./currency-fixtures";
import type {
  CollectionContext,
  CustomerCollection,
  CollectionInput,
  CollectionReviewInput,
} from "@/lib/customer-collections";
export const reviewerId = "88888888-8888-4888-8888-888888888888";
export const declaration: CollectionInput = {
  request_key: nextId,
  expected_pricing_revision: 1,
  expected_collection_revision: 0,
  amount_usd: "0.20",
  paid_amount: "0.20",
  paid_currency: "USD",
  method: "EFECTIVO",
  source_key: "CAJA",
  reference_key: "RECIBO-94",
  received_on: "2026-11-14",
  quote_id: null,
  confirmed_received: true,
};
export const collection: CustomerCollection = {
  id: "77777777-7777-4777-8777-777777777777",
  request_key: nextId,
  order_id: orderId,
  pricing,
  amount_usd: "0.20",
  paid_amount: "0.20",
  paid_currency: "USD",
  method: "EFECTIVO",
  source_key: "CAJA",
  reference_key: "RECIBO-94",
  received_on: "2026-11-14",
  declared_by: actorId,
  created_at: "2026-11-14T16:02:00Z",
  quote: null,
  review: null,
  status: "PENDIENTE",
  scope: "manual_customer_collections",
  bank_verified: false,
};
export const collectionContext: CollectionContext = {
  order_id: orderId,
  pricing,
  order_status: "PENDIENTE",
  currency: "USD",
  collection_revision: 0,
  price_locked: false,
  today: "2026-11-14",
  summary: {
    currency: "USD",
    total_usd: "0.50",
    pending_usd: "0.00",
    verified_usd: "0.00",
    due_usd: "0.50",
    available_to_declare_usd: "0.50",
    refund_due_usd: "0.00",
    state: "SIN_COBROS",
    declaration_count: 0,
    review_count: 0,
  },
  collections: [],
  has_more: false,
  ves_quotes: [orderReceipt],
  scope: "manual_customer_collections",
  bank_integration_available: false,
};
export const pendingContext: CollectionContext = {
  ...collectionContext,
  collection_revision: 1,
  price_locked: true,
  summary: {
    ...collectionContext.summary,
    pending_usd: "0.20",
    available_to_declare_usd: "0.30",
    state: "EN_REVISION",
    declaration_count: 1,
  },
  collections: [collection],
};
export const reviewCommand: CollectionReviewInput = {
  request_key: nextId,
  expected_collection_revision: 1,
  decision: "VERIFICADO",
  note: "Ingreso comprobado con el recibo",
  verified_evidence: true,
  acknowledge_refund_due: false,
};
export const reviewed: CustomerCollection = {
  ...collection,
  status: "VERIFICADO_MANUALMENTE",
  review: {
    ...reviewCommand,
    id: "99999999-9999-4999-8999-999999999999",
    collection_id: collection.id,
    reviewed_by: reviewerId,
    reviewed_at: "2026-11-14T16:03:00Z",
  },
};

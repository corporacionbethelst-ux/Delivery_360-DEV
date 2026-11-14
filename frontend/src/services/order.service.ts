import {
  preparePricePayload,
  type ExactOrderPricing,
  type DecimalInput,
} from "@/lib/order-pricing";
import { capturePrivateTask } from "@/lib/private-task";
import {
  readOrderCatalog,
  validateHttpOrder,
  record,
  identifier,
} from "@/lib/operational-catalog";
import { orderAssignmentPatch } from "@/lib/order-assignment";
import { api } from "@/lib/api";
import { isCancellationReasonValid } from "@/lib/delivery-status";
import { User } from "@/types/user";
import type { AxiosError } from "axios";

export type OrderStatus =
  | "PENDIENTE"
  | "ASIGNADO"
  | "EN_RECOLECCION"
  | "RECOLECTADO"
  | "EN_RUTA"
  | "ENTREGADO"
  | "FALLIDO"
  | "CANCELADO";

export type PriorityLevel = "NORMAL" | "ALTA" | "URGENTE";

export interface OrderItem {
  id?: string;
  product_id?: string;
  product_name: string;
  quantity: number;
  unit_price: number;
  subtotal?: number;
}

export interface OrderRiderSummary {
  id: string;
  first_name?: string;
  last_name?: string;
  full_name?: string;
  email?: string | null;
  phone?: string | null;
  vehicle_type?: string | null;
  vehicle_plate?: string | null;
  status?: string | null;
  is_online?: boolean;
  last_location_at?: string | null;
}

export interface DeliverySummary {
  id: string;
  order_id: string;
  rider_id?: string | null;
  status: string;
  started_at?: string | null;
  arrived_pickup_at?: string | null;
  left_pickup_at?: string | null;
  arrived_delivery_at?: string | null;
  completed_at?: string | null;
  sla_expected_minutes?: number | null;
  sla_actual_minutes?: number | null;
  sla_compliant?: boolean | null;
}

export interface Order {
  pricing?: ExactOrderPricing | null;
  currency?: string | null;
  id: string;
  external_id: string;

  // Datos del Cliente
  customer_id?: string;
  customer_name?: string;
  customer_phone?: string;
  customer_email?: string;

  // Datos del Restaurante/Pickup
  restaurant_id?: string;
  pickup_address?: string;
  pickup_name?: string;
  pickup_phone?: string;

  // Datos de Entrega
  delivery_address: string;
  delivery_reference?: string;
  delivery_instructions?: string;
  delivery_contact?: string;

  // Coordenadas
  pickup_lat?: number | null;
  pickup_lng?: number | null;
  delivery_lat?: number | null;
  delivery_lng?: number | null;

  // Estado y Asignación
  status: OrderStatus;
  priority: PriorityLevel;
  assigned_rider_id?: string | null;
  rider_id?: string | null;

  // Información Financiera (Soporte dual para total/total_amount)
  subtotal?: number;
  delivery_fee?: number;
  total?: number;
  total_amount?: number;
  payment_method?: string;
  payment_status?: string;

  // Tiempos y SLA
  ordered_at?: string;
  accepted_at?: string;
  picked_up_at?: string;
  delivered_at?: string | null;
  estimated_delivery_time?: string;
  sla_deadline?: string;

  // Fallos y Cancelaciones
  failure_reason?: string;
  failure_notes?: string;
  cancelled_by?: string;
  cancellation_reason?: string;

  // Metadata
  notes?: string;
  source?: string;
  integration_id?: string;
  items: OrderItem[];

  // Relaciones
  customer?: User;
  rider?: OrderRiderSummary | User | null;
  delivery?: DeliverySummary | null; // NUEVO: Datos de la entrega

  // Auditoría
  created_at: string;
  updated_at?: string;
}

export interface OrderCreateInput {
  currency?: "USD";
  sla_minutes?: number;
  customer_id?: string;
  customer_name?: string;
  customer_phone?: string;
  customer_email?: string;
  restaurant_id?: string;
  external_id?: string;

  pickup_address: string;
  pickup_name?: string;
  pickup_contact?: string;
  pickup_phone?: string;

  delivery_address: string;
  delivery_reference?: string;
  delivery_instructions?: string;
  delivery_contact?: string;

  items: {
    product_id?: string;
    product_name: string;
    quantity: DecimalInput;
    unit_price: DecimalInput;
    subtotal?: DecimalInput;
  }[];

  pickup_lat?: number | null;
  pickup_lng?: number | null;
  delivery_lat?: number | null;
  delivery_lng?: number | null;

  subtotal?: DecimalInput;
  delivery_fee?: DecimalInput;
  total?: DecimalInput;
  declared_value?: DecimalInput;

  payment_method?: string;
  priority?: PriorityLevel;
  status?: OrderStatus;
  notes?: string;
}

export type OrderUpdateInput = Partial<OrderCreateInput> & {
  expected_pricing_revision?: number | null;
};

export interface OrderListParams {
  status?: OrderStatus;
  rider_id?: string;
  customer_id?: string;
  limit?: number;
  page?: number;
  offset?: number;
  date_from?: string;
  date_to?: string;
}

export interface OrderStats {
  total_orders: number;
  total_revenue: number;
  pending_count: number;
  completed_count: number;
  daily_revenue: { label: string; value: number }[];
}

// Helper interno para extraer datos de forma segura
const extractData = <T>(response: unknown): T => {
  if (!response) throw new Error("Respuesta vacía del servidor");
  const axiosResponse = response as { data?: T };
  return axiosResponse.data || (response as T);
};

function confirmItems(
  items: OrderCreateInput["items"],
  pricing: ExactOrderPricing,
) {
  if (
    items.length !== pricing.items.length ||
    items.some((item, i) =>
      ["quantity", "unit_price", "subtotal"].some(
        (key) =>
          (item as Record<string, unknown>)[key] !== pricing.items[i][key],
      ),
    )
  ) {
    throw new Error(
      "Los artículos confirmados no corresponden al precio enviado.",
    );
  }
}

export const orderService = {
  /**
   * Listar órdenes con filtros
   */
  getAll: async (params?: OrderListParams): Promise<Order[]> => {
    const task = capturePrivateTask();
    return readOrderCatalog(params, task.assertCurrent);
  },

  /**
   * Obtener detalles de una orden por ID
   */
  getById: async (id: string): Promise<Order> => {
    if (!id) throw new Error("[OrderService] ID de orden requerido");

    const task = capturePrivateTask();
    const response = await api.get<unknown>(
      `/orders/${encodeURIComponent(id)}`,
    );
    task.assertCurrent();
    return validateHttpOrder(response, id);
  },

  /**
   * Crear nueva orden
   */
  create: async (data: OrderCreateInput): Promise<Order> => {
    try {
      // Validación básica
      if (!data.delivery_address || !data.items || data.items.length === 0) {
        throw new Error("[OrderService] Datos incompletos para crear orden");
      }

      if (data.currency !== undefined && data.currency !== "USD")
        throw new Error("La moneda de la orden debe ser USD.");
      const payload = {
        ...preparePricePayload(data),
        currency: "USD" as const,
      };
      const task = capturePrivateTask();
      const response = await api.post<unknown>("/orders", payload);
      task.assertCurrent();
      const result = validateHttpOrder(extractData<unknown>(response));
      if (!result.pricing || result.pricing.revision !== 1)
        throw new Error(
          "El servidor no confirmó el precio exacto de la orden.",
        );
      for (const field of [
        "subtotal",
        "delivery_fee",
        "total",
        "declared_value",
      ] as const)
        if (
          payload[field] !== undefined &&
          String(payload[field]) !==
            result.pricing[field === "declared_value" ? "total" : field]
        )
          throw new Error("El precio confirmado no corresponde a lo enviado.");
      confirmItems(payload.items, result.pricing);
      return result;
    } catch (error) {
      console.error("[OrderService] Error creating order:", error);
      throw error;
    }
  },

  /**
   * Actualizar datos editables de una orden.
   */
  update: async (id: string, data: OrderUpdateInput): Promise<Order> => {
    if (!id)
      throw new Error("[OrderService] ID de orden requerido para actualizar");

    try {
      if (data.currency !== undefined && data.currency !== "USD")
        throw new Error("La moneda de la orden debe ser USD.");
      const payload = preparePricePayload(data);
      const task = capturePrivateTask();
      const response = await api.patch<unknown>(
        `/orders/${encodeURIComponent(id)}`,
        payload,
      );
      task.assertCurrent();
      const result = validateHttpOrder(extractData<unknown>(response), id);
      if (
        ["items", "subtotal", "delivery_fee", "total", "declared_value"].some(
          (key) => key in data,
        )
      ) {
        if (!result.pricing)
          throw new Error("El servidor no confirmó la revisión de precio.");
        const expected = data.expected_pricing_revision;
        if (
          expected == null
            ? result.pricing.revision !== 1
            : ![expected, expected + 1].includes(result.pricing.revision)
        )
          throw new Error(
            "La revisión confirmada no corresponde a la solicitud.",
          );
        if (payload.items) confirmItems(payload.items, result.pricing);
        for (const field of [
          "subtotal",
          "delivery_fee",
          "total",
          "declared_value",
        ] as const)
          if (
            payload[field] !== undefined &&
            String(payload[field]) !==
              result.pricing[field === "declared_value" ? "total" : field]
          )
            throw new Error(
              "El precio confirmado no coincide con el solicitado.",
            );
      }
      return result;
    } catch (error) {
      console.error(`[OrderService] Error updating order ${id}:`, error);
      throw error;
    }
  },

  /**
   * Asignar repartidor manualmente
   */
  assignRider: async (orderId: string, riderId: string): Promise<Order> => {
    if (!orderId || !riderId) {
      throw new Error("[OrderService] OrderID y RiderID son requeridos");
    }

    const task = capturePrivateTask();
    const response = await api.patch<unknown>(
      `/orders/${encodeURIComponent(orderId)}/assign`,
      { rider_id: riderId },
    );
    task.assertCurrent();
    orderAssignmentPatch(response, orderId, riderId);
    return validateHttpOrder(response, orderId);
  },

  /**
   * Asignación automática inteligente
   */
  assignRiderAuto: async (
    orderId: string,
  ): Promise<{
    message: string;
    order_id: string;
    assigned_rider: {
      id: string;
      name: string;
      distance_km: number;
    };
    other_candidates: number;
  }> => {
    if (!orderId)
      throw new Error(
        "[OrderService] OrderID requerido para asignación automática",
      );

    const task = capturePrivateTask();
    const response = await api.post<unknown>(
      `/orders/${encodeURIComponent(orderId)}/assign-auto`,
    );
    task.assertCurrent();
    const result = record(response),
      rider = record(result.assigned_rider);
    identifier(rider.id);
    if (
      result.order_id !== orderId ||
      typeof result.message !== "string" ||
      typeof rider.name !== "string" ||
      typeof rider.distance_km !== "number" ||
      !Number.isFinite(rider.distance_km) ||
      rider.distance_km < 0 ||
      !Number.isInteger(result.other_candidates) ||
      Number(result.other_candidates) < 0
    ) {
      throw new Error("La confirmación automática no coincide con el pedido");
    }
    return response as {
      message: string;
      order_id: string;
      assigned_rider: { id: string; name: string; distance_km: number };
      other_candidates: number;
    };
  },

  /**
   * Actualizar estado de la orden
   */
  updateStatus: async (id: string, status: OrderStatus): Promise<Order> => {
    if (!id || !status) {
      throw new Error("[OrderService] ID y Status son requeridos");
    }

    const task = capturePrivateTask();
    const response = await api.patch<unknown>(
      `/orders/${encodeURIComponent(id)}/status`,
      {},
      { params: { new_status: status } },
    );
    task.assertCurrent();
    const order = validateHttpOrder(response, id);
    if (order.status !== status)
      throw new Error("El servidor no confirmó el estado solicitado");
    return order;
  },

  /**
   * Eliminar orden
   */
  delete: async (id: string): Promise<void> => {
    if (!id) throw new Error("[OrderService] ID requerido para eliminar");

    try {
      await api.delete<void>(`/orders/${id}`);
    } catch (error) {
      console.error(`[OrderService] Error deleting order ${id}:`, error);
      throw error;
    }
  },

  /**
   * Cancelar orden con motivo
   */
  cancel: async (id: string, reason?: string): Promise<Order> => {
    if (!id) throw new Error("[OrderService] ID requerido para cancelar");
    if (typeof reason !== "string" || !isCancellationReasonValid(reason)) {
      throw new Error(
        "El motivo debe tener entre ocho y 500 caracteres sin controles",
      );
    }

    try {
      const response = await api.patch<Order>(
        `/orders/${encodeURIComponent(id)}/cancel`,
        { reason: reason.trim() },
      );
      return extractData<Order>(response);
    } catch (error) {
      console.error(`[OrderService] Error cancelling order ${id}:`, error);
      throw error;
    }
  },

  /**
   * Obtener estadísticas de órdenes
   */
  getStats: async (range: "week" | "month" = "week"): Promise<OrderStats> => {
    try {
      // Intentar obtener del backend real primero
      const response = await api.get<OrderStats>(
        `/orders/stats?range=${range}`,
      );
      const data = extractData<OrderStats>(response);

      // Unknown or malformed metrics are not measured zeroes.
      if (
        !data ||
        ![
          data.total_orders,
          data.total_revenue,
          data.pending_count,
          data.completed_count,
        ].every(
          (value) => typeof value === "number" && Number.isFinite(value),
        ) ||
        !Array.isArray(data.daily_revenue) ||
        !data.daily_revenue.every(
          (item) =>
            item &&
            typeof item.label === "string" &&
            typeof item.value === "number" &&
            Number.isFinite(item.value),
        )
      ) {
        throw new Error(
          "El resumen de pedidos contiene métricas desconocidas o inválidas",
        );
      }

      return data;
    } catch (error) {
      // A failed legacy read must not become fabricated business metrics.
      throw error;
    }
  },
};

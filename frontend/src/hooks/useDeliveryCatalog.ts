"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  firstDeliveryQuery,
  prepareDeliveryQuery,
  searchDeliveries,
  type DeliveryQuery,
  type DeliverySnapshot,
} from "@/lib/delivery-catalog";
import { readDeliveryPage } from "@/services/delivery-catalog.service";
import { capturePrivateTask } from "@/lib/private-task";

export function useDeliveryCatalog() {
  const [data, setData] = useState<DeliverySnapshot | null>(null),
    [pending, setPending] = useState<DeliveryQuery | null>(firstDeliveryQuery),
    [error, setError] = useState<string | null>(null),
    [search, setSearch] = useState("");
  const latest = useRef<DeliverySnapshot | null>(null),
    attempt = useRef(firstDeliveryQuery),
    alive = useRef(false),
    sequence = useRef(0);
  const load = useCallback(async (input: DeliveryQuery) => {
    if (!alive.current) return;
    const ticket = ++sequence.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () =>
      alive.current &&
      ticket === sequence.current &&
      (!task || task.isCurrent());
    try {
      const query = prepareDeliveryQuery(input);
      attempt.current = query;
      setPending(query);
      setError(null);
      task = capturePrivateTask();
      const next = await readDeliveryPage(query);
      task.assertCurrent();
      const old = latest.current;
      if (
        old &&
        old.query.status === query.status &&
        old.query.assignment === query.assignment &&
        old.query.rider === query.rider &&
        old.query.limit === query.limit &&
        Math.abs(old.query.offset - query.offset) === query.limit &&
        next.rows.some((row) =>
          old.rows.some((previous) => previous.id === row.id),
        )
      )
        throw new Error("Las páginas cambiaron");
      if (current()) {
        latest.current = next;
        setData(next);
      }
    } catch {
      if (current())
        setError(
          "No se pudo comprobar la consulta. Se conserva la última página confirmada.",
        );
    } finally {
      if (current()) setPending(null);
    }
  }, []);
  useEffect(() => {
    const requests = sequence;
    alive.current = true;
    void load(firstDeliveryQuery);
    return () => {
      alive.current = false;
      requests.current++;
    };
  }, [load]);
  const navigate = (direction: -1 | 1) => {
    const snapshot = latest.current;
    if (pending || !snapshot) return;
    const offset = snapshot.query.offset + direction * snapshot.query.limit;
    if (offset < 0 || (direction === 1 && offset >= snapshot.total)) return;
    void load({ ...snapshot.query, offset });
  };
  return {
    data,
    error,
    search,
    setSearch,
    isLoading: pending !== null,
    rows: searchDeliveries(data?.rows ?? [], search),
    load,
    navigate,
    refresh: () => load(latest.current?.query ?? firstDeliveryQuery),
    retry: () => load(attempt.current),
    first: () =>
      load({ ...(latest.current?.query ?? firstDeliveryQuery), offset: 0 }),
  };
}

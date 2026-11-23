"use client";

import { toast as notifications } from "sonner";
import { getCredentialGeneration } from "@/lib/auth-session";

export type FeedbackItem = {
  id: number;
  kind: "alert" | "confirm";
  message: string;
  title: string;
  tone: "error" | "warning";
  generation: number;
  pathname: string;
  resolve?: (accepted: boolean) => void;
};
let sequence = 0;
let queue: FeedbackItem[] = [];
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());
export const feedbackSnapshot = () => queue[0] ?? null;
export const subscribeFeedback = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

export function showAlert(message: string, options?: { title?: string; tone?: "error" | "warning" }): number {
  if (typeof window === "undefined") return 0;
  const generation = getCredentialGeneration();
  const text = String(message).replace(/^[✅❌⚠️]+\s*/u, "");
  const duplicate = queue.find((item) => item.kind === "alert" && item.message === text && item.generation === generation);
  if (duplicate) return duplicate.id;
  const item: FeedbackItem = {
    id: ++sequence, kind: "alert", message: text, generation, pathname: window.location.pathname,
    title: options?.title ?? "No se pudo completar la acción",
    tone: options?.tone ?? "error",
  };
  queue = [...queue, item];
  emit();
  return item.id;
}

export function confirmAction(message: string, title = "Confirmar acción"): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  return new Promise((resolve) => {
    queue = [...queue, {
      id: ++sequence, kind: "confirm", message, title, tone: "warning",
      generation: getCredentialGeneration(), pathname: window.location.pathname, resolve,
    }];
    emit();
  });
}

export function settleFeedback(id: number, accepted: boolean): void {
  const item = queue[0];
  if (!item || item.id !== id) return;
  queue = queue.slice(1);
  item.resolve?.(accepted && item.generation === getCredentialGeneration() && item.pathname === window.location.pathname);
  emit();
}

export function dismissDialogs(): void {
  const previous = queue;
  queue = [];
  previous.forEach((item) => item.resolve?.(false));
  emit();
}

export function clearFeedback(): void {
  dismissDialogs();
  notifications.dismiss();
}

/** Informational results stay nonblocking; errors require acknowledgement. */
export const toast = {
  success: notifications.success,
  info: notifications.info,
  error: (message: string) => showAlert(message),
  warning: (message: string) => showAlert(message, { title: "Revisa esta información", tone: "warning" }),
};

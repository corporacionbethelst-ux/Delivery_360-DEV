import { formatDistanceToNow } from 'date-fns';
import { es } from 'date-fns/locale';

/** Legacy API timestamps are UTC even when the ISO string has no zone suffix. */
export function alertDate(value: unknown): Date | null {
  if (!(value instanceof Date) && typeof value !== 'string') return null;
  if (typeof value === 'string' && !value.trim()) return null;
  let input = value instanceof Date ? value.getTime() : value;
  if (typeof input === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(input)) {
    input += 'Z';
  }
  const date = new Date(input);
  return Number.isFinite(date.getTime()) ? date : null;
}

export function formatAlertDate(value: unknown, relative = false): string {
  const date = alertDate(value);
  if (!date) return 'Fecha no disponible';
  return relative
    ? formatDistanceToNow(date, { addSuffix: true, locale: es })
    : date.toLocaleString();
}

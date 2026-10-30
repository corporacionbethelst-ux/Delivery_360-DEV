/** Canonical states and terminal aliases received from older API responses. */
export function isDeliveryCancelled(status: string | null | undefined): boolean {
  return status === 'CANCELADA' || status === 'CANCELADO';
}

export function isDeliveryTerminal(status: string | null | undefined): boolean {
  return isDeliveryCancelled(status) || ['COMPLETADA', 'FALLIDA', 'ENTREGADO', 'FALLIDO'].includes(status ?? '');
}

export function isCancellationReasonValid(reason: string): boolean {
  const value = reason.trim();
  // Count Unicode code points, matching Python's length validation.
  const length = Array.from(value).length;
  return length >= 8 && length <= 500 && !new RegExp('[\\p{Cc}\\p{Cf}\\p{Cs}]', 'u').test(value);
}

/** Encode spreadsheet text as literal cells; numeric negatives remain numbers. */
function csvCell(value: unknown): string {
  if (value == null) return '""';
  if (!['string', 'number', 'boolean'].includes(typeof value) || typeof value === 'number' && !Number.isFinite(value)) {
    throw new Error('El CSV contiene una celda no válida');
  }
  let text = String(value);
  if (typeof value === 'string' && /^[\s\u0000-\u001f\u007f\uFEFF]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

export function serializeCSV(data: ReadonlyArray<Record<string, unknown>>): string {
  if (!data.length) return '';
  const headers = Array.from(new Set(data.flatMap(row => Object.keys(row))));
  if (!headers.length) throw new Error('El CSV no tiene columnas');
  return '\uFEFF' + [headers.map(csvCell).join(','), ...data.map(row => headers.map(name => csvCell(Object.prototype.hasOwnProperty.call(row, name) ? row[name] : undefined)).join(','))].join('\r\n') + '\r\n';
}

export function downloadCSV(data: ReadonlyArray<Record<string, unknown>>, filename: string): boolean {
  if (!data.length) { alert('No hay datos para exportar'); return false; }
  const content = serializeCSV(data);
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  let link: HTMLAnchorElement | undefined;
  try {
    link = document.createElement('a');
    link.href = url;
    const safeName = filename.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_');
    link.download = `${safeName}_${new Date().toISOString().split('T')[0]}.csv`;
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    return true;
  } finally {
    link?.remove();
    // Give browsers time to start consuming the Blob, then release its storage.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

/** Selection checks for UX; the server independently validates bytes and limits. */
export const DOCUMENT_ACCEPT = '.pdf,.png,.jpg,.jpeg';
export const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024;

export function validateDocumentSelection(file: File): void {
  if (!file.size) throw new Error('El documento está vacío');
  if (file.size > MAX_DOCUMENT_BYTES) throw new Error('El documento excede el máximo de 10 MiB');
  const extension = /^.+\.([^.]+)$/.exec(file.name)?.[1].toLowerCase();
  const types: Record<string, string> = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg' };
  const expected = extension ? types[extension] : undefined;
  if (!expected) throw new Error('Solo se admiten documentos PDF, PNG o JPEG');
  const declared = file.type.split(';')[0].trim().toLowerCase();
  if (declared && declared !== 'application/octet-stream' && declared !== expected) {
    throw new Error('El tipo declarado no coincide con el archivo');
  }
}

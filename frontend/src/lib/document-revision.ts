/** Revisions are concurrency preconditions, never authorization credentials. */
export class DocumentRevisionError extends Error {
  readonly status = 409;
  constructor() {
    super('Recarga la documentación para revisar su versión actual');
    this.name = 'DocumentRevisionError';
  }
}

export function requireDocumentRevision(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) throw new DocumentRevisionError();
  return value;
}

export function isDocumentRevisionConflict(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'status' in error && (error.status === 409 || error.status === 412);
}

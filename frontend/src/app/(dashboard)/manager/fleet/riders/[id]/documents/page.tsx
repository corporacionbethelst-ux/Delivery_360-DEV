"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  FileText,
  RefreshCw,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import { DocumentDownloadButton } from "@/components/DocumentDownloadButton";
import {
  OperationsHeader,
  OperationEmpty,
  OperationNotice,
  OperationPill,
  operationStyles,
  type OperationTone,
} from "@/components/operations/OperationsUI";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { riderService } from "@/services/rider.service";
import { useAuthStore } from "@/stores/authStore";
import type { RiderDocument } from "@/types/user";
import {
  requireDocumentRevision,
  isDocumentRevisionConflict,
} from "@/lib/document-revision";
import {
  DOCUMENT_ACCEPT,
  validateDocumentSelection,
} from "@/lib/document-upload";
import {
  canManageRiders,
  riderDate,
  riderReadRoles,
} from "@/lib/rider-display";

const labels: Record<RiderDocument["type"], string> = {
  LICENCIA: "Licencia de Conducción",
  DOCUMENTO_IDENTIDAD: "Documento de Identidad",
  REGISTRO_VEHICULO: "Tarjeta de Propiedad",
  SEGURO: "Seguro / SOAT",
};
const statuses: Record<string, { label: string; tone: OperationTone }> = {
  PENDIENTE: { label: "Pendiente", tone: "amber" },
  APROBADO: { label: "Aprobado", tone: "emerald" },
  RECHAZADO: { label: "Rechazado", tone: "rose" },
};
type Snapshot = { id: string; revision: string; label: string };
const errorMessage = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback;

export default function ManagerRiderDocumentsPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  return (
    <ManagerPageBoundary scope={`rider-documents:${id}`} roles={riderReadRoles}>
      <Documents id={id} />
    </ManagerPageBoundary>
  );
}
function Documents({ id }: { id: string }) {
  const { user } = useAuthStore();
  const canManage = canManageRiders(user?.role);
  const [documents, setDocuments] = useState<RiderDocument[] | null>(null);
  const [loading, setLoading] = useState(false),
    [pending, setPending] = useState(false);
  const [readError, setReadError] = useState<string | null>(null),
    [actionError, setActionError] = useState<string | null>(null),
    [success, setSuccess] = useState<string | null>(null);
  const [rejection, setRejection] = useState<Snapshot | null>(null),
    [reason, setReason] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false),
    [uploadType, setUploadType] = useState("");
  const [file, setFile] = useState<File | null>(null),
    [fileError, setFileError] = useState<string | null>(null);
  const alive = useRef(false),
    sequence = useRef(0),
    writing = useRef(false),
    reading = useRef(false);
  const load = useCallback(async () => {
    const ticket = ++sequence.current;
    reading.current = true;
    setLoading(true);
    setReadError(null);
    try {
      if (!id) throw new Error("ID de repartidor no válido.");
      const rows = await riderService.getDocuments(id);
      if (
        !Array.isArray(rows) ||
        rows.some(
          (row) =>
            !row ||
            typeof row.id !== "string" ||
            !row.id ||
            (row.rider_id != null && row.rider_id !== id),
        ) ||
        new Set(rows.map((row) => row.id)).size !== rows.length
      )
        throw new Error(
          "La respuesta documental no corresponde a la ficha solicitada.",
        );
      if (alive.current && ticket === sequence.current) setDocuments(rows);
    } catch (error) {
      if (alive.current && ticket === sequence.current)
        setReadError(
          errorMessage(error, "No se pudieron cargar los documentos."),
        );
    } finally {
      if (alive.current && ticket === sequence.current) {
        reading.current = false;
        setLoading(false);
      }
    }
  }, [id]);
  useEffect(() => {
    const requests = sequence;
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
      requests.current++;
    };
  }, [load]);
  const disabled = loading || pending || !!readError || documents === null;
  const snapshotForReview = (doc: RiderDocument): Snapshot | null => {
    if (!canManage || disabled || reading.current || writing.current)
      return null;
    try {
      return {
        id: doc.id,
        revision: requireDocumentRevision(doc.revision),
        label: labels[doc.type] || doc.type || "Documento",
      };
    } catch (error) {
      const message = errorMessage(error, "Recarga la documentación");
      setActionError(message);
      toast.error(message);
      return null;
    }
  };
  const perform = async (
    work: () => Promise<unknown>,
    message: string,
    close: () => void,
  ) => {
    if (
      !canManage ||
      !alive.current ||
      reading.current ||
      writing.current ||
      disabled
    )
      return;
    writing.current = true;
    setPending(true);
    setActionError(null);
    setSuccess(null);
    try {
      await work();
      if (!alive.current) return;
      close();
      setSuccess(message);
      toast.success(message);
      await load();
    } catch (error) {
      if (!alive.current) return;
      const text = errorMessage(error, "No se pudo completar la operación.");
      setActionError(text);
      toast.error(text);
      if (isDocumentRevisionConflict(error)) {
        setRejection(null);
        await load();
      }
    } finally {
      writing.current = false;
      if (alive.current) setPending(false);
    }
  };
  const approve = (doc: RiderDocument) => {
    const snapshot = snapshotForReview(doc);
    if (
      !snapshot ||
      !window.confirm(
        `¿Aprobar ${snapshot.label}? Documento: ${snapshot.id}. Repartidor: ${id}.`,
      )
    )
      return;
    void perform(
      () => riderService.approveDocument(snapshot.id, snapshot.revision),
      "Documento aprobado correctamente",
      () => {},
    );
  };
  const remove = (doc: RiderDocument) => {
    const snapshot = snapshotForReview(doc);
    if (
      !snapshot ||
      !window.confirm(
        `¿Eliminar ${snapshot.label}? Documento: ${snapshot.id}. Repartidor: ${id}. Su referencia se eliminará permanentemente.`,
      )
    )
      return;
    void perform(
      () => riderService.deleteDocument(snapshot.id, snapshot.revision),
      "Documento eliminado",
      () => {},
    );
  };
  const reject = () => {
    const snapshot = rejection,
      text = reason.trim();
    if (!snapshot || !text || text.length > 2000) return;
    void perform(
      () => riderService.rejectDocument(snapshot.id, text, snapshot.revision),
      "Documento rechazado",
      () => setRejection(null),
    );
  };
  const openUpload = () => {
    setFile(null);
    setFileError(null);
    setUploadType("");
    setActionError(null);
    setUploadOpen(true);
  };
  const selectFile = (candidate: File | null) => {
    setFile(null);
    setFileError(null);
    if (!candidate) return;
    try {
      validateDocumentSelection(candidate);
      setFile(candidate);
    } catch (error) {
      setFileError(errorMessage(error, "Archivo inválido"));
    }
  };
  const upload = () => {
    const chosenFile = file,
      type = uploadType;
    if (!chosenFile || !Object.hasOwn(labels, type)) return;
    try {
      validateDocumentSelection(chosenFile);
    } catch (error) {
      setFileError(errorMessage(error, "Archivo inválido"));
      return;
    }
    void perform(
      () => riderService.uploadDocumentForRider(id, { type, file: chosenFile }),
      "Documento subido exitosamente",
      () => {
        setUploadOpen(false);
        setFile(null);
        setUploadType("");
      },
    );
  };
  return (
    <main className={operationStyles.page}>
      <OperationsHeader
        icon={ShieldCheck}
        eyebrow="Flota · Documentos"
        title="Validación de Documentos"
        audit
        description={
          <span className="break-all">
            ID repartidor: {id || "No informado"}
          </span>
        }
        actions={
          <>
            <Link
              className={operationStyles.button}
              href={`/manager/fleet/riders/${encodeURIComponent(id)}`}
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              Volver al perfil
            </Link>
            <button
              className={operationStyles.button}
              onClick={() => void load()}
              disabled={loading || pending}
            >
              <RefreshCw aria-hidden="true" className="h-4 w-4" />
              Actualizar
            </button>
            {canManage && (
              <button
                className={operationStyles.primaryButton}
                disabled={disabled}
                onClick={openUpload}
              >
                <Upload aria-hidden="true" className="h-4 w-4" />
                Subir Documento
              </button>
            )}
          </>
        }
      />
      {loading && (
        <OperationNotice role="status">Consultando documentos…</OperationNotice>
      )}
      {readError && (
        <OperationNotice role="alert" tone="warning">
          <p>{readError}</p>
          <p>Se conserva la última consulta confirmada, si existe.</p>
          <button
            className={operationStyles.button}
            onClick={() => void load()}
            disabled={loading || pending}
          >
            Reintentar documentos
          </button>
        </OperationNotice>
      )}
      {actionError && (
        <OperationNotice role="alert" tone="error">
          {actionError}
        </OperationNotice>
      )}
      {success && (
        <OperationNotice role="status" tone="success">
          {success}
        </OperationNotice>
      )}
      {documents !== null && (
        <section
          aria-label="Documentos de la consulta confirmada"
          aria-busy={loading}
          className="space-y-4"
        >
          <p className="text-sm text-slate-600">
            {documents.length} documentos cargados. Fechas en America/Caracas.
          </p>
          {documents.length === 0 ? (
            <OperationEmpty>
              <span>Sin documentos registrados</span>
              {canManage && (
                <button
                  className={operationStyles.button}
                  disabled={disabled}
                  onClick={openUpload}
                >
                  Subir Primer Documento
                </button>
              )}
            </OperationEmpty>
          ) : (
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {documents.map((doc) => {
                const status = statuses[doc.status],
                  label = labels[doc.type] || doc.type || "Tipo no informado";
                let hasRevision = false;
                try {
                  requireDocumentRevision(doc.revision);
                  hasRevision = true;
                } catch {
                  /* Require a confirmed version for this content. */
                }
                return (
                  <article
                    key={`${doc.id}:${doc.revision ?? "unknown"}`}
                    aria-label={`Documento ${doc.id}`}
                    className={`${operationStyles.panel} flex min-w-0 flex-col overflow-hidden`}
                  >
                    <div className="space-y-3 border-b border-violet-100 bg-gradient-to-br from-violet-50 via-white to-blue-50 p-5">
                      <h2 className="font-bold">{label}</h2>
                      <p className="break-all font-mono text-xs text-slate-600">
                        ID documento: {doc.id}
                      </p>
                      <OperationPill tone={status?.tone}>
                        {status?.label || doc.status || "Estado no informado"}
                      </OperationPill>
                    </div>
                    <div className="flex flex-1 flex-col gap-4 p-5">
                      <p className="text-sm text-slate-600">
                        Subido: {riderDate(doc.created_at)}
                      </p>
                      <p className="text-sm text-slate-600">
                        Actualizado: {riderDate(doc.updated_at)}
                      </p>
                      <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-4">
                        {!hasRevision ? (
                          <p className="text-sm">
                            Recarga la documentación para consultar su versión
                            actual.
                          </p>
                        ) : doc.file_url && doc.file_url !== "#" ? (
                          <DocumentDownloadButton
                            documentId={doc.id}
                            revision={doc.revision}
                            className={operationStyles.button}
                          />
                        ) : (
                          <p className="text-sm">Archivo no informado.</p>
                        )}
                      </div>
                      {doc.rejection_reason && (
                        <OperationNotice tone="warning">
                          <p className="font-semibold">Motivo del rechazo</p>
                          <p className="break-words">{doc.rejection_reason}</p>
                        </OperationNotice>
                      )}
                      {canManage && (
                        <div className="mt-auto flex flex-wrap gap-2 border-t border-slate-100 pt-4">
                          {doc.status === "PENDIENTE" && (
                            <>
                              <button
                                className={operationStyles.button}
                                onClick={() => approve(doc)}
                                disabled={disabled}
                              >
                                Aprobar
                              </button>
                              <button
                                className={operationStyles.button}
                                disabled={disabled}
                                onClick={() => {
                                  const snapshot = snapshotForReview(doc);
                                  if (snapshot) {
                                    setActionError(null);
                                    setReason(
                                      "No cumple con los requisitos de legibilidad o vigencia.",
                                    );
                                    setRejection(snapshot);
                                  }
                                }}
                              >
                                Rechazar
                              </button>
                            </>
                          )}
                          <button
                            className={operationStyles.button}
                            title="Eliminar documento"
                            aria-label={`Eliminar documento ${doc.id}`}
                            onClick={() => remove(doc)}
                            disabled={disabled}
                          >
                            Eliminar
                          </button>
                        </div>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      )}
      <Dialog
        open={!!rejection}
        onOpenChange={(open) => {
          if (!open && !writing.current) setRejection(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl border-violet-200">
          <DialogHeader>
            <DialogTitle>Rechazar Documento</DialogTitle>
            <DialogDescription>
              {rejection?.label}. Documento:{" "}
              <span className="break-all">{rejection?.id}</span>. Repartidor:{" "}
              <span className="break-all">{id}</span>. Se revisará la versión
              seleccionada al abrir este diálogo.
            </DialogDescription>
          </DialogHeader>
          <label htmlFor="rejection-reason" className="text-sm font-medium">
            Motivo del rechazo *
          </label>
          <textarea
            id="rejection-reason"
            className={`${operationStyles.field} min-h-28`}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={2000}
            disabled={pending}
          />
          {actionError && (
            <p role="alert" className="text-sm text-rose-700">
              {actionError}
            </p>
          )}
          <DialogFooter>
            <button
              className={operationStyles.button}
              disabled={pending}
              onClick={() => setRejection(null)}
            >
              Cancelar
            </button>
            <button
              className={operationStyles.primaryButton}
              disabled={
                disabled || !reason.trim() || reason.trim().length > 2000
              }
              onClick={reject}
            >
              {pending ? "Guardando…" : "Confirmar"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={uploadOpen}
        onOpenChange={(open) => {
          if (!writing.current) setUploadOpen(open);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl border-violet-200">
          <DialogHeader>
            <DialogTitle>Subir Documento Manualmente</DialogTitle>
            <DialogDescription>
              Repartidor: <span className="break-all">{id}</span>. Se guardará
              como pendiente; reemplazar un documento puede afectar la
              habilitación del repartidor.
            </DialogDescription>
          </DialogHeader>
          <fieldset
            disabled={pending}
            className="min-w-0 space-y-4 rounded-xl border border-blue-100 bg-blue-50/40 p-4"
          >
            <div className="space-y-2">
              <label
                htmlFor="upload-document-type"
                className="text-sm font-medium"
              >
                Tipo de Documento
              </label>
              <select
                id="upload-document-type"
                className={operationStyles.field}
                value={uploadType}
                onChange={(event) => setUploadType(event.target.value)}
              >
                <option value="">Seleccionar tipo…</option>
                {Object.entries(labels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label
                htmlFor="upload-document-file"
                className="text-sm font-medium"
              >
                Archivo (PDF, JPG, PNG)
              </label>
              <input
                id="upload-document-file"
                type="file"
                accept={DOCUMENT_ACCEPT}
                className={operationStyles.field}
                onChange={(event) =>
                  selectFile(event.target.files?.[0] ?? null)
                }
                aria-describedby="document-file-help"
              />
              <p id="document-file-help" className="text-xs text-slate-600">
                Máximo 10 MiB. El servidor valida el contenido del archivo.
              </p>
            </div>
          </fieldset>
          {fileError && (
            <p role="alert" className="text-sm text-rose-700">
              {fileError}
            </p>
          )}
          {actionError && (
            <p role="alert" className="text-sm text-rose-700">
              {actionError}
            </p>
          )}
          <DialogFooter>
            <button
              className={operationStyles.button}
              disabled={pending}
              onClick={() => setUploadOpen(false)}
            >
              Cancelar
            </button>
            <button
              className={operationStyles.primaryButton}
              disabled={disabled || !file || !uploadType}
              onClick={upload}
            >
              {pending ? "Subiendo…" : "Subir"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}

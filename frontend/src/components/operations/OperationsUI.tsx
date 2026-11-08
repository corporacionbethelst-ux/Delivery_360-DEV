import type { ReactNode } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Inbox,
  Info,
  type LucideIcon,
} from "lucide-react";

export const operationStyles = {
  page: "mx-auto max-w-7xl space-y-6 text-slate-900",
  panel: "rounded-2xl border border-slate-200 bg-white shadow-sm",
  field:
    "w-full min-w-0 rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition-colors focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:cursor-not-allowed disabled:bg-slate-100",
  button:
    "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  primaryButton:
    "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-blue-700 bg-blue-700 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  link: "inline-flex items-center gap-2 rounded-lg font-semibold text-blue-700 underline decoration-blue-200 underline-offset-4 transition-colors hover:text-blue-900 hover:decoration-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2",
  tableHead:
    "border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600",
};

const tones = {
  blue: "border-blue-200 bg-blue-50 text-blue-800",
  violet: "border-violet-200 bg-violet-50 text-violet-800",
  emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
  amber: "border-amber-200 bg-amber-50 text-amber-900",
  rose: "border-rose-200 bg-rose-50 text-rose-800",
  slate: "border-slate-200 bg-slate-100 text-slate-700",
};
export type OperationTone = keyof typeof tones;

export function OperationsHeader({
  title,
  description,
  icon: Icon,
  actions,
  audit = false,
  eyebrow,
}: {
  title: string;
  description: ReactNode;
  icon: LucideIcon;
  actions?: ReactNode;
  audit?: boolean;
  eyebrow?: string;
}) {
  return (
    <header
      className={`relative overflow-hidden rounded-2xl border p-5 shadow-sm sm:p-6 ${audit ? "border-violet-200 bg-gradient-to-br from-violet-50 via-white to-blue-50" : "border-blue-200 bg-gradient-to-br from-blue-50 via-white to-cyan-50"}`}
    >
      <div className="relative flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex min-w-0 items-start gap-4 xl:flex-1">
          <div
            className={`hidden shrink-0 rounded-2xl p-3 text-white shadow-sm sm:block ${audit ? "bg-gradient-to-br from-violet-600 to-indigo-700" : "bg-gradient-to-br from-blue-600 to-cyan-700"}`}
          >
            <Icon aria-hidden="true" className="h-6 w-6" />
          </div>
          <div className="min-w-0 space-y-2">
            <p
              className={`text-xs font-bold uppercase tracking-widest ${audit ? "text-violet-700" : "text-blue-700"}`}
            >
              {eyebrow ?? `Operaciones · ${audit ? "Auditoría" : "Entregas"}`}
            </p>
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
              {title}
            </h1>
            <div className="max-w-2xl text-sm leading-relaxed text-slate-600">
              {description}
            </div>
          </div>
        </div>
        {actions && (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        )}
      </div>
    </header>
  );
}

export function SectionHeading({
  icon: Icon,
  title,
  description,
  tone = "blue",
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  tone?: OperationTone;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className={`shrink-0 rounded-xl border p-2 ${tones[tone]}`}>
        <Icon aria-hidden="true" className="h-5 w-5" />
      </span>
      <div className="min-w-0">
        <h2 className="font-semibold text-slate-900">{title}</h2>
        {description && (
          <p className="mt-1 text-sm leading-relaxed text-slate-600">
            {description}
          </p>
        )}
      </div>
    </div>
  );
}

export function OperationMetric({
  label,
  value,
  icon: Icon,
  tone = "blue",
}: {
  label: string;
  value: ReactNode;
  icon: LucideIcon;
  tone?: OperationTone;
}) {
  return (
    <div
      className={`${operationStyles.panel} flex min-w-0 items-start gap-3 p-4`}
    >
      <span className={`shrink-0 rounded-xl border p-2.5 ${tones[tone]}`}>
        <Icon aria-hidden="true" className="h-5 w-5" />
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium leading-relaxed text-slate-600">
          {label}
        </p>
        <p className="mt-1 break-words text-xl font-bold tabular-nums text-slate-900">
          {value}
        </p>
      </div>
    </div>
  );
}

export function OperationPill({
  children,
  tone = "slate",
}: {
  children: ReactNode;
  tone?: OperationTone;
}) {
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${tones[tone]}`}
    >
      <span
        aria-hidden="true"
        className="h-1.5 w-1.5 shrink-0 rounded-full bg-current"
      />
      {children}
    </span>
  );
}

const noticeStyles = {
  info: { style: "border-blue-200 bg-blue-50/70 text-blue-950", icon: Info },
  warning: {
    style: "border-amber-200 bg-amber-50 text-amber-950",
    icon: AlertCircle,
  },
  error: {
    style: "border-rose-200 bg-rose-50 text-rose-950",
    icon: AlertCircle,
  },
  success: {
    style: "border-emerald-200 bg-emerald-50 text-emerald-950",
    icon: CheckCircle2,
  },
};
export function OperationNotice({
  children,
  tone = "info",
  role,
}: {
  children: ReactNode;
  tone?: keyof typeof noticeStyles;
  role?: "alert" | "status";
}) {
  const { style, icon: Icon } = noticeStyles[tone];
  return (
    <div
      role={role}
      className={`flex items-start gap-3 rounded-xl border p-4 text-sm leading-relaxed ${style}`}
    >
      <Icon aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-2">{children}</div>
    </div>
  );
}

export function OperationEmpty({ children }: { children: ReactNode }) {
  return (
    <div
      className={`${operationStyles.panel} flex flex-col items-center gap-3 px-5 py-10 text-center text-sm text-slate-600`}
    >
      <span className="rounded-2xl bg-slate-100 p-3">
        <Inbox aria-hidden="true" className="h-7 w-7 text-slate-500" />
      </span>
      <p className="max-w-lg leading-relaxed">{children}</p>
    </div>
  );
}

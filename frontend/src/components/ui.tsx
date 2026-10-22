import type { Tone } from "@/lib/format";

const TONES: Record<Tone, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/15",
  blue: "bg-sky-50 text-sky-700 ring-sky-600/15",
  gray: "bg-zinc-100 text-zinc-600 ring-zinc-500/15",
  red: "bg-rose-50 text-rose-700 ring-rose-600/15",
  amber: "bg-amber-50 text-amber-700 ring-amber-600/20",
  violet: "bg-accent-soft text-accent ring-accent/20",
};

export function Pill({ tone, children, live }: { tone: Tone; children: React.ReactNode; live?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${live ? "animate-pulse" : ""}`} />
      {children}
    </span>
  );
}

export function Alert({ kind = "error", children }: { kind?: "error" | "info" | "warning" | "success"; children: React.ReactNode }) {
  const styles = {
    error: "border-rose-200 bg-rose-50 text-rose-800",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    info: "border-sky-200 bg-sky-50 text-sky-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
  }[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-xl border px-4 py-3 text-sm ${styles}`}>
      {children}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return <span className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent ${className}`} />;
}

export function Counter({ value, max }: { value: string | null | undefined; max: number }) {
  return <span className="text-xs tabular-nums text-muted">{(value ?? "").length}/{max}</span>;
}

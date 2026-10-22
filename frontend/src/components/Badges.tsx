import type { CallStatus } from "@/lib/api";
import { humanize } from "@/lib/format";

const STATUS_STYLES: Record<CallStatus, string> = {
  queued: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300",
  ringing: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  in_progress: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  completed: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  failed: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
};

export function StatusBadge({ status }: { status: CallStatus }) {
  const live = status === "ringing" || status === "in_progress";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}>
      {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {humanize(status)}
    </span>
  );
}

const POSITIVE = new Set(["demo_booked", "interested_follow_up", "callback_requested", "high", "medium"]);
const NEGATIVE = new Set(["not_interested", "do_not_call", "wrong_person", "none", "low"]);

export function OutcomeBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted">—</span>;
  const tone = POSITIVE.has(value)
    ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
    : NEGATIVE.has(value)
      ? "bg-rose-500/10 text-rose-700 dark:text-rose-300"
      : "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300";
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${tone}`}>{humanize(value)}</span>;
}

export function SyncBadge({ status }: { status: "pending" | "synced" | "error" }) {
  const styles = {
    synced: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
    pending: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300",
    error: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
  }[status];
  const label = { synced: "Live on Retell", pending: "Not synced", error: "Sync failed" }[status];
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${styles}`}>{label}</span>;
}

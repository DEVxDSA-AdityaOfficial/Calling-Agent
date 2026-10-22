import type { Call } from "./api";

export const APP_NAME = "Calling Agent";

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m ? `${m}m ${s.toString().padStart(2, "0")}s` : `${s}s`;
}

export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => n.toString().padStart(2, "0")).join(":");
}

export function parseDate(iso: string): Date {
  // Backend timestamps are UTC; SQLite may drop the offset, so assume UTC if missing.
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return parseDate(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = parseDate(iso);
  const now = new Date();
  const time = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const days = Math.floor((new Date(now.toDateString()).getTime() - new Date(date.toDateString()).getTime()) / 86_400_000);
  if (days === 0) return `Today ${time}`;
  if (days === 1) return `Yesterday ${time}`;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" }) + ` ${time}`;
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const ACTIVE_STATUSES = new Set(["queued", "ringing", "in_progress"]);

export function isActive(call: Pick<Call, "status">) {
  return ACTIVE_STATUSES.has(call.status);
}

export type Tone = "green" | "blue" | "gray" | "red" | "amber" | "violet";

/** One label that summarises a call for tables: live status, or its business result. */
export function callResult(call: Call): { label: string; tone: Tone; live?: boolean } {
  if (call.status === "queued") return { label: "Queued", tone: "gray", live: true };
  if (call.status === "ringing") return { label: "Ringing", tone: "amber", live: true };
  if (call.status === "in_progress") return { label: "In progress", tone: "blue", live: true };
  if (call.status === "failed") {
    if (call.disconnection_reason === "dial_busy") return { label: "Busy", tone: "red" };
    if (call.goal_status === "no_response") return { label: "No answer", tone: "gray" };
    return { label: "Failed", tone: "red" };
  }
  switch (call.goal_status) {
    case "goal_achieved":
      return { label: "Goal achieved", tone: "green" };
    case "follow_up":
      return { label: "Interested", tone: "blue" };
    case "not_interested":
      return { label: "Not interested", tone: "gray" };
    case "no_response":
      return { label: call.outcome === "voicemail" ? "Voicemail" : "No response", tone: "gray" };
    default:
      return { label: "Completed", tone: "green" };
  }
}

export const GOAL_LABELS: Record<string, string> = {
  goal_achieved: "Goal achieved",
  follow_up: "Interested, follow-up",
  not_interested: "Not interested",
  no_response: "No response",
  failed: "Call failed",
};

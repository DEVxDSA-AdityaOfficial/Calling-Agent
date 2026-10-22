"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { CallsTable } from "@/components/CallsTable";
import { IconPhone } from "@/components/icons";
import { StartCallForm } from "@/components/StartCallForm";
import { Alert, PageHeader } from "@/components/ui";
import { api, type Call } from "@/lib/api";
import { GOAL_LABELS, isActive } from "@/lib/format";
import { usePolling } from "@/lib/usePolling";

const FILTERS = ["", ...Object.keys(GOAL_LABELS)];

export default function CallsPage() {
  const params = useSearchParams();
  const [showNew, setShowNew] = useState(params.get("new") === "1" || !!params.get("agent"));
  const [filter, setFilter] = useState("");

  return (
    <>
      <PageHeader
        title="Calls"
        subtitle="Place outbound calls and review every conversation."
        actions={!showNew && <button className="btn-primary" onClick={() => setShowNew(true)}><IconPhone /> New Call</button>}
      />
      {showNew && (
        <section className="card mb-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-semibold">New call</h2>
            <button className="text-sm text-muted hover:text-foreground" onClick={() => setShowNew(false)}>Cancel</button>
          </div>
          <StartCallForm defaultAgentId={params.get("agent")} />
        </section>
      )}

      <div className="mb-3 flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button key={f} onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${filter === f ? "bg-ink text-white" : "bg-surface text-muted ring-1 ring-border hover:text-foreground"}`}>
            {f ? GOAL_LABELS[f] : "All calls"}
          </button>
        ))}
      </div>
      {/* Keyed so changing the filter restarts polling with the new query. */}
      <CallsList key={filter} goal={filter} />
    </>
  );
}

function CallsList({ goal }: { goal: string }) {
  const { data: calls, error } = usePolling(
    () => api<Call[]>(`/calls?limit=200${goal ? `&goal_status=${goal}` : ""}`),
    (d) => !!d?.some(isActive),
  );
  return (
    <>
      {error && <div className="mb-3"><Alert>{error}</Alert></div>}
      <section className="card">{calls && <CallsTable calls={calls} empty="No calls here yet." />}</section>
    </>
  );
}

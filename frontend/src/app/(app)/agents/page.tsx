"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { IconPhone, IconPlus } from "@/components/icons";
import { FadeIn, HoverCard, Skeleton, Stagger, StaggerItem } from "@/components/motion";
import { type BrandId, ProviderLogo } from "@/components/ProviderLogo";
import { Alert, PageHeader, Pill } from "@/components/ui";
import { api, type Agent, type Options } from "@/lib/api";
import { formatRelative } from "@/lib/format";

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>();
  const [options, setOptions] = useState<Options>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    api<Agent[]>("/agents").then(setAgents).catch((e) => setError(e.message));
    api<Options>("/options").then(setOptions).catch(() => {});
  }, []);

  return (
    <>
      <FadeIn><PageHeader
        title="Agents"
        subtitle="Describe the goal, define the boundaries, let AI handle the conversation."
        actions={<Link href="/agents/new" className="btn-primary"><IconPlus /> New Agent</Link>}
      /></FadeIn>
      {error && <Alert>{error}</Alert>}
      {agents && !agents.length && (
        <div className="card py-14 text-center">
          <p className="mb-4 text-muted">No agents yet.</p>
          <Link href="/agents/new" className="btn-primary"><IconPlus /> Create your first agent</Link>
        </div>
      )}
      {!agents && !error && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-44 rounded-2xl" />)}</div>
      )}
      <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {agents?.map((a) => (
          <StaggerItem key={a.id}>
          <HoverCard className="card flex h-full flex-col">
            <Link href={`/agents/${a.id}`} className="flex-1">
              <div className="mb-3 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-semibold">{a.name}</div>
                  <div className="truncate text-sm text-muted">{a.business_name}</div>
                </div>
                {a.sync_status === "synced" ? <Pill tone="green">Ready</Pill> : a.sync_status === "error" ? <Pill tone="red">Needs attention</Pill> : <Pill tone="gray">Draft</Pill>}
              </div>
              <p className="line-clamp-2 text-sm">{a.objective}</p>
              <div className="mt-3 flex flex-wrap gap-1.5 text-xs text-muted">
                <span className="rounded-md bg-background px-2 py-0.5">{options?.languages[a.language] ?? a.language}</span>
                <span className="rounded-md bg-background px-2 py-0.5 capitalize">{a.tone}</span>
                <ModeBadge agent={a} />
              </div>
            </Link>
            <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs text-muted">
              <span>Updated {formatRelative(a.updated_at)}</span>
              {a.sync_status === "synced" && (
                <Link href={`/calls?agent=${a.id}`} className="inline-flex items-center gap-1 font-medium text-foreground hover:text-accent"><IconPhone /> Call</Link>
              )}
            </div>
          </HoverCard>
          </StaggerItem>
        ))}
      </Stagger>
    </>
  );
}

function ModeBadge({ agent }: { agent: Agent }) {
  const brands: BrandId[] =
    agent.mode === "direct" ? ["twilio", agent.stt_provider ?? "sarvam", "elevenlabs"] : agent.mode === "custom_brain" ? ["retell", "openai"] : ["retell"];
  const label = { managed: "Managed", custom_brain: "Custom Brain", direct: "Twilio pipeline" }[agent.mode];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-background py-0.5 pl-1 pr-2">
      <span className="flex">{brands.map((b, i) => <span key={b} className={i ? "-ml-1" : ""}><ProviderLogo id={b} size="xs" className="ring-1 ring-white" /></span>)}</span>
      {label}
    </span>
  );
}

"use client";

import Link from "next/link";
import { CallsTable } from "@/components/CallsTable";
import { CountUp, FadeIn, HoverCard, Skeleton, Stagger, StaggerItem } from "@/components/motion";
import { IconArrowRight, IconCheckCircle, IconClock, IconPhone, IconPlus, IconUser } from "@/components/icons";
import { Alert, PageHeader } from "@/components/ui";
import { api, type Call, type Stats } from "@/lib/api";
import { formatDuration, isActive } from "@/lib/format";
import { usePolling } from "@/lib/usePolling";

export default function DashboardPage() {
  const calls = usePolling(() => api<Call[]>("/calls?limit=8"), (d) => !!d?.some(isActive), 4000);
  const stats = usePolling(() => api<Stats>("/calls/stats"), () => !!calls.data?.some(isActive), 4000);
  const s = stats.data;

  const tiles = [
    { label: "Total Calls", value: s && <CountUp value={s.total_calls} />, icon: IconPhone, tint: "bg-sky-50 text-sky-600" },
    { label: "Completed", value: s && <CountUp value={s.completed} />, icon: IconCheckCircle, tint: "bg-emerald-50 text-emerald-600" },
    { label: "Interested", value: s && <CountUp value={s.interested} />, icon: IconUser, tint: "bg-orange-50 text-orange-500", sub: s ? `${s.goal_achieved} goal achieved` : undefined },
    {
      label: "Avg. Duration",
      value: s && (s.avg_duration_ms ? <CountUp value={s.avg_duration_ms} format={(n) => formatDuration(n)} /> : "—"),
      icon: IconClock,
      tint: "bg-zinc-100 text-zinc-600",
    },
  ];

  return (
    <>
      <FadeIn>
        <PageHeader
          title="Dashboard"
          subtitle="Create agents, make calls, and track results."
          actions={<Link href="/agents/new" className="btn-primary transition-transform hover:-translate-y-0.5"><IconPlus /> New Agent</Link>}
        />
      </FadeIn>
      {(calls.error || stats.error) && <div className="mb-4"><Alert>{calls.error ?? stats.error}</Alert></div>}

      <Stagger className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {tiles.map(({ label, value, icon: Icon, tint, sub }) => (
          <StaggerItem key={label}>
            <HoverCard className="card flex h-full items-start gap-3">
              <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-full ${tint}`}><Icon className="h-5 w-5" /></span>
              <div className="min-w-0">
                <div className="text-sm text-muted">{label}</div>
                <div className="mt-0.5 text-2xl font-semibold tabular-nums">{value ?? <Skeleton className="mt-1 h-6 w-12" />}</div>
                {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
              </div>
            </HoverCard>
          </StaggerItem>
        ))}
      </Stagger>

      <FadeIn delay={0.25} className="card">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-semibold">Recent Calls</h2>
          <Link href="/calls" className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline">View all <IconArrowRight /></Link>
        </div>
        {calls.data ? (
          <CallsTable calls={calls.data}
            empty={<>No calls yet. <Link href="/calls?new=1" className="font-medium text-accent hover:underline">Place your first call</Link>.</>} />
        ) : (
          <div className="space-y-3 py-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
        )}
      </FadeIn>
    </>
  );
}

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { CallOrb } from "@/components/CallOrb";
import { IconArrowLeft, IconPhoneOff, Waveform } from "@/components/icons";
import { FadeIn } from "@/components/motion";
import { Pipeline } from "@/components/Pipeline";
import { Transcript } from "@/components/Transcript";
import { Alert, Pill, Spinner } from "@/components/ui";
import { api, type CallDetail } from "@/lib/api";
import { callResult, formatClock, formatDateTime, formatDuration, GOAL_LABELS, humanize, isActive, parseDate } from "@/lib/format";
import { usePolling } from "@/lib/usePolling";

export default function CallPage() {
  const { id } = useParams<{ id: string }>();
  const { data: call, error, setData } = usePolling(
    () => api<CallDetail>(`/calls/${id}`),
    (c) => !!c && (isActive(c) || (c.status === "completed" && !c.summary && !c.goal_status)),
    2000,
  );

  if (!call) return error ? <Alert>{error}</Alert> : <p className="text-muted">Loading…</p>;
  return (
    <>
      <Link href="/calls" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground"><IconArrowLeft /> Back to Calls</Link>
      {isActive(call) ? <LiveCall call={call} onEnded={setData} /> : <CallAnalysis call={call} />}
    </>
  );
}

function useTicker(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

function LiveCall({ call, onEnded }: { call: CallDetail; onEnded: (c: CallDetail) => void }) {
  const now = useTicker(true);
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState<string>();
  const connected = call.status === "in_progress";
  const since = call.started_at ? parseDate(call.started_at).getTime() : null;
  const title = { queued: "Starting…", ringing: "Calling...", in_progress: "In call" }[call.status as "queued" | "ringing" | "in_progress"];

  async function endCall() {
    setEnding(true);
    setError(undefined);
    try {
      onEnded(await api<CallDetail>(`/calls/${call.id}/end`, { method: "POST" }));
    } catch (e) {
      setError((e as Error).message);
      setEnding(false);
    }
  }

  return (
    <div className="card relative overflow-hidden px-6 pb-8 pt-10">
      <motion.button whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.96 }} onClick={endCall} disabled={ending} className="btn-danger absolute right-5 top-5 z-10 py-2">
        {ending ? <Spinner /> : <IconPhoneOff />} End Call
      </motion.button>
      <div className="flex flex-col items-center text-center">
        <motion.h1 key={title} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="text-2xl font-semibold">{title}</motion.h1>
        <p className="mt-1 text-sm text-muted">{call.agent_name}</p>

        <div className="my-6">
          <CallOrb state={connected ? "connected" : "ringing"} />
        </div>

        <div className="text-xl font-semibold tabular-nums">{call.to_number}</div>
        {call.customer_name && <div className="text-sm text-muted">{call.customer_name}</div>}
        <div className="mt-1 font-mono text-muted tabular-nums">{since ? formatClock(now - since) : "00:00:00"}</div>
        <div className="mt-5"><Pipeline mode={call.mode} stt={call.stt_provider} live={connected} /></div>
      </div>
      {error && <div className="mt-6"><Alert>{error}</Alert></div>}

      <section className="mx-auto mt-8 max-w-2xl rounded-2xl border border-border bg-background/60 p-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium"><Waveform className="h-4 w-4 text-accent" /> Live transcript</div>
        <Transcript turns={call.transcript_object ?? []} live />
        {!call.transcript_object?.length && connected && (
          <p className="mt-2 text-xs text-muted">Live lines appear when webhooks or a Custom Brain mode are enabled; otherwise the full transcript shows when the call ends.</p>
        )}
      </section>
    </div>
  );
}

function CallAnalysis({ call }: { call: CallDetail }) {
  const result = callResult(call);
  // Analysis can still arrive only for completed calls that haven't been classified yet.
  const analysing = call.status === "completed" && !call.summary && !call.goal_status;
  const rows: [string, React.ReactNode][] = [
    ["Goal", call.goal_status ? GOAL_LABELS[call.goal_status] : analysing ? "Analysing…" : "—"],
    ["Customer interest", humanize(call.customer_interest)],
    ["Primary objection", call.primary_objection || "—"],
    ["Questions unanswered", call.unanswered_questions || (call.summary ? "None" : "—")],
    ["Follow-up requested", call.follow_up_requested == null ? "—" : call.follow_up_requested ? "Yes" : "No"],
    ["Preferred time", call.appointment_preference || "—"],
    ["Sentiment", humanize(call.sentiment)],
  ];
  const facts: [string, React.ReactNode][] = [
    ["Agent", <Link key="a" href={`/agents/${call.agent_id}`} className="hover:text-accent">{call.agent_name}</Link>],
    ["Mode", { managed: "Retell · Managed", custom_brain: "Retell + Custom Brain", direct: "Twilio + Custom Brain" }[call.mode]],
    ["To", call.to_number],
    ["From", call.from_number],
    ["Started", formatDateTime(call.started_at ?? call.created_at)],
    ["Duration", formatDuration(call.duration_ms)],
    ["Ended by", humanize(call.disconnection_reason)],
  ];

  return (
    <FadeIn>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight">{call.customer_name || call.to_number}</h1>
          <p className="mt-1 text-sm text-muted">Call analysis · {formatDateTime(call.created_at)}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Pill tone={result.tone}>{result.label}</Pill>
          <Pipeline mode={call.mode} stt={call.stt_provider} />
        </div>
      </div>
      {call.status === "failed" && <div className="mb-6"><Alert>Call failed: {call.error ?? humanize(call.disconnection_reason)}</Alert></div>}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="space-y-6">
          <section className="card">
            <h2 className="mb-4 font-semibold">Call analysis</h2>
            <dl className="space-y-3 text-sm">
              {rows.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4"><dt className="text-muted">{k}</dt><dd className="text-right font-medium">{v}</dd></div>
              ))}
            </dl>
            {call.next_action && (
              <div className="mt-5 rounded-xl bg-accent-soft p-3.5 text-sm">
                <div className="mb-0.5 text-xs font-semibold uppercase tracking-wide text-accent">Suggested next action</div>
                {call.next_action}
              </div>
            )}
            {call.key_notes && <p className="mt-4 border-t border-border pt-4 text-sm text-muted">{call.key_notes}</p>}
          </section>
          {call.mode === "direct" && call.diagnostics && <SpeechDiagnostics d={call.diagnostics} />}
          <section className="card">
            <h2 className="mb-4 font-semibold">Details</h2>
            <dl className="space-y-2.5 text-sm">
              {facts.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4"><dt className="text-muted">{k}</dt><dd className="text-right tabular-nums">{v}</dd></div>
              ))}
            </dl>
          </section>
        </div>
        <div className="space-y-6">
          <section className="card">
            <h2 className="mb-2 font-semibold">Summary</h2>
            <p className="text-sm leading-relaxed">{call.summary ?? (analysing ? "Analysing the call…" : "No summary.")}</p>
            {call.recording_url && <audio controls preload="none" src={call.recording_url} className="mt-4 w-full" />}
          </section>
          <section className="card">
            <h2 className="mb-4 font-semibold">Transcript</h2>
            <Transcript turns={call.transcript_object ?? []} />
          </section>
        </div>
      </div>
    </FadeIn>
  );
}

function SpeechDiagnostics({ d }: { d: NonNullable<CallDetail["diagnostics"]> }) {
  const rows: [string, React.ReactNode][] = [
    ["Provider", d.stt ? `${d.stt.provider === "sarvam" ? "Sarvam AI" : "OpenAI Whisper"} · ${d.stt.model}` : "—"],
    ["Chosen by", d.stt?.source === "agent" ? "Agent setting" : d.stt?.source === "fallback" ? "Fallback" : "Default"],
    ["Utterances", d.utterances ?? 0],
    ["Avg. transcript latency", d.avg_stt_latency_ms != null ? `${d.avg_stt_latency_ms} ms` : "—"],
    ["Avg. time to first audio", d.avg_first_audio_ms != null ? `${d.avg_first_audio_ms} ms` : "—"],
    ["Interruptions", d.interruptions ?? 0],
    ["Duplicates suppressed", d.duplicates_suppressed ?? 0],
  ];
  return (
    <section className="card">
      <h2 className="mb-4 font-semibold">Speech pipeline</h2>
      <dl className="space-y-2.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4"><dt className="text-muted">{k}</dt><dd className="text-right tabular-nums">{v}</dd></div>
        ))}
      </dl>
      {!!d.fallback_events?.length && (
        <div className="mt-4"><Alert kind="warning">
          Fell back from {d.fallback_events[0].from} to {d.fallback_events[0].to} ({d.fallback_events[0].reason.replace(/_/g, " ")}) before the call audio started.
        </Alert></div>
      )}
      {!!d.dropped_frames && <p className="mt-3 text-xs text-amber-700">{d.dropped_frames} audio frames dropped while speech-to-text was catching up.</p>}
    </section>
  );
}

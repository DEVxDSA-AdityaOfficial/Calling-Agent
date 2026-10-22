"use client";

import { useRef, useState } from "react";
import { api, type Options, type SimEvaluation, type SimTurnResult } from "@/lib/api";
import { humanize } from "@/lib/format";
import { IconFlask } from "./icons";
import { Alert, Pill, Spinner } from "./ui";

const MAX_AGENT_TURNS = 8;
type Line = { role: string; content: string };

export function Simulator({ agentId, personas }: { agentId: number; personas: Options["personas"] }) {
  const [persona, setPersona] = useState("interested");
  const [lines, setLines] = useState<Line[]>([]);
  const [running, setRunning] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluation, setEvaluation] = useState<SimEvaluation>();
  const [error, setError] = useState<string>();
  const stopRef = useRef(false);

  async function run() {
    stopRef.current = false;
    setRunning(true);
    setLines([]);
    setEvaluation(undefined);
    setError(undefined);
    let history: Line[] = [];
    try {
      for (let i = 0; i < MAX_AGENT_TURNS && !stopRef.current; i++) {
        const res = await api<SimTurnResult>(`/agents/${agentId}/simulate/turn`, {
          method: "POST",
          body: JSON.stringify({ persona, history }),
        });
        history = [...history, ...res.turns];
        setLines(history);
        if (res.ended) break;
      }
      setRunning(false);
      if (history.length) {
        setEvaluating(true);
        setEvaluation(await api<SimEvaluation>(`/agents/${agentId}/simulate/evaluate`, {
          method: "POST",
          body: JSON.stringify({ persona, history }),
        }));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
      setEvaluating(false);
    }
  }

  return (
    <section className="card">
      <div className="mb-1 flex items-center gap-2 font-semibold"><IconFlask className="text-accent" /> Test your agent</div>
      <p className="mb-4 text-sm text-muted">
        Your agent talks to an AI-played customer. No phone call is made. Then the conversation is scored.
      </p>
      <div className="mb-4 flex flex-wrap gap-2">
        {Object.entries(personas).map(([id, p]) => (
          <button key={id} type="button" disabled={running} onClick={() => setPersona(id)} title={p.description}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${persona === id ? "bg-ink text-white" : "bg-background text-muted ring-1 ring-border hover:text-foreground"}`}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        {running ? (
          <button type="button" className="btn-secondary" onClick={() => (stopRef.current = true)}><Spinner /> Stop</button>
        ) : (
          <button type="button" className="btn-primary" onClick={run} disabled={evaluating}><IconFlask /> {lines.length ? "Run again" : "Start simulation"}</button>
        )}
      </div>
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}

      {lines.length > 0 && (
        <ol className="mt-5 space-y-3 rounded-2xl bg-background p-4">
          {lines.map((l, i) => (
            <li key={i} className={`flex ${l.role === "agent" ? "" : "justify-end"}`}>
              <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${l.role === "agent" ? "rounded-bl-md bg-surface ring-1 ring-border" : "rounded-br-md bg-ink text-white"}`}>
                <div className={`mb-0.5 text-[11px] font-semibold uppercase tracking-wide ${l.role === "agent" ? "text-accent" : "text-zinc-400"}`}>
                  {l.role === "agent" ? "Your agent" : personas[persona]?.label ?? "Customer"}
                </div>
                {l.content}
              </div>
            </li>
          ))}
          {running && <li className="text-xs text-muted"><Spinner className="mr-2 h-3 w-3" />Thinking…</li>}
        </ol>
      )}

      {evaluating && <p className="mt-4 text-sm text-muted"><Spinner className="mr-2 h-3 w-3" />Scoring the conversation…</p>}
      {evaluation && (
        <div className="mt-5 space-y-4">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold">Evaluation</h3>
            <Pill tone={evaluation.goal_achieved ? "green" : "gray"}>{evaluation.goal_achieved ? "Goal achieved" : "Goal not achieved"}</Pill>
          </div>
          {evaluation.summary && <p className="text-sm text-muted">{evaluation.summary}</p>}
          <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {Object.entries(evaluation.scores).map(([k, v]) => (
              <div key={k}>
                <div className="mb-1 flex justify-between text-sm"><span>{humanize(k)}</span><span className="tabular-nums text-muted">{v ?? "–"}/5</span></div>
                <div className="h-1.5 rounded-full bg-background">
                  <div className={`h-full rounded-full ${(v ?? 0) >= 4 ? "bg-emerald-500" : (v ?? 0) >= 3 ? "bg-amber-400" : "bg-rose-400"}`} style={{ width: `${((v ?? 0) / 5) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
          {evaluation.unsupported_claims.length > 0 && (
            <Alert kind="warning"><b>Unsupported claims:</b> {evaluation.unsupported_claims.join(" · ")}</Alert>
          )}
          {evaluation.improvements.length > 0 && (
            <div className="rounded-xl bg-accent-soft p-4 text-sm">
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-accent">Suggested improvements</div>
              <ul className="list-disc space-y-1 pl-5">{evaluation.improvements.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

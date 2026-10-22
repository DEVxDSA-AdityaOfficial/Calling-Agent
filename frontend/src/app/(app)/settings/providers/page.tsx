"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { IconBrain, IconChevronRight } from "@/components/icons";
import { DrawCheck, EASE, FadeIn, Skeleton, Stagger, StaggerItem } from "@/components/motion";
import { isBrand, ProviderLogo } from "@/components/ProviderLogo";
import { Alert, PageHeader, Pill, Spinner } from "@/components/ui";
import { api, type Options, type Provider, type SpeechSettings, type SttProviderId, type TranscriptionResult } from "@/lib/api";
import { formatRelative } from "@/lib/format";

const GROUPS = [
  { title: "Telephony", ids: ["twilio"] },
  { title: "Voice & calling", ids: ["retell", "elevenlabs"] },
  { title: "Speech recognition", ids: ["whisper", "sarvam"], speech: true },
  { title: "Conversation engine", ids: ["openai"], engine: true },
];

export default function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>();
  const [options, setOptions] = useState<Options>();
  const [speech, setSpeech] = useState<SpeechSettings>();
  const [error, setError] = useState<string>();

  const loadSpeech = () => api<SpeechSettings>("/speech/settings").then(setSpeech).catch(() => {});
  useEffect(() => {
    api<Provider[]>("/providers").then(setProviders).catch((e) => setError(e.message));
    api<Options>("/options").then(setOptions).catch(() => {});
    loadSpeech();
  }, []);

  const update = (p: Provider) => {
    setProviders((list) => list?.map((x) => (x.id === p.id ? p : x)));
    if (p.id === "whisper" || p.id === "sarvam" || p.id === "openai") loadSpeech();
  };
  const engine = options?.conversation_engine;
  const openai = providers?.find((p) => p.id === "openai");

  return (
    <>
      <FadeIn>
        <PageHeader title="API & Providers" subtitle="Connect your own provider accounts. Keys are encrypted at rest and never shown again in full." />
      </FadeIn>
      {error && <Alert>{error}</Alert>}
      {!providers && !error && (
        <div className="space-y-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20 w-full rounded-2xl" />)}</div>
      )}
      {providers && (
        <Stagger className="space-y-9" gap={0.08}>
          {GROUPS.map((g) => (
            <StaggerItem key={g.title}>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{g.title}</h2>
              {g.speech && (
                <p className="-mt-1 mb-3 text-sm text-muted">
                  Transcribes the caller for agents in <b className="font-medium text-foreground">Twilio + Custom Brain</b> mode.
                  Retell agents use Retell&apos;s own speech recognition.
                </p>
              )}
              <div className="space-y-4">
                {g.ids.map((id) => {
                  const p = providers.find((x) => x.id === id);
                  return p ? <ProviderCard key={id} provider={p} onChange={update} /> : null;
                })}
                {g.speech && speech && <SpeechDefaults settings={speech} onChange={setSpeech} />}
                {g.speech && speech && (speech.connected.whisper || speech.connected.sarvam) && <TryTranscription settings={speech} />}
                {g.engine && engine && (
                  <div className="flex items-start gap-3 rounded-2xl border border-dashed border-border p-4 text-sm">
                    <IconBrain className="mt-0.5 shrink-0 text-accent" />
                    <div>
                      <div className="font-medium">
                        Active engine:{" "}
                        {engine.provider === "local_slm"
                          ? `Local SLM · ${engine.model}`
                          : `OpenAI · ${openai?.fields.find((f) => f.key === "model")?.value || engine.model}`}
                      </div>
                      <p className="mt-0.5 text-muted">
                        {engine.provider === "local_slm"
                          ? `Self-hosted model at ${engine.base_url}.`
                          : openai?.status === "connected"
                            ? "Using your OpenAI connection above."
                            : engine.platform_key
                              ? "Using the platform-managed key. Adding your own key above overrides it."
                              : "No platform key configured: add your OpenAI key above."}{" "}
                        Switch engines with <code>CONVERSATION_PROVIDER=openai|local_slm</code> on the backend.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </StaggerItem>
          ))}
        </Stagger>
      )}
    </>
  );
}

function StatusPill({ status }: { status: Provider["status"] }) {
  const map = {
    connected: <Pill tone="green">Connected</Pill>,
    error: <Pill tone="red">Failed</Pill>,
    untested: <Pill tone="amber">Not tested</Pill>,
    not_configured: <Pill tone="gray">Not connected</Pill>,
  };
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span key={status} initial={{ opacity: 0, scale: 0.85 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.85 }} transition={{ duration: 0.25, ease: EASE }}>
        {map[status]}
      </motion.span>
    </AnimatePresence>
  );
}

function ProviderCard({ provider, onChange }: { provider: Provider; onChange: (p: Provider) => void }) {
  const initial = () => Object.fromEntries(provider.fields.map((f) => [f.key, f.value ?? (f.kind === "select" ? f.options[0]?.value ?? "" : "")]));
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [open, setOpen] = useState(!provider.configured);
  const [busy, setBusy] = useState<"save" | "test" | "remove">();
  const [error, setError] = useState<string>();
  const [justConnected, setJustConnected] = useState(false);

  async function act(kind: "save" | "test" | "remove") {
    setBusy(kind);
    setError(undefined);
    try {
      let result: Provider;
      if (kind === "remove") result = await api<Provider>(`/providers/${provider.id}`, { method: "DELETE" });
      else if (kind === "save") result = await api<Provider>(`/providers/${provider.id}`, { method: "PUT", body: JSON.stringify({ values }) });
      else result = await api<Provider>(`/providers/${provider.id}/test`, { method: "POST" });
      onChange(result);
      setValues(Object.fromEntries(result.fields.map((f) => [f.key, f.value ?? (f.kind === "select" ? f.options[0]?.value ?? "" : "")])));
      if (result.status === "connected" && provider.status !== "connected") {
        setJustConnected(true);
        setTimeout(() => setJustConnected(false), 2200);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(undefined);
    }
  }

  return (
    <motion.section layout className="card" transition={{ layout: { duration: 0.35, ease: EASE } }}>
      <button type="button" className="flex w-full items-center gap-3 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        {isBrand(provider.id) ? <ProviderLogo id={provider.id} /> : null}
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 font-semibold">
            {provider.name}
            <AnimatePresence>
              {justConnected && (
                <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0, opacity: 0 }}
                  className="grid h-5 w-5 place-items-center rounded-full bg-emerald-500 text-white">
                  <DrawCheck className="h-3 w-3" />
                </motion.span>
              )}
            </AnimatePresence>
          </span>
          <span className="block truncate text-sm text-muted">{provider.purpose}</span>
        </span>
        <StatusPill status={provider.status} />
        <motion.span animate={{ rotate: open ? 90 : 0 }} transition={{ duration: 0.25, ease: EASE }} className="text-muted">
          <IconChevronRight />
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.35, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="mt-5 space-y-4 border-t border-border pt-5">
              <div className="grid gap-4 sm:grid-cols-2">
                {provider.fields.map((f) => (
                  <div key={f.key}>
                    <label className="label" htmlFor={`${provider.id}-${f.key}`}>{f.label}</label>
                    {f.kind === "select" ? (
                      <select id={`${provider.id}-${f.key}`} className="input" value={values[f.key] ?? ""}
                        onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}>
                        {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    ) : (
                      // Plain text inputs (secrets visually masked) so password managers don't autofill a login here.
                      <input id={`${provider.id}-${f.key}`} name={`${provider.id}-${f.key}`} type="text"
                        className={`input font-mono ${f.secret ? "[-webkit-text-security:disc]" : ""}`}
                        autoComplete="off" data-1p-ignore data-lpignore="true" spellCheck={false}
                        placeholder={f.placeholder} value={values[f.key] ?? ""}
                        onFocus={(e) => f.secret && e.target.value.startsWith("•") && setValues((v) => ({ ...v, [f.key]: "" }))}
                        onBlur={(e) => f.secret && !e.target.value && setValues((v) => ({ ...v, [f.key]: f.value ?? "" }))}
                        onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} />
                    )}
                    {f.help && <p className="hint">{f.help}</p>}
                  </div>
                ))}
              </div>
              {provider.status_detail && (
                <p className={`text-sm ${provider.status === "error" ? "text-rose-600" : "text-muted"}`}>
                  {provider.status_detail}
                  {provider.last_tested_at && <span className="text-muted"> · tested {formatRelative(provider.last_tested_at)}</span>}
                  {provider.secrets_rotated_at && <span className="text-muted"> · key updated {formatRelative(provider.secrets_rotated_at)}</span>}
                </p>
              )}
              {provider.note && <p className="text-xs leading-relaxed text-muted">{provider.note}</p>}
              {error && <Alert>{error}</Alert>}
              <div className="flex flex-wrap gap-2">
                <motion.button whileTap={{ scale: 0.97 }} type="button" className="btn-primary" disabled={!!busy} onClick={() => act("save")}>
                  {busy === "save" && <Spinner />} {provider.configured ? "Save & test" : "Connect"}
                </motion.button>
                <motion.button whileTap={{ scale: 0.97 }} type="button" className="btn-secondary" disabled={!!busy || !provider.configured} onClick={() => act("test")}>
                  {busy === "test" && <Spinner />} Test connection
                </motion.button>
                {provider.configured && (
                  <button type="button" className="btn ml-auto text-rose-600 hover:bg-rose-50" disabled={!!busy} onClick={() => act("remove")}>
                    Disconnect
                  </button>
                )}
              </div>
              {provider.configured && provider.status === "connected" && (
                <p className="text-xs text-muted">Replacing a key? The new one is tested first; if it fails, the working key is kept.</p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}

const SPEECH: { id: SttProviderId; name: string; blurb: string }[] = [
  { id: "sarvam", name: "Sarvam AI", blurb: "Best for Hindi, Hinglish & Indian languages" },
  { id: "whisper", name: "OpenAI Whisper", blurb: "Broad multilingual coverage" },
];

function SpeechDefaults({ settings, onChange }: { settings: SpeechSettings; onChange: (s: SpeechSettings) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();

  async function save(next: Partial<SpeechSettings>) {
    setSaving(true);
    setError(undefined);
    try {
      onChange(await api<SpeechSettings>("/speech/settings", {
        method: "PUT",
        body: JSON.stringify({ default_provider: settings.default_provider, fallback_enabled: settings.fallback_enabled, ...next }),
      }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card">
      <div className="mb-1 flex items-center gap-2 font-semibold">Default speech provider {saving && <Spinner className="h-3 w-3 text-muted" />}</div>
      <p className="mb-4 text-sm text-muted">Used by Twilio + Custom Brain agents unless the agent picks its own. A call keeps the same provider until it ends.</p>
      <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Default speech provider">
        {SPEECH.map((s) => {
          const active = settings.default_provider === s.id;
          const connected = settings.connected[s.id];
          return (
            <motion.button key={s.id} type="button" role="radio" aria-checked={active} disabled={!connected || saving}
              whileHover={connected ? { y: -2 } : undefined} whileTap={connected ? { scale: 0.98 } : undefined}
              onClick={() => save({ default_provider: s.id })}
              className={`relative flex items-center gap-3 rounded-xl border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${active ? "border-accent bg-accent-soft/60" : "border-border hover:border-zinc-300"}`}>
              {active && <motion.span layoutId="stt-default" className="absolute inset-0 rounded-xl ring-4 ring-accent/15" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
              <ProviderLogo id={s.id} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{s.name}</span>
                <span className="block text-xs text-muted">{connected ? s.blurb : "Connect it above first"}</span>
              </span>
              <span className={`grid h-5 w-5 place-items-center rounded-full border-2 ${active ? "border-accent" : "border-zinc-300"}`}>
                {active && <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} className="h-2.5 w-2.5 rounded-full bg-accent" />}
              </span>
            </motion.button>
          );
        })}
      </div>
      <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm">
        <button type="button" role="switch" aria-checked={settings.fallback_enabled} disabled={saving}
          onClick={() => save({ fallback_enabled: !settings.fallback_enabled })}
          className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${settings.fallback_enabled ? "bg-accent" : "bg-zinc-300"}`}>
          <motion.span layout transition={{ type: "spring", stiffness: 500, damping: 32 }}
            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow ${settings.fallback_enabled ? "right-0.5" : "left-0.5"}`} />
        </button>
        <span>
          <span className="font-medium">Fall back to the other provider</span>
          <span className="block text-xs text-muted">Only if the chosen provider can&apos;t connect when a call starts. Never switches mid-call. Fallbacks are recorded on the call.</span>
        </span>
      </label>
      {error && <div className="mt-3"><Alert>{error}</Alert></div>}
    </section>
  );
}

function TryTranscription({ settings }: { settings: SpeechSettings }) {
  const connected = SPEECH.filter((s) => settings.connected[s.id]);
  const [provider, setProvider] = useState<SttProviderId>(settings.default_provider && settings.connected[settings.default_provider] ? settings.default_provider : connected[0].id);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TranscriptionResult & { roundtrip_ms: number }>();
  const [error, setError] = useState<string>();
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  async function send(blob: Blob, name: string) {
    setBusy(true);
    setError(undefined);
    setResult(undefined);
    const form = new FormData();
    form.append("provider", provider);
    form.append("audio", blob, name);
    const started = performance.now();
    try {
      const r = await api<TranscriptionResult>("/speech/test-transcription", { method: "POST", body: form });
      setResult({ ...r, roundtrip_ms: Math.round(performance.now() - started) });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleRecording() {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "" });
      chunks.current = [];
      rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      rec.onstop = () => {
        clearTimeout(timer.current);
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        void send(new Blob(chunks.current, { type: "audio/webm" }), "clip.webm");
      };
      recorder.current = rec;
      rec.start();
      setRecording(true);
      timer.current = setTimeout(() => rec.state === "recording" && rec.stop(), 15000);
    } catch {
      setError("Microphone access was blocked. Allow it in the browser, or upload a clip instead.");
    }
  }

  return (
    <section className="card">
      <div className="mb-1 font-semibold">Try a transcription</div>
      <p className="mb-4 text-sm text-muted">
        Speak or upload up to 15&nbsp;s of audio to check accuracy and latency with your own keys. This sends a real request,
        billed by the provider (Whisper uses <code>whisper-1</code> for clips).
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Provider" className="input w-auto" value={provider} onChange={(e) => setProvider(e.target.value as SttProviderId)}>
          {connected.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <motion.button whileTap={{ scale: 0.96 }} type="button" onClick={toggleRecording} disabled={busy}
          className={`btn ${recording ? "bg-rose-600 text-white" : "btn-primary"}`}>
          <span className="relative flex h-2.5 w-2.5">
            {recording && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white/80" />}
            <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${recording ? "bg-white" : "bg-rose-500"}`} />
          </span>
          {recording ? "Stop & transcribe" : "Record"}
        </motion.button>
        <label className="btn-secondary cursor-pointer">
          Upload clip
          <input type="file" accept="audio/*" className="sr-only" disabled={busy}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void send(f, f.name); e.target.value = ""; }} />
        </label>
        {busy && <span className="flex items-center gap-2 text-sm text-muted"><Spinner /> Transcribing…</span>}
      </div>
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}
      <AnimatePresence>
        {result && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.4, ease: EASE }}
            className="mt-4 rounded-xl bg-background p-4">
            <p className="text-base">{result.text || <span className="text-muted">No speech detected.</span>}</p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              <span>{result.model}</span>
              {result.language && <span>Language: {result.language}{result.language_confidence != null && ` (${Math.round(result.language_confidence * 100)}%)`}</span>}
              {result.latency_ms != null && <span>Provider latency: {result.latency_ms} ms</span>}
              <span>Round trip: {result.roundtrip_ms} ms</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

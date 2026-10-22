"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { api, type Agent, type AgentInput, type AgentMode, type Options, type Playbook, type SpeechSettings, type SttProviderId, type Voice } from "@/lib/api";
import { EASE } from "./motion";
import { type BrandId, ProviderLogo } from "./ProviderLogo";
import { IconArrowLeft, IconArrowRight, IconCheck, IconPhone, IconShield, IconSparkles } from "./icons";
import { PlaybookEditor } from "./PlaybookEditor";
import { Simulator } from "./Simulator";
import { Alert, Counter, Pill, Spinner } from "./ui";

const EXAMPLE = {
  objective: "Book product demos with interested restaurant owners",
  target_audience: "Restaurant owners in Indore",
  script:
    "You are calling on behalf of RecursX, an AI automation company.\n\n" +
    "1. Greet the customer and confirm it's a good time to talk.\n" +
    "2. Briefly introduce our services (AI calling, WhatsApp automation).\n" +
    "3. Understand how they take orders and handle customer queries today.\n" +
    "4. Explain how we can help, based on what they said.\n" +
    "5. Ask if they'd like a product demo.",
  additional_context:
    "Product: AI Ordering Agent\nMonthly price: ₹2,499\nFeatures: WhatsApp ordering, voice-based ordering, customer query handling\nSetup takes 2 days. No hardware needed.",
  dos_and_donts:
    "Do not invent discounts.\nDo not promise unsupported features (e.g. POS integrations).\nDo not place orders without the customer's confirmation.",
  success_condition: "The customer shares a preferred day and time for a demo",
};

const EMPTY: AgentInput = {
  name: "",
  business_name: "",
  mode: "managed",
  objective: "",
  target_audience: "",
  success_condition: "",
  fallback_behavior: "",
  max_duration_minutes: 3,
  script: "",
  additional_context: "",
  dos_and_donts: "",
  playbook: null,
  language: "en-IN",
  voice_provider: null,
  voice_id: "",
  stt_provider: null,
  tone: "friendly",
  opening_line: "",
};

const STEPS = ["Basics", "Script & Context", "Review & Test"];

function toInput(agent: Agent): AgentInput {
  const keys = Object.keys(EMPTY) as (keyof AgentInput)[];
  return Object.fromEntries(keys.map((k) => [k, agent[k] ?? EMPTY[k]])) as AgentInput;
}

function emptyToNull(form: AgentInput): AgentInput {
  const out = { ...form };
  for (const k of ["target_audience", "success_condition", "fallback_behavior", "additional_context", "dos_and_donts", "opening_line"] as const) {
    out[k] = form[k]?.trim() ? form[k] : null;
  }
  return out;
}

export function AgentBuilder({ agent }: { agent?: Agent }) {
  const router = useRouter();
  const [step, setStep] = useState(agent ? 2 : 0);
  const [form, setForm] = useState<AgentInput>(agent ? toInput(agent) : EMPTY);
  const [saved, setSaved] = useState<Agent | undefined>(agent);
  const [options, setOptions] = useState<Options>();
  const [voices, setVoices] = useState<Voice[]>();
  const [voiceError, setVoiceError] = useState<string>();
  const [preview, setPreview] = useState<{ prompt: string; begin_message: string | null } | undefined>(
    agent ? { prompt: agent.generated_prompt, begin_message: agent.begin_message } : undefined,
  );
  const [busy, setBusy] = useState<"save" | "playbook" | "preview">();
  const [error, setError] = useState<string>();
  const [dirty, setDirty] = useState(false);

  const [speech, setSpeech] = useState<SpeechSettings>();

  /** Retell's catalogue for Retell modes; the user's own ElevenLabs library for the Twilio pipeline. */
  function loadVoices(mode: AgentMode, keepCurrent: boolean) {
    api<Voice[]>(`/voices?source=${mode === "direct" ? "elevenlabs" : "retell"}`)
      .then((list) => {
        setVoices(list);
        setVoiceError(undefined);
        const preferred = list.find((v) => v.provider === "elevenlabs") ?? list[0];
        setForm((f) => {
          if (keepCurrent && f.voice_id && list.some((v) => v.voice_id === f.voice_id)) return f;
          if (keepCurrent && f.voice_id && !preferred) return f;
          return preferred ? { ...f, voice_provider: preferred.provider, voice_id: preferred.voice_id } : { ...f, voice_id: "" };
        });
      })
      .catch((e) => setVoiceError(e.message));
  }

  useEffect(() => {
    api<Options>("/options").then(setOptions).catch((e) => setError(e.message));
    api<SpeechSettings>("/speech/settings").then(setSpeech).catch(() => {});
    loadVoices(agent?.mode ?? "managed", true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setMode(mode: AgentMode) {
    const switchesVoiceSource = (mode === "direct") !== (form.mode === "direct");
    set("mode", mode);
    if (switchesVoiceSource) {
      setVoices(undefined);
      loadVoices(mode, false);
    }
  }

  const providers = useMemo(() => [...new Set((voices ?? []).map((v) => v.provider))].sort(), [voices]);
  const voiceProvider = form.voice_provider ?? voices?.find((v) => v.voice_id === form.voice_id)?.provider ?? providers[0];
  const providerVoices = (voices ?? []).filter((v) => v.provider === voiceProvider);
  const selectedVoice = voices?.find((v) => v.voice_id === form.voice_id);

  function set<K extends keyof AgentInput>(key: K, value: AgentInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setDirty(true);
  }

  const stepValid = [
    !!(form.name.trim() && form.business_name.trim() && form.objective.trim().length >= 3 && form.voice_id),
    form.script.trim().length >= 20,
    true,
  ];

  async function generatePlaybook() {
    setBusy("playbook");
    setError(undefined);
    try {
      set("playbook", await api<Playbook>("/agents/playbook", { method: "POST", body: JSON.stringify(emptyToNull(form)) }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(undefined);
    }
  }

  async function loadPreview() {
    setBusy("preview");
    try {
      setPreview(await api("/agents/preview", { method: "POST", body: JSON.stringify(emptyToNull(form)) }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(undefined);
    }
  }

  async function save() {
    setBusy("save");
    setError(undefined);
    try {
      const result = await api<Agent>(saved ? `/agents/${saved.id}` : "/agents", {
        method: saved ? "PUT" : "POST",
        body: JSON.stringify(emptyToNull(form)),
      });
      setSaved(result);
      setDirty(false);
      setPreview({ prompt: result.generated_prompt, begin_message: result.begin_message });
      if (!saved) router.replace(`/agents/${result.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(undefined);
    }
  }

  function fillExample() {
    setForm((f) => ({
      ...f,
      name: f.name || "RecursX Sales Agent",
      business_name: f.business_name || "RecursX",
      ...EXAMPLE,
      language: "hinglish",
    }));
    setDirty(true);
  }

  function goTo(next: number) {
    setStep(next);
    if (next === 2 && !preview) void loadPreview();
  }

  return (
    <div className="mx-auto max-w-4xl">
      <Link href="/agents" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground"><IconArrowLeft /> Agents</Link>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight">{saved ? saved.name : "Create Agent"}</h1>
          <p className="mt-1 text-sm text-muted">
            {saved ? `${saved.business_name} · define how your agent should behave and what it should say.` : "Define how your agent should behave and what it should say."}
          </p>
        </div>
        <span className="text-sm text-muted">Step {step + 1} of {STEPS.length}</span>
      </div>

      <div className="mb-6 flex gap-6 border-b border-border text-sm">
        {STEPS.map((label, i) => {
          const reachable = !!saved || stepValid.slice(0, i).every(Boolean);
          return (
            <button key={label} type="button" disabled={!reachable} onClick={() => goTo(i)}
              className={`-mb-px flex items-center gap-2 border-b-2 pb-3 font-medium transition disabled:opacity-40 ${step === i ? "border-accent text-foreground" : "border-transparent text-muted hover:text-foreground"}`}>
              <span className={`grid h-5 w-5 place-items-center rounded-full text-[11px] ${step > i || (saved && step !== i) ? "bg-emerald-100 text-emerald-700" : step === i ? "bg-accent text-white" : "bg-zinc-100"}`}>
                {step > i ? <IconCheck /> : i + 1}
              </span>
              {label}
            </button>
          );
        })}
      </div>

      {error && <div className="mb-4"><Alert>{error}</Alert></div>}

      {step === 0 && (
        <section className="card space-y-5">
          {!saved && (
            <div className="flex items-center justify-between rounded-xl bg-accent-soft px-4 py-3 text-sm">
              <span>New here? Start from the RecursX restaurant example.</span>
              <button type="button" className="font-medium text-accent hover:underline" onClick={fillExample}>Use example</button>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <div className="flex justify-between"><label className="label" htmlFor="name">Agent Name</label><Counter value={form.name} max={50} /></div>
              <input id="name" className="input" maxLength={50} placeholder="RecursX Sales Agent" value={form.name} onChange={(e) => set("name", e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="business">Business Name</label>
              <input id="business" className="input" maxLength={200} placeholder="RecursX" value={form.business_name} onChange={(e) => set("business_name", e.target.value)} />
            </div>
          </div>
          <div>
            <div className="flex justify-between"><label className="label" htmlFor="objective">Calling Objective</label><Counter value={form.objective} max={500} /></div>
            <textarea id="objective" className="input min-h-20" maxLength={500} placeholder="Call potential customers, introduce our AI automation services, understand their requirements and book a product demo."
              value={form.objective} onChange={(e) => set("objective", e.target.value)} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="language">Language</label>
              <select id="language" className="input" value={form.language} onChange={(e) => set("language", e.target.value)}>
                {Object.entries(options?.languages ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="tone">Conversation Tone</label>
              <select id="tone" className="input capitalize" value={form.tone} onChange={(e) => set("tone", e.target.value)}>
                {Object.keys(options?.tones ?? { friendly: "" }).map((k) => <option key={k} value={k} className="capitalize">{k}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="label">Voice Provider</label>
            {voiceError ? (
              <>
                <input className="input" placeholder={form.mode === "direct" ? "ElevenLabs voice_id" : "Retell voice_id"} value={form.voice_id} onChange={(e) => set("voice_id", e.target.value)} />
                <p className="hint text-rose-600">
                  Couldn&apos;t load voices ({voiceError}). {form.mode === "direct" ? "Connect ElevenLabs" : "Connect Retell"} in Settings, or enter a voice ID.
                </p>
              </>
            ) : form.mode === "direct" ? (
              <div className="grid gap-3 sm:grid-cols-[1fr_1.4fr]">
                <div className="input flex items-center gap-2 bg-background"><ProviderLogo id="elevenlabs" size="xs" /> ElevenLabs (your account)</div>
                <select aria-label="Voice" className="input" disabled={!voices} value={form.voice_id} onChange={(e) => set("voice_id", e.target.value)}>
                  {!voices && <option>Loading…</option>}
                  {voices?.map((v) => (
                    <option key={v.voice_id} value={v.voice_id}>{v.voice_name}{v.accent || v.gender ? ` (${[v.gender, v.accent].filter(Boolean).join(", ")})` : ""}</option>
                  ))}
                </select>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-[1fr_1.4fr]">
                <select aria-label="Voice provider" className="input capitalize" disabled={!voices} value={voiceProvider ?? ""}
                  onChange={(e) => {
                    const first = voices?.find((v) => v.provider === e.target.value);
                    setForm((f) => ({ ...f, voice_provider: e.target.value, voice_id: first?.voice_id ?? "" }));
                    setDirty(true);
                  }}>
                  {!voices && <option>Loading…</option>}
                  {providers.map((p) => <option key={p} value={p}>{p === "elevenlabs" ? "ElevenLabs" : p}</option>)}
                </select>
                <select aria-label="Voice" className="input" disabled={!voices} value={form.voice_id} onChange={(e) => set("voice_id", e.target.value)}>
                  {providerVoices.map((v) => (
                    <option key={v.voice_id} value={v.voice_id}>{v.voice_name} ({[v.gender, v.accent].filter(Boolean).join(", ")})</option>
                  ))}
                </select>
              </div>
            )}
            {selectedVoice?.preview_audio_url && <audio controls preload="none" src={selectedVoice.preview_audio_url} className="mt-2 h-9 w-full" />}
          </div>
          <div>
            <label className="label">Calling Provider</label>
            <div className="grid gap-3 lg:grid-cols-3">
              <ModeCard mode="managed" current={form.mode} onSelect={setMode} brands={["retell"]}
                title="Retell · Managed" body="Retell runs telephony, speech and the conversation. Simplest setup." />
              <ModeCard mode="custom_brain" current={form.mode} onSelect={setMode} brands={["retell", "openai"]}
                disabled={options && !options.custom_brain_available}
                title={`Retell + Custom Brain`}
                body={`Retell handles the call and voice; ${options?.conversation_engine.provider === "local_slm" ? "your local SLM" : "OpenAI"} writes every reply.`} />
              <ModeCard mode="direct" current={form.mode} onSelect={setMode} brands={["twilio", "sarvam", "whisper", "elevenlabs"]}
                disabled={options && !options.direct_available}
                title="Twilio + Custom Brain"
                body="Twilio audio → Whisper or Sarvam speech-to-text → our engine → ElevenLabs voice. Full control." />
            </div>
            {options && !options.custom_brain_available && (
              <p className="hint">Custom Brain modes need <code>PUBLIC_BASE_URL</code> on the backend so Retell/Twilio can reach this server.</p>
            )}
          </div>
          {form.mode === "direct" && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} transition={{ duration: 0.35, ease: EASE }} className="overflow-hidden">
              <label className="label">Speech recognition</label>
              <div className="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Speech recognition provider">
                {([
                  [null, `Default${speech?.default_provider ? ` (${speech.default_provider === "sarvam" ? "Sarvam AI" : "Whisper"})` : ""}`, speech?.default_provider ?? null],
                  ["sarvam", "Sarvam AI", "sarvam"],
                  ["whisper", "OpenAI Whisper", "whisper"],
                ] as [SttProviderId | null, string, SttProviderId | null][]).map(([value, label, logo]) => {
                  const active = form.stt_provider === value;
                  const unavailable = value ? speech && !speech.connected[value] : speech && !speech.default_provider;
                  return (
                    <button key={label} type="button" role="radio" aria-checked={active} onClick={() => set("stt_provider", value)}
                      className={`relative flex items-center gap-2.5 rounded-xl border p-3 text-left text-sm transition-colors ${active ? "border-accent bg-accent-soft/60" : "border-border hover:border-zinc-300"}`}>
                      {active && <motion.span layoutId="stt-pick" className="absolute inset-0 rounded-xl ring-4 ring-accent/15" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
                      {logo ? <ProviderLogo id={logo} size="sm" /> : <span className="grid h-7 w-7 place-items-center rounded-lg bg-zinc-100 text-xs text-muted">—</span>}
                      <span className="min-w-0">
                        <span className="block font-medium">{label}</span>
                        {unavailable && <span className="block text-xs text-amber-600">{value ? "Not connected" : "No default set"}</span>}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="hint">The agent&apos;s choice overrides your default. Sarvam handles Hinglish and Indian languages best.</p>
            </motion.div>
          )}
        </section>
      )}

      {step === 1 && (
        <section className="card space-y-5">
          <div>
            <div className="flex justify-between"><label className="label" htmlFor="script">Conversation Script</label><Counter value={form.script} max={8000} /></div>
            <textarea id="script" className="input min-h-48 leading-relaxed" maxLength={8000}
              placeholder="Describe what the agent should communicate and accomplish. Write it as a brief, not word-for-word lines."
              value={form.script} onChange={(e) => set("script", e.target.value)} />
          </div>
          <div>
            <div className="flex justify-between"><label className="label" htmlFor="context">Additional Context <span className="font-normal text-muted">(optional)</span></label><Counter value={form.additional_context} max={8000} /></div>
            <textarea id="context" className="input min-h-28" maxLength={8000} placeholder="Product details, pricing, FAQs, company information…"
              value={form.additional_context ?? ""} onChange={(e) => set("additional_context", e.target.value)} />
            <p className="hint">The agent only states facts from the script and this section.</p>
          </div>
          <div>
            <div className="flex justify-between">
              <label className="label flex items-center gap-1.5" htmlFor="rules"><IconShield className="text-accent" /> Do&apos;s and Don&apos;ts <span className="font-normal text-muted">(optional)</span></label>
              <Counter value={form.dos_and_donts} max={3000} />
            </div>
            <textarea id="rules" className="input min-h-24" maxLength={3000} placeholder="e.g. Do not offer discounts. Do not make fake promises."
              value={form.dos_and_donts ?? ""} onChange={(e) => set("dos_and_donts", e.target.value)} />
          </div>

          <div className="border-t border-border pt-5">
            <h3 className="mb-1 font-semibold">Goal &amp; call settings</h3>
            <p className="mb-4 text-sm text-muted">How you measure this call. After each call we report: goal achieved, interested, not interested, no response, or failed.</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="audience">Target audience</label>
                <input id="audience" className="input" placeholder="Restaurant owners" value={form.target_audience ?? ""} onChange={(e) => set("target_audience", e.target.value)} />
              </div>
              <div>
                <label className="label" htmlFor="success">Success condition</label>
                <input id="success" className="input" placeholder="Customer shares a preferred demo time" value={form.success_condition ?? ""} onChange={(e) => set("success_condition", e.target.value)} />
              </div>
              <div>
                <label className="label" htmlFor="fallback">If not interested</label>
                <input id="fallback" className="input" placeholder="Thank them and close politely" value={form.fallback_behavior ?? ""} onChange={(e) => set("fallback_behavior", e.target.value)} />
              </div>
              <div>
                <label className="label" htmlFor="duration">Maximum duration</label>
                <select id="duration" className="input" value={form.max_duration_minutes} onChange={(e) => set("max_duration_minutes", Number(e.target.value))}>
                  {[2, 3, 5, 8, 10, 15].map((m) => <option key={m} value={m}>{m} minutes</option>)}
                </select>
              </div>
            </div>
            <p className="hint mt-3">A preferred time is a request, not a confirmed booking. The agent tells customers the team will confirm.</p>
          </div>
        </section>
      )}

      {step === 2 && (
        <div className="space-y-6">
          <section className="card">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="flex items-center gap-2 font-semibold"><IconSparkles className="text-accent" /> Conversation playbook</h3>
                <p className="mt-1 text-sm text-muted">AI drafts the opening, qualification questions, objection handling and closing from your script. Edit anything.</p>
              </div>
              <button type="button" className="btn-secondary" onClick={generatePlaybook} disabled={busy === "playbook"}>
                {busy === "playbook" ? <Spinner /> : <IconSparkles />} {form.playbook ? "Regenerate" : "Generate with AI"}
              </button>
            </div>
            {form.playbook ? (
              <PlaybookEditor value={form.playbook} onChange={(p) => set("playbook", p)} />
            ) : (
              <div className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted">
                Optional, but recommended: the agent adapts better with a playbook of likely objections and follow-ups.
              </div>
            )}
          </section>

          <section className="card">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="font-semibold">Opening line &amp; final instructions</h3>
              <button type="button" className="text-sm font-medium text-accent hover:underline" onClick={loadPreview} disabled={busy === "preview"}>
                {busy === "preview" ? "Refreshing…" : "Refresh preview"}
              </button>
            </div>
            <label className="label" htmlFor="opening">Opening line <span className="font-normal text-muted">(optional)</span></label>
            <input id="opening" className="input" maxLength={500} placeholder="Leave empty to auto-generate a greeting that discloses the AI"
              value={form.opening_line ?? ""} onChange={(e) => set("opening_line", e.target.value)} />
            <p className="hint">Must say this is an AI assistant calling on behalf of your business.</p>
            {preview && (
              <details className="mt-4 rounded-xl bg-background p-4">
                <summary className="cursor-pointer text-sm font-medium">View the full agent instructions</summary>
                {preview.begin_message && <p className="mt-3 text-sm"><span className="text-muted">First sentence:</span> {preview.begin_message}</p>}
                <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed">{preview.prompt}</pre>
              </details>
            )}
          </section>

          {saved?.sync_status === "error" && (
            <Alert>{saved.mode === "direct" ? "Saved, but the agent can't call yet" : "Saved, but Retell couldn't set up the agent"}: {saved.sync_error}</Alert>
          )}
          {saved && saved.sync_status === "synced" && !dirty && options && <Simulator agentId={saved.id} personas={options.personas} />}
          {saved && dirty && <Alert kind="info">You have unsaved changes. Save to update the live agent and test it.</Alert>}
        </div>
      )}

      <div className="mt-6 flex items-center justify-between gap-3">
        <button type="button" className="btn-secondary" disabled={step === 0} onClick={() => goTo(step - 1)}><IconArrowLeft /> Back</button>
        <div className="flex items-center gap-3">
          {saved?.sync_status === "synced" && !dirty && (
            <Link href={`/calls?agent=${saved.id}`} className="btn-secondary"><IconPhone /> Call with this agent</Link>
          )}
          {step < STEPS.length - 1 ? (
            <button type="button" className="btn-primary" disabled={!stepValid[step]} onClick={() => goTo(step + 1)}>Next <IconArrowRight /></button>
          ) : (
            <button type="button" className="btn-primary" onClick={save} disabled={busy === "save" || !stepValid[0] || !stepValid[1] || (!!saved && !dirty)}>
              {busy === "save" ? <Spinner /> : <IconCheck />} {saved ? (dirty ? "Save changes" : "Saved") : "Create Agent"}
            </button>
          )}
        </div>
      </div>
      {saved && (
        <p className="mt-3 text-right text-xs text-muted">
          {saved.sync_status === "synced"
            ? <Pill tone="green">{saved.mode === "direct" ? "Ready to call" : "Live on Retell"}</Pill>
            : <Pill tone="red">{saved.mode === "direct" ? "Not ready" : "Not synced"}</Pill>}
        </p>
      )}
    </div>
  );
}

function ModeCard({ mode, current, onSelect, brands, title, body, disabled }: {
  mode: AgentMode; current: AgentMode; onSelect: (m: AgentMode) => void; brands: BrandId[]; title: string; body: string; disabled?: boolean;
}) {
  const active = mode === current;
  return (
    <motion.button type="button" disabled={disabled} onClick={() => onSelect(mode)}
      whileHover={disabled ? undefined : { y: -3 }} whileTap={disabled ? undefined : { scale: 0.98 }}
      transition={{ type: "spring", stiffness: 400, damping: 28 }}
      className={`relative rounded-xl border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${active ? "border-accent bg-accent-soft/60" : "border-border hover:border-zinc-300"}`}>
      {active && <motion.span layoutId="mode-ring" className="pointer-events-none absolute inset-0 rounded-xl ring-4 ring-accent/15" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
      <div className="mb-3 flex items-center">
        {brands.map((b, i) => (
          <span key={b} className={i ? "-ml-1.5" : ""} style={{ zIndex: brands.length - i }}>
            <ProviderLogo id={b} size="sm" className="ring-2 ring-white" />
          </span>
        ))}
        {active && <IconCheck className="ml-auto text-accent" />}
      </div>
      <div className="mb-1 text-sm font-medium">{title}</div>
      <p className="text-xs leading-relaxed text-muted">{body}</p>
    </motion.button>
  );
}

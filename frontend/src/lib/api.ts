export type User = { id: number; name: string; email: string };

export type Playbook = {
  opening: string;
  qualification_questions: string[];
  value_points: string[];
  objections: { objection: string; response: string }[];
  follow_up_questions: string[];
  closing_strategy: string;
  success_criteria: string[];
};

export type AgentMode = "managed" | "custom_brain" | "direct";
export type SttProviderId = "whisper" | "sarvam";

export type AgentInput = {
  name: string;
  business_name: string;
  mode: AgentMode;
  objective: string;
  target_audience: string | null;
  success_condition: string | null;
  fallback_behavior: string | null;
  max_duration_minutes: number;
  script: string;
  additional_context: string | null;
  dos_and_donts: string | null;
  playbook: Playbook | null;
  language: string;
  voice_provider: string | null;
  voice_id: string;
  stt_provider: SttProviderId | null;
  tone: string;
  opening_line: string | null;
};

export type Agent = AgentInput & {
  id: number;
  generated_prompt: string;
  begin_message: string | null;
  retell_agent_id: string | null;
  sync_status: "pending" | "synced" | "error";
  sync_error: string | null;
  created_at: string;
  updated_at: string;
};

export type CallStatus = "queued" | "ringing" | "in_progress" | "completed" | "failed";
export type GoalStatus = "goal_achieved" | "follow_up" | "not_interested" | "no_response" | "failed";

export type Call = {
  id: number;
  agent_id: number;
  agent_name: string | null;
  mode: AgentMode;
  to_number: string;
  from_number: string;
  customer_name: string | null;
  retell_call_id: string | null;
  twilio_call_sid: string | null;
  stt_provider: SttProviderId | null;
  status: CallStatus;
  retell_status: string | null;
  disconnection_reason: string | null;
  error: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  summary: string | null;
  sentiment: string | null;
  call_successful: boolean | null;
  outcome: string | null;
  goal_status: GoalStatus | null;
  customer_interest: string | null;
  follow_up_requested: boolean | null;
  appointment_preference: string | null;
  primary_objection: string | null;
  unanswered_questions: string | null;
  next_action: string | null;
  key_notes: string | null;
  created_at: string;
};

export type Turn = { role: string | null; content: string | null };

export type CallDiagnostics = {
  stt?: { provider: string; model: string; language?: string; mode?: string | null; source: string };
  fallback_events?: { from: string; to: string; reason: string; at: string }[];
  utterances?: number;
  avg_stt_latency_ms?: number | null;
  avg_first_audio_ms?: number | null;
  interruptions?: number;
  duplicates_suppressed?: number;
  dropped_frames?: number;
  reminders?: number;
  errors?: string[];
};

export type CallDetail = Call & {
  diagnostics: CallDiagnostics | null;
  transcript: string | null;
  transcript_object: Turn[] | null;
  recording_url: string | null;
};

export type Stats = {
  total_calls: number;
  completed: number;
  failed: number;
  interested: number;
  goal_achieved: number;
  follow_ups: number;
  avg_duration_ms: number | null;
};

export type Voice = {
  voice_id: string;
  voice_name: string;
  provider: string;
  gender: string;
  accent: string | null;
  age: string | null;
  preview_audio_url: string | null;
};

export type Options = {
  languages: Record<string, string>;
  tones: Record<string, string>;
  modes: Record<AgentMode, string>;
  outcomes: string[];
  personas: Record<string, { label: string; description: string }>;
  from_number: string;
  webhooks_enabled: boolean;
  custom_brain_available: boolean;
  direct_available: boolean;
  default_stt_provider: SttProviderId | null;
  destination_allow_list: boolean;
  retell_configured: boolean;
  conversation_engine: { provider: string; model: string; platform_key?: boolean; base_url?: string };
};

export type ProviderField = {
  key: string;
  label: string;
  secret: boolean;
  placeholder: string;
  required: boolean;
  kind: "text" | "select";
  options: { value: string; label: string }[];
  help: string;
  value: string | null;
};

export type Provider = {
  id: string;
  name: string;
  category: string;
  purpose: string;
  note: string;
  fields: ProviderField[];
  configured: boolean;
  status: "not_configured" | "untested" | "connected" | "error";
  status_detail: string | null;
  last_tested_at: string | null;
  secrets_rotated_at: string | null;
};

export type SpeechSettings = {
  default_provider: SttProviderId | null;
  fallback_enabled: boolean;
  connected: Record<SttProviderId, boolean>;
};

export type SpeechCapabilities = {
  id: SttProviderId;
  name: string;
  summary: string;
  models: { id: string; label: string; streaming: boolean; batch: boolean; note: string }[];
  languages: { code: string; label: string }[];
  deprecation?: string;
};

export type TranscriptionResult = {
  text: string;
  provider: string;
  model: string;
  status: "completed" | "empty";
  language: string | null;
  language_confidence: number | null;
  latency_ms: number | null;
  audio_duration_s: number | null;
};

export type SimTurnResult = { turns: { role: string; content: string }[]; ended: boolean; ended_by: string | null };

export type SimEvaluation = {
  scores: Record<string, number | null>;
  goal_achieved: boolean;
  unsupported_claims: string[];
  strengths: string[];
  improvements: string[];
  summary: string;
};

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: [...], msg}]
    return detail
      .map((d: { loc?: (string | number)[]; msg?: string }) => {
        const field = d.loc?.filter((p) => p !== "body").join(".");
        return field ? `${field.replace(/_/g, " ")}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  return "Something went wrong.";
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      // Let the browser set the multipart boundary for FormData uploads.
      headers: isForm ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Can't reach the backend. Is it running on port 8000?", 0);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
      // Session expired mid-use: a full reload to the login page also resets client state.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    }
    const fallback = res.status >= 500 && !body ? "Backend unavailable. Is it running on port 8000?" : undefined;
    throw new ApiError(fallback ?? describe(body?.detail), res.status);
  }
  return body as T;
}

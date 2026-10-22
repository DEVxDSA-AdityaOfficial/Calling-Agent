# Calling Agent — Prompt-to-Calling-Agent Platform (POC)

**Describe the goal. Define the boundaries. Let AI handle the conversation.**

Create an AI phone agent from a plain-language script, test it against simulated customers, place real
outbound calls, and review goal-based outcomes. Each agent picks one of three calling modes:

| Mode | Telephony | Speech-to-text | Brain | Voice |
| --- | --- | --- | --- | --- |
| **Retell · Managed** | Retell | Retell | Retell LLM | Retell voices |
| **Retell + Custom Brain** | Retell | Retell | **our ConversationModel** (OpenAI / local SLM) | Retell voices |
| **Twilio + Custom Brain** | **Twilio** Media Streams | **OpenAI Whisper or Sarvam AI** (your choice) | **our ConversationModel** | **ElevenLabs** (your account) |

```
                         ┌── Retell API / webhooks / custom-LLM WebSocket  (Managed, Retell + Custom Brain)
Next.js ──/api/*──▶ FastAPI ──┤
                         └── Twilio REST + status callbacks + Media Stream WebSocket  (Twilio + Custom Brain)
                                      │ μ-law 8 kHz audio
                                      ▼
                              SpeechProviderRouter ──▶ Sarvam streaming (saaras:v4)  |  OpenAI Realtime (gpt-realtime-whisper)
                                      │ final transcripts
                                      ▼
                              ConversationModel (OpenAI | local SLM) ──▶ ElevenLabs TTS (ulaw_8000) ──▶ Twilio
```

## Features

| Area | What it does |
| --- | --- |
| **Auth** | Email/password accounts, HttpOnly session cookies, all data scoped per user. |
| **API & Providers** | Connect Twilio, Retell AI, ElevenLabs and OpenAI with your own keys. Keys are Fernet-encrypted at rest, masked in the UI, each with *Test connection*. Platform defaults come from `.env`. |
| **Agent builder** (3 steps) | Basics (name, objective, language incl. **Hinglish**, voice provider + voice, calling mode) → Script & Context (script, approved info, do's & don'ts, goal, success condition, fallback, max duration) → Review & Test. |
| **Script-to-Agent intelligence** | "Generate with AI" drafts a playbook: opening, qualification questions, value points, objections + responses, follow-ups, closing strategy, success criteria. Fully editable. |
| **Guardrails** | Prompt enforces AI disclosure, approved-facts-only (no invented prices/discounts), no unapproved commitments, respects "not interested"/do-not-call, no sensitive data. |
| **Adaptive conversation** | Prompt covers interested / busy / doubtful / confused / angry / price-sensitive customers. |
| **Pre-call simulator** | Agent talks to an AI-played persona (interested, confused, angry, price-sensitive, busy, skeptical), then gets scored on adherence, quality, goal, relevance and guardrails, with unsupported claims and suggested improvements. |
| **Two calling modes** | **Managed**: Retell's LLM runs the call. **Custom Brain**: Retell does telephony/STT/TTS and our backend answers every turn over Retell's custom-LLM WebSocket. |
| **Calls** | Start a call (consent checkbox required), live "Calling…" screen with timer, live transcript and **End Call**. |
| **Goal-based outcomes** | Each call ends as *goal achieved*, *interested / follow-up*, *not interested*, *no response* or *failed*, plus interest, primary objection, unanswered questions, preferred time and a suggested next action. |
| **Dashboard** | Total calls, completed, interested, average duration, recent calls. |

### Speech-to-text (Whisper / Sarvam)

Only **Twilio + Custom Brain** agents use our STT. Retell's modes use Retell's own speech recognition,
and Retell doesn't let an external STT provider replace it, so the setting doesn't apply to them.

- **Configure**: Settings → API & Providers → *Speech recognition*. Add keys, pick model / language /
  transcript style (choices come from the backend and are validated on save), *Test connection*.
- **Selection policy** (deterministic): the agent's provider → else your default → else a clear error.
  The provider is pinned when a call is placed and never changes mid-call. An optional, off-by-default
  fallback can switch to the other provider *only if the first can't connect before audio starts*;
  fallbacks are recorded in the call's diagnostics.
- **Sarvam AI**: streaming `wss://api.sarvam.ai/speech-to-text-realtime/ws` with `saaras:v4` (or
  `saaras:v3-realtime`), `encoding=mulaw&sample_rate=8000`, so Twilio audio passes through unconverted;
  Sarvam's VAD marks end of utterance. Hinglish agents default to `hi-IN` + `codemix`. Testing the
  connection opens a session without sending audio (not billed). REST `/speech-to-text` is used for
  “Try a transcription”. REST and streaming differ (`unknown` vs `auto`, `od-IN` vs `or-IN`,
  `saaras:v3` vs `saaras:v3-realtime`); both mappings are handled and covered by tests.
- **OpenAI Whisper**: live calls use `gpt-realtime-whisper` in a Realtime transcription session with
  `audio/pcmu` input (no conversion). That model has no server VAD, so we detect end of speech locally
  and send `input_audio_buffer.commit`. Clips use `whisper-1` on `/v1/audio/transcriptions`.
  Both are Whisper models; OpenAI has **deprecated `whisper-1` (shuts down 26 Feb 2027)**.
  The Whisper key is optional and falls back to your OpenAI key.
- **Pipeline handling**: partial/final events, barge-in (Twilio `clear`), duplicate-final suppression,
  bounded audio buffer with drop-oldest backpressure, silence reminders, max duration, `[END_CALL]`
  hang-up after the goodbye has played (Twilio `mark`), clean teardown, and post-call analysis.
  Per-call diagnostics: provider, why it was chosen, utterances, STT latency, time to first audio,
  interruptions, duplicates, dropped frames.

### Swapping OpenAI for your own SLM

All LLM use goes through `ConversationModel` (`backend/app/conversation/base.py`). Set
`CONVERSATION_PROVIDER=local_slm`, `LOCAL_SLM_BASE_URL` and `LOCAL_SLM_MODEL` to use any
OpenAI-compatible server (vLLM, Ollama, llama.cpp, TGI). Nothing else changes.

## Setup

Prerequisites: Python 3.11+, Node 20+, Docker (or any PostgreSQL), a Retell account with an API key and a
phone number bought in / imported into Retell, and an OpenAI key (for Custom Brain, playbooks and the simulator).

```bash
# 1. Database
docker compose up -d postgres

# 2. Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # set ENCRYPTION_KEY; optionally platform RETELL_/OPENAI_ keys
uvicorn app.main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev                 # http://localhost:3000 → create an account → Settings → API & Providers
```

The schema is managed with Alembic (`backend/migrations/`). Migrations run on startup
(`AUTO_MIGRATE=true`); or run `python -m app.cli migrate` in your deploy step and set it to `false`.
After changing models: `alembic revision --autogenerate -m "…"` (a test fails if models and migrations drift).

### Credential security

- Keys are encrypted with Fernet (`ENCRYPTION_KEY`, MultiFernet: first key encrypts, all decrypt) and
  only ever returned masked (`••••1234`). Errors from providers are sanitized before they're stored,
  logged or shown.
- **Rotation**: prepend a new key to `ENCRYPTION_KEY`, run `python -m app.cli rotate-keys`, remove the old one.
- **Safe replacement**: replacing a working provider key tests the new one first; if it fails, the old
  key is kept.
- Connection tests (10/min), saves (20/min) and test transcriptions (5/min) are rate-limited per user
  (in-process; use Redis with multiple workers).
- **Production**: inject `ENCRYPTION_KEY` from a KMS / secret manager (AWS KMS + Secrets Manager, GCP
  Secret Manager, Vault). Envelope encryption with a KMS-held key is the recommended next step.

### Public URL (Custom Brain + webhooks)

Retell and Twilio must reach your backend for both Custom Brain modes and for webhooks:

```bash
ngrok http 8000
# backend/.env:  PUBLIC_BASE_URL=https://<id>.ngrok.app   then restart and re-save each agent
```

Without it, Managed mode still works and call status is refreshed by polling Retell.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q     # 64 tests
cd frontend && npm run lint && npm run build
```

Backend tests use SQLite, fakes for Retell/Twilio/ElevenLabs/the conversation model, mocked HTTP
transports and local mock WebSocket servers for Sarvam and OpenAI Realtime. Every provider URL points at
a dead local port during tests, so nothing reaches a real API. Coverage includes STT contract tests
(request shapes, auth/rate-limit/timeout/malformed errors, streaming events, close codes), the voice
pipeline (barge-in, duplicates, backpressure, STT failure, reminders, teardown), provider selection
and tenant isolation, safe key replacement, key rotation, Twilio signatures and form encoding, a full
Twilio-media-stream call, and migration drift. They cover auth and
per-user isolation, encrypted credentials, both agent modes, playbook generation, the simulator, the call
lifecycle via signed webhooks, polling fallback, End Call, goal outcomes, the Custom Brain WebSocket
(streaming, `[END_CALL]` handling) and SSE parsing of the OpenAI-compatible client.

The full UI flow was also tested end to end in Chrome against a mock Retell + OpenAI server (sign-up →
connect providers → build agent → generate playbook → simulate → Custom Brain call with live transcript →
Managed call → End Call → analysis → dashboard).

## Safety and compliance

Before calling real people:

- **AI disclosure**: the greeting says the caller is an AI assistant, and the agent must admit it when asked.
- **Consent**: every call requires `consent_confirmed`. Recording that consent is your job (TRAI/DND in India,
  TCPA/FCC in the US, GDPR/PECR in the EU/UK). Respect local calling hours.
- **Do-not-call**: the agent ends the call when asked not to be called again. There is no suppression list yet:
  check yours before dialing.
- **Allow-list**: set `ALLOWED_DESTINATION_NUMBERS` while testing.
- **Caller ID**: use a number you own and have registered (e.g. STIR/SHAKEN, branded caller ID).
- **Secrets**: provider keys are encrypted with `ENCRYPTION_KEY`; keep it out of git and back it up (losing it
  makes stored keys unreadable).
- **Custom Brain WebSocket**: Retell sends no auth headers, so each agent's URL contains a random secret and
  only calls placed by this app are served. For production, also allow-list Retell's egress IP.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/signup`, `/login`, `/logout` · GET `/api/auth/me` | Accounts and sessions |
| GET | `/api/providers` · PUT/DELETE `/api/providers/{id}` · POST `/{id}/test` | Provider credentials |
| GET | `/api/options`, `/api/voices` | Languages, tones, personas, voices |
| GET/POST | `/api/agents` · GET/PUT/DELETE `/api/agents/{id}` | Agents (+ Retell sync) |
| POST | `/api/agents/preview`, `/api/agents/playbook` | Prompt preview, AI playbook |
| POST | `/api/agents/{id}/simulate/turn`, `/simulate/evaluate` | Pre-call simulator |
| GET/POST | `/api/calls` · GET `/api/calls/{id}` · POST `/{id}/end` | Calls |
| GET | `/api/calls/stats` | Dashboard numbers |
| POST | `/api/webhooks/retell` | Retell webhooks (signature-verified) |
| WS | `/api/llm-ws/{agent_token}/{call_id}` | Custom Brain (Retell custom-LLM protocol) |
| GET | `/api/speech/providers` | STT models / languages / options per provider |
| GET/PUT | `/api/speech/settings` | Default STT provider, fallback switch |
| POST | `/api/speech/test-transcription` | Transcribe a short clip (multipart) |
| GET | `/api/voices?source=elevenlabs` | Your ElevenLabs voices (Twilio mode) |
| POST | `/api/twilio/status/{token}` | Twilio status callback (signature-verified) |
| WS | `/api/twilio/media/{token}` | Twilio Media Stream (Twilio + Custom Brain) |

Interactive docs: http://localhost:8000/docs

## Verification status

| Check | Status |
| --- | --- |
| Unit, contract and integration tests (mocked providers) | ✅ 64/64 |
| Chrome end to end against mock Retell/Twilio/Sarvam/OpenAI/ElevenLabs servers (Sarvam call, Whisper call, Managed call, settings, test transcription) | ✅ |
| Request/response shapes checked against official docs (Oct 2026) | ✅ Sarvam REST + streaming, OpenAI transcription + Realtime, Twilio Media Streams, ElevenLabs streaming TTS |
| **Real** Sarvam / OpenAI / Twilio / ElevenLabs calls | ❌ not run (no credentials in this environment) |
| Real-audio accuracy & latency (Hindi, Hinglish, accents, noise) | ❌ not measured: use *Try a transcription*, then a consented test call |
| OpenAI Realtime transcription URL | ⚠️ uses the documented `wss://api.openai.com/v1/realtime`; whether a transcription-only session needs an extra query parameter couldn't be confirmed (configurable via `OPENAI_REALTIME_URL`) |
| Sarvam streaming access | ⚠️ the docs list “beta denied” as a rejection reason; your account may need access enabled |

Mock tests prove our side of each contract, not live compatibility. Before a real call: connect real
keys, run *Test connection* for each provider, try a transcription, set `ALLOWED_DESTINATION_NUMBERS`
to your own phone, and call yourself first.

## Roadmap

- Twilio-mode recordings, call transfer, DTMF; a Redis-backed rate limiter; KMS envelope encryption.
- "Improve my agent": suggestions from real call analyses, applied only after approval.
- Alembic migrations, Google/Microsoft sign-in, do-not-call suppression list, calendar booking, bulk campaigns, CRM sync.

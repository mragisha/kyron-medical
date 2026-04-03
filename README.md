# Kyron Medical — Patient Portal

A modular AI-powered patient portal that lets patients book appointments through a chat interface or an outbound voice call. Built entirely in Python (FastAPI + uvicorn). No Node.js.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Directory Structure](#directory-structure)
- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Installation](#installation)
- [Running the Server](#running-the-server)
- [Running Tests](#running-tests)
- [Module Reference](#module-reference)
- [Voice Call Setup](#voice-call-setup)
- [Email Setup (Resend)](#email-setup-resend)
- [SMS Setup (Twilio)](#sms-setup-twilio)
- [Local Development with ngrok](#local-development-with-ngrok)
- [API Reference](#api-reference)
- [Data Models](#data-models)
- [Troubleshooting](#troubleshooting)

---

## Overview

Kyron Medical is a patient-facing portal with two interaction modes:

**Chat** — The patient types messages. An AI assistant (GPT-4o-mini) classifies intent, collects intake information, and guides the patient through booking an appointment. A confirmation email is sent on booking.

**Voice** — The patient clicks "Voice Call" in the UI. The system dials their phone via Vapi. A voice AI assistant collects the doctor preference, date, time, and patient details, then books the slot and sends a confirmation email — all within the call.

Both flows share the same scheduler, session context store, and notification service.

---

## Architecture

```
Browser
  │
  ├── GET  /                     → UI module (static HTML/JS)
  │
  ├── POST /api/chat             → AI Core module
  ├── POST /api/session          → AI Core / Context module
  ├── GET  /api/session/:id      → AI Core / Context module
  │
  ├── GET  /api/schedule/doctors → Scheduler module
  ├── GET  /api/schedule/slots   → Scheduler module
  ├── POST /api/schedule/book    → Scheduler module
  │
  ├── POST /api/voice/initiate-call → Voice module
  └── POST /api/voice/webhook       → Voice module (Vapi calls this)

Internal (server-to-server only):
  POST /api/notify/email  → Notifications module
  POST /api/notify/sms    → Notifications module
```

All modules are mounted into a single FastAPI gateway at `app/main.py` and served on one port (default `3001`).

### Module responsibilities

| Module | Path | Purpose |
|---|---|---|
| **AI Core** | `modules/ai` | Chat endpoint, intent classification, patient intake via GPT-4o-mini |
| **Context** | `modules/context` | Session store (Redis with in-memory fallback) |
| **Scheduler** | `modules/scheduler` | Doctor list, slot availability, appointment booking |
| **Notifications** | `modules/notifications` | Confirmation emails via Resend, SMS via Twilio |
| **Voice** | `modules/voice` | Outbound Vapi calls, webhook tool handler |
| **Safety** | `modules/safety` | Guardrails — blocks medical advice and out-of-scope topics |
| **UI** | `modules/ui` | Serves the single-page chat + booking frontend |

---

## Directory Structure

```
kyron-medical/
├── .env                          # All secrets and config (never commit)
├── app/
│   └── main.py                   # Master FastAPI gateway — mounts all modules
├── modules/
│   ├── ai/
│   │   ├── main.py               # Chat endpoint, OpenAI integration
│   │   └── test_ai.py
│   ├── context/
│   │   ├── main.py               # Session CRUD, Redis/in-memory store
│   │   └── test_context.py
│   ├── notifications/
│   │   ├── main.py               # Email (Resend) and SMS (Twilio)
│   │   ├── test_notifications.py
│   │   └── test_email_live.py    # Live integration test (real keys required)
│   ├── safety/
│   │   ├── guardrails.py         # Regex-based safety filters
│   │   ├── main.py
│   │   └── test_safety.py
│   ├── scheduler/
│   │   ├── db.py                 # In-memory doctor/slot/appointment store
│   │   ├── models.py             # Pydantic models
│   │   ├── router.py             # FastAPI routes
│   │   ├── main.py
│   │   └── test_scheduler.py
│   ├── ui/
│   │   ├── main.py               # Serves static files
│   │   ├── static/
│   │   │   └── index.html        # Single-page app (chat + booking UI)
│   │   └── test_ui.py
│   └── voice/
│       ├── main.py               # Vapi call initiation + webhook tool handler
│       └── test_voice.py
├── CONTRACTS.md                  # Source of truth for all inter-module interfaces
├── ORCHESTRATOR.md               # Build orchestration instructions
└── types.ts                      # Shared type definitions (reference)
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.14 tested |
| pip / venv | any | Standard library |
| Redis | optional | Falls back to in-memory if `REDIS_URL` is not set |
| ngrok | any | Required for local voice call testing |

**External service accounts required:**

| Service | Used for | Sign up |
|---|---|---|
| OpenAI | AI chat + intent classification | [platform.openai.com](https://platform.openai.com) |
| Vapi | Outbound voice calls | [vapi.ai](https://vapi.ai) |
| Resend | Confirmation emails | [resend.com](https://resend.com) |
| Twilio | SMS notifications (optional) | [twilio.com](https://twilio.com) |
| Redis | Persistent session storage (optional) | [redis.com](https://redis.com) or run locally |

---

## Environment Variables

Create a `.env` file at the **project root**. All modules read from this single file.

```env
# ── AI ────────────────────────────────────────────────────────────────────────
OPENAI_API_KEY=sk-...

# ── Email (Resend) ────────────────────────────────────────────────────────────
RESEND_API_KEY=re_...

# Leave blank to use the Resend sandbox sender (onboarding@resend.dev).
# Sandbox can only deliver to your own account email.
RESEND_FROM_EMAIL=

# Forces ALL confirmation emails to this address while your domain is unverified.
# Remove once RESEND_FROM_EMAIL is set with a verified domain.
RESEND_SANDBOX_OVERRIDE=you@gmail.com

# ── SMS (Twilio) — optional ───────────────────────────────────────────────────
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...           # E.164 format

# ── Voice (Vapi) ──────────────────────────────────────────────────────────────
VAPI_API_KEY=...                    # Private Key — Settings → API Keys in Vapi dashboard

# UUID of your Vapi phone number (NOT the E.164 string).
# Find it: Vapi dashboard → Phone Numbers → click your number → copy the ID field.
VAPI_PHONE_NUMBER=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# ── Session store ─────────────────────────────────────────────────────────────
# Optional. Falls back to in-memory (lost on restart) if not set.
REDIS_URL=redis://default:password@host:port

# ── Server ────────────────────────────────────────────────────────────────────
PORT=3001

# Public URL Vapi uses to POST tool-call webhooks.
# For local dev: your ngrok HTTPS URL (see Local Development section).
# For production: your server's public HTTPS URL.
FRONTEND_URL=https://your-ngrok-url.ngrok-free.app
```

---

## Installation

```bash
# 1. Clone the repo
git clone <repo-url>
cd kyron-medical

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# 3. Install all dependencies
pip install fastapi uvicorn httpx python-dotenv pydantic \
            openai resend twilio redis pytest
```

---

## Running the Server

```bash
# Activate the venv first if not already active
source .venv/bin/activate

# Start from the project root
uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload
```

The `--reload` flag restarts the server automatically when you save a file. Remove it in production.

| URL | What you get |
|---|---|
| `http://localhost:3001/` | Chat + booking UI |
| `http://localhost:3001/health` | `{"status": "ok"}` |
| `http://localhost:3001/docs` | Swagger API explorer |

---

## Module Reference

### AI Core (`modules/ai`)

Handles all chat interactions.

- `POST /api/chat` receives `{ sessionId, message }`, calls OpenAI GPT-4o-mini, and returns `{ reply, intent, session }`.
- Classifies every response into one of 7 intents (see [Intent values](#intent-values)).
- Runs every AI response through safety guardrails before returning it.
- When patient intake is complete (all fields collected), stores the `Patient` object on the session automatically.

### Context (`modules/context`)

Manages the session lifecycle.

- `POST /api/session` creates a new empty session and returns its UUID.
- `GET /api/session/:id` returns the full session including messages, patient, and appointment.
- Uses Redis if `REDIS_URL` is set, otherwise uses a Python dict in memory.
- **Important:** In-memory sessions are lost on every server restart. Use Redis for persistence.
- Exposes `get_session()` and `upsert_session()` as importable Python functions used by the AI and voice modules.

### Scheduler (`modules/scheduler`)

Manages doctor availability and booking.

- Pure **in-memory store** — resets completely on every server restart (no database).
- Seeds 4 doctors on startup with slots auto-generated for weekdays only, from tomorrow through the next 30 days, at 09:00, 11:00, and 14:00.

  | Doctor | Specialty | Body parts matched |
  |---|---|---|
  | Dr. Sarah Chen | Cardiology | heart, chest, cardiovascular, blood pressure |
  | Dr. Marcus Webb | Orthopedics | bone, joint, spine, knee, shoulder, hip |
  | Dr. Priya Nair | Neurology | brain, headache, migraine, seizure, dizziness |
  | Dr. James Okafor | Dermatology | skin, rash, mole, acne, eczema, psoriasis |

- `GET /api/schedule/slots` accepts optional `doctorId` and `date` (YYYY-MM-DD) query params.
- `POST /api/schedule/book` returns `409 Conflict` if the slot is already booked.

### Notifications (`modules/notifications`)

Sends confirmation emails and SMS messages. Called internally by the AI and voice modules — not exposed to the browser.

- `POST /api/notify/email` sends via Resend. Returns `{ success: false }` (not an error) if the API key is missing or the send fails.
- `POST /api/notify/sms` sends via Twilio. **Only fires if `patient.smsOptIn === true`.** Returns `{ success: false }` if opt-in is false — this is intentional, not a bug.

### Safety (`modules/safety`)

A Python library imported by the AI Core — not an HTTP service.

- **`is_medical_advice(text)`** — returns `True` if the text contains diagnoses, prescriptions, dosages, or self-harm content.
- **`sanitize_response(text)`** — strips or replaces dangerous phrases.
- **`check_out_of_scope(text)`** — returns `True` if the topic is outside the practice's scope (legal, financial, etc.).
- 40+ compiled regex patterns evaluated on every AI response before it reaches the patient.

### Voice (`modules/voice`)

Handles outbound Vapi calls and the tool-call webhook.

- `POST /api/voice/initiate-call` — loads the session context, pre-fetches the live doctor list, injects both into the AI system prompt, and POSTs to Vapi's `/call/phone` API.
- `POST /api/voice/webhook` — receives Vapi events. On `tool-calls`, runs `_tool_request_appointment` which resolves the doctor, finds the best slot, books it, sends the email, and returns a spoken confirmation to Vapi.
- **Single-tool design:** The voice AI collects doctor + date + time + patient details through conversation, then fires **one** `request_appointment` tool call. The server does all resolution internally — the AI never handles slot UUIDs.

### UI (`modules/ui`)

Serves the frontend as a static single-page application.

- Chat panel (left) — sends messages to `/api/chat`, displays AI replies.
- Slots panel (right) — opens automatically when intent is `SCHEDULING`. Fetches doctors and slots, lets the patient pick a slot and enter their details.
- Voice Call button (header) — prompts for a phone number and calls `POST /api/voice/initiate-call`.

---

## Voice Call Setup

### Step 1 — Get a Vapi account and phone number

1. Sign up at [vapi.ai](https://vapi.ai).
2. Go to **Phone Numbers** in the dashboard → buy or provision a US phone number.
3. Click the number → copy the **ID field** (a UUID like `57931de8-5e87-42ef-8db5-13718083bcdd`).
   > This is **not** the E.164 phone number string. It is the UUID identifier used in API calls.
4. Go to **Settings → API Keys** → copy your **Private Key**.
5. Add both to `.env`:
   ```env
   VAPI_API_KEY=<private key>
   VAPI_PHONE_NUMBER=<uuid>
   ```

### Step 2 — Expose your local server with ngrok

Vapi is a cloud service and cannot POST to `localhost`. You need a publicly accessible HTTPS URL.

```bash
# Install ngrok (once)
brew install ngrok

# Authenticate (once — free account at ngrok.com)
ngrok config add-authtoken <your-token>

# Start tunnel every dev session
ngrok http 3001
```

ngrok will print a URL like `https://a1b2c3d4.ngrok-free.app`. Copy it and set it in `.env`:

```env
FRONTEND_URL=https://a1b2c3d4.ngrok-free.app
```

Then restart the server. The webhook URL is embedded into each Vapi call at initiation time, so a restart picks up the new value.

> **Note:** Free ngrok accounts get a new URL on every restart. Update `FRONTEND_URL` in `.env` each dev session.

### Step 3 — Verify the webhook endpoint

```bash
curl https://a1b2c3d4.ngrok-free.app/api/voice/webhook \
  -X POST -H "Content-Type: application/json" \
  -d '{"type":"test"}'
# Expected response: {"received": true}
```

### Step 4 — Initiate a call

1. Open `http://localhost:3001` in the browser.
2. Start a chat session (a session must exist before a call can begin).
3. Click **📞 Voice Call** in the header.
4. Enter the destination phone number in E.164 format (e.g. `+19195551234`).
5. Vapi dials the number. The voice AI guides the patient through booking.

### How the voice AI collects information

The AI follows a strict four-step flow before calling the `request_appointment` tool:

```
Step 1 — Doctor or specialty
  "Which doctor or specialty do you need?"
  ↳ Maps body parts to specialties: "knee pain" → orthopedics → Dr. Marcus Webb
  ↳ Confirms: "That sounds like it could be for Dr. Marcus Webb — is that right?"

Step 2 — Preferred date
  "What date works for you?"
  ↳ Accepts natural language: "next Monday", "March 25th", "this Friday"
  ↳ Normalises to YYYY-MM-DD before querying the scheduler
  ↳ If the date is a weekend, automatically tries the next available weekday

Step 3 — Preferred time
  "Morning, afternoon, or a specific time like 9 AM?"
  ↳ Finds the available slot closest to the expressed preference

Step 4 — Patient details
  "Can I get your first name, last name, and email for the confirmation?"
```

Once all four are confirmed, the AI fires `request_appointment`. The server books the slot and sends the confirmation email within the same call.

---

## Email Setup (Resend)

### During development (sandbox mode)

Without a verified sending domain, Resend only delivers to the email address you signed up with. Set `RESEND_SANDBOX_OVERRIDE` in `.env` to route all emails to your own address:

```env
RESEND_SANDBOX_OVERRIDE=you@gmail.com
```

The email subject will include the patient's name so you can identify which booking it belongs to. Remove this variable when you go to production.

### For production (send to any recipient)

1. Go to [resend.com/domains](https://resend.com/domains) → **Add Domain**.
2. Enter your domain (e.g. `kyronmedical.com`).
3. Add the DNS records Resend provides (SPF, DKIM × 2, DMARC) to your DNS registrar.
4. Wait for verification (typically under 30 minutes).
5. Update `.env`:
   ```env
   RESEND_FROM_EMAIL=no-reply@kyronmedical.com
   # Remove RESEND_SANDBOX_OVERRIDE
   ```

---

## SMS Setup (Twilio)

SMS confirmations are **opt-in only**. The notifications module checks `patient.smsOptIn === true` before sending. If the flag is `false`, the endpoint returns `{ success: false }` — this is expected behaviour, not an error.

1. Create a Twilio account at [twilio.com](https://twilio.com).
2. Buy a phone number from the Twilio console.
3. Add to `.env`:
   ```env
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_PHONE_NUMBER=+1...    # your Twilio number in E.164 format
   ```

---

## Local Development with ngrok

A typical local development session:

```bash
# Terminal 1 — start ngrok tunnel
ngrok http 3001
# Copy the https://....ngrok-free.app URL printed

# Terminal 2 — update .env, then start the server
# Edit .env: FRONTEND_URL=https://your-new-ngrok-url.ngrok-free.app
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload

# Terminal 3 — run tests while developing
cd modules/voice
../../.venv/bin/python -m pytest test_voice.py -v
```

The server console prints structured, timestamped logs with visible section banners for every major event:

```
10:32:01 [VOICE] INFO     ────────────────────────────────────────────────────────────
10:32:01 [VOICE] INFO       INITIATE CALL
10:32:01 [VOICE] INFO     ────────────────────────────────────────────────────────────
10:32:01 [VOICE] INFO     sessionId=abc-123  customerPhone=+19193372450
10:32:01 [VOICE] INFO     Pre-fetched 4 doctors for system prompt
10:32:01 [VOICE] INFO     Vapi call created successfully. callId=019d02ce-...

10:32:18 [VOICE] INFO     ────────────────────────────────────────────────────────────
10:32:18 [VOICE] INFO       TOOL CALL → request_appointment
10:32:18 [VOICE] INFO     ────────────────────────────────────────────────────────────
10:32:18 [VOICE] INFO     [1/6] Doctors: [doc-sarah-chen, doc-marcus-webb, ...]
10:32:18 [VOICE] INFO     [2/6] preferredDate='March 25th' → '2026-03-25'
10:32:18 [VOICE] INFO     [3/6] 3 total slots, 3 available
10:32:18 [VOICE] INFO     [4/6] Chosen slot: 2026-03-25T09:00:00
10:32:18 [VOICE] INFO     [5/6] Booking response: HTTP 201
10:32:18 [VOICE] INFO     [5/6] Appointment JSON: { ... }
10:32:18 [VOICE] INFO     [6/6] Email API: HTTP 200
```

---

## API Reference

### Sessions

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/api/session` | — | `{ sessionId: string }` |
| `GET` | `/api/session/:id` | — | `{ session: Session }` |
| `POST` | `/api/chat` | `{ sessionId, message }` | `{ reply, intent, session }` |

### Scheduling

| Method | Path | Query / Body | Response |
|---|---|---|---|
| `GET` | `/api/schedule/doctors` | — | `{ doctors: Doctor[] }` |
| `GET` | `/api/schedule/slots` | `?doctorId=&date=YYYY-MM-DD` | `{ slots: Slot[] }` |
| `POST` | `/api/schedule/book` | `{ sessionId, slotId, reason }` | `{ appointment: Appointment }` |

### Notifications (internal only)

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/api/notify/email` | `{ appointment, patient }` | `{ success: boolean }` |
| `POST` | `/api/notify/sms` | `{ appointment, patient }` | `{ success: boolean }` |

### Voice

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/api/voice/initiate-call` | `{ sessionId, customerPhone? }` | `{ callId, status: "dialing" }` |
| `POST` | `/api/voice/webhook` | Vapi event payload | `{ received: true }` or tool results |

### Intent values

The `intent` field returned by `/api/chat`:

| Value | Meaning |
|---|---|
| `INTAKE` | AI is collecting patient info (name, DOB, phone, email) |
| `SCHEDULING` | Patient is browsing or booking appointments |
| `RX_REFILL` | Prescription refill inquiry |
| `OFFICE_INFO` | Address, hours, or contact information |
| `CALL_REQUESTED` | Patient wants to switch to a voice call |
| `COMPLETED` | Appointment confirmed |
| `OUT_OF_SCOPE` | Topic the practice does not handle |

---

## Data Models

### Patient
```json
{
  "id": "uuid",
  "firstName": "Jane",
  "lastName": "Doe",
  "dob": "1990-01-15",
  "phone": "+19195551234",
  "email": "jane@example.com",
  "smsOptIn": true
}
```

### Doctor
```json
{
  "id": "doc-sarah-chen",
  "name": "Dr. Sarah Chen",
  "specialty": "cardiology",
  "bodyParts": ["heart", "chest", "cardiovascular", "blood pressure"],
  "slots": [ ... ]
}
```

### Slot
```json
{
  "id": "uuid",
  "doctorId": "doc-sarah-chen",
  "datetime": "2026-03-25T09:00:00",
  "durationMinutes": 30,
  "booked": false
}
```

### Appointment
```json
{
  "id": "uuid",
  "patientId": "session-uuid",
  "doctorId": "doc-sarah-chen",
  "slotId": "slot-uuid",
  "reason": "Annual checkup",
  "confirmedAt": "2026-03-25T09:00:00",
  "emailSent": true,
  "smsSent": false
}
```

### Session
```json
{
  "id": "uuid",
  "patient": { "...": "Patient object, set after intake" },
  "appointment": { "...": "Appointment object, set after booking" },
  "messages": [
    { "role": "user", "content": "Hi", "timestamp": "2026-03-18T10:00:00Z" },
    { "role": "assistant", "content": "Hello!", "timestamp": "2026-03-18T10:00:01Z" }
  ],
  "createdAt": "2026-03-18T10:00:00Z",
  "lastActiveAt": "2026-03-18T10:05:00Z"
}
```

---

## Troubleshooting

### Server won't start — `ModuleNotFoundError: No module named 'fastapi'`

The virtual environment is not active. Run:
```bash
source .venv/bin/activate
```

---

### All `/api/*` routes return 404

One or more modules failed to load at startup, so their routes were not registered. Check the server startup output for Python import errors.

---

### Voice call connects but the AI is completely silent

The Vapi payload is missing the `transcriber` or `voice` configuration. Both are set in the current codebase (Deepgram nova-2 for speech-to-text, OpenAI Alloy for text-to-speech). If this occurs after a code change, check the Vapi dashboard → Calls → select the call → verify the assistant config.

---

### Vapi error: `phoneNumberId must be a UUID`

`VAPI_PHONE_NUMBER` in `.env` is set to the E.164 phone number string (e.g. `+19195551234`) instead of the UUID identifier. In the Vapi dashboard go to **Phone Numbers** → click the number → copy the **ID** field, which looks like `57931de8-5e87-42ef-8db5-13718083bcdd`.

---

### Vapi error: `EHOSTUNREACH` on tool calls

Vapi cannot reach your webhook URL. Check:
- ngrok is running (`ngrok http 3001`)
- `FRONTEND_URL` in `.env` matches the current ngrok URL
- The server was restarted after updating `.env`

Verify connectivity:
```bash
curl https://your-ngrok-url.ngrok-free.app/api/voice/webhook \
  -X POST -H "Content-Type: application/json" -d '{}'
# Expected: {"received": true}
```

---

### Vapi error: `401 Unauthorized`

`VAPI_API_KEY` is the **Public Key** instead of the **Private Key**. In the Vapi dashboard go to **Settings → API Keys** and copy the **Private Key**.

---

### Email returns `{ "success": false }` silently

`RESEND_API_KEY` is missing or incorrect. Check `.env` and confirm the value starts with `re_`.

---

### Email error: `You can only send testing emails to your own email address`

Your sending domain is not verified in Resend. Set `RESEND_SANDBOX_OVERRIDE=your-gmail@gmail.com` in `.env` to redirect all emails to your own address during development. See [Email Setup](#email-setup-resend) for domain verification steps.

---

### All appointment slots are already booked after testing

The scheduler is entirely in-memory and resets on every restart. Simply restart the server to get a fresh set of available slots:
```bash
# Ctrl+C to stop, then:
uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload
```

---

### Voice call books the wrong doctor or wrong date

Check the server logs for the `TOOL CALL → request_appointment` banner. The `[1/6]` step logs which doctor was resolved from the AI's input, and `[2/6]` logs the date normalisation. Common causes:

- **Wrong doctor:** The AI passed a specialty or partial name. The fuzzy matcher checks if the needle is a substring of the doctor's name or specialty field.
- **Wrong date:** The requested date was a weekend (no slots generated for Saturdays/Sundays). The code automatically scans the next 7 days for the nearest available weekday.

---

### `ImportError: cannot import name '_in_memory_store' from 'main'` in tests

Do not run `pytest` from the project root — module filenames collide (every module is named `main.py`). Always `cd` into the module directory first:
```bash
cd modules/context && ../../.venv/bin/python -m pytest test_context.py -v
```

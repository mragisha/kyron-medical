
# CONTRACTS.md — Kyron Medical Patient Portal
# This is the single source of truth for all inter-module interfaces.
# Every agent must read this before writing any code.
# No agent may invent types, endpoints, or env vars not listed here.

---

## Shared Data Models (types.ts)

All agents import types from /types.ts — never redefine them locally.

### Patient
```ts
interface Patient {
  id: string              // uuid, generated at session start
  firstName: string
  lastName: string
  dob: string             // "YYYY-MM-DD"
  phone: string           // E.164 format e.g. "+19195551234"
  email: string
  smsOptIn: boolean       // must be explicitly true before SMS is sent
}
```

### Doctor
```ts
interface Doctor {
  id: string
  name: string
  specialty: string       // e.g. "cardiology", "orthopedics"
  bodyParts: string[]     // e.g. ["heart", "chest", "cardiovascular"]
  slots: Slot[]
}
```

### Slot
```ts
interface Slot {
  id: string
  doctorId: string
  datetime: string        // ISO 8601 e.g. "2025-04-14T10:00:00"
  durationMinutes: number
  booked: boolean
}
```

### Appointment
```ts
interface Appointment {
  id: string
  patientId: string
  doctorId: string
  slotId: string
  reason: string
  confirmedAt: string     // ISO 8601
  emailSent: boolean
  smsSent: boolean
}
```

### Session
```ts
interface Session {
  id: string              // uuid, lives in Redis or in-memory store
  patient?: Patient       // set after intake is complete
  appointment?: Appointment
  messages: Message[]     // full conversation history
  createdAt: string
  lastActiveAt: string
}

interface Message {
  role: "user" | "assistant"
  content: string
  timestamp: string
}
```

---

## API Endpoints

### Module: AI Core  (/modules/ai)
Base path: /api

POST /api/chat
  Request:  { sessionId: string, message: string }
  Response: { reply: string, intent: Intent, session: Session }

GET /api/session/:sessionId
  Response: { session: Session }

POST /api/session
  Response: { sessionId: string }   // creates a new empty session

### Module: Scheduler  (/modules/scheduler)
Base path: /api/schedule

GET /api/schedule/doctors
  Response: { doctors: Doctor[] }

GET /api/schedule/slots?doctorId=&date=
  Response: { slots: Slot[] }

POST /api/schedule/book
  Request:  { sessionId: string, slotId: string, reason: string }
  Response: { appointment: Appointment }

### Module: Notifications  (/modules/notifications)
Base path: /api/notify
  (called internally by AI core — not exposed to the browser)

POST /api/notify/email
  Request:  { appointment: Appointment, patient: Patient }
  Response: { success: boolean }

POST /api/notify/sms
  Request:  { appointment: Appointment, patient: Patient }
  Response: { success: boolean }
  Note: must check patient.smsOptIn === true before sending

### Module: Voice  (/modules/voice)
Base path: /api/voice

POST /api/voice/initiate-call
  Request:  { sessionId: string }
  Response: { callId: string, status: "dialing" }
  Note: fetches session history, injects it into Vapi as context

POST /api/voice/webhook
  (Vapi calls this — handles call events, updates session)

---

## Intent Enum

The AI core must classify every response with one of these intents.
The UI uses this to show contextual UI (e.g. a calendar when intent is SCHEDULING).
```ts
type Intent =
  | "INTAKE"           // collecting patient info
  | "SCHEDULING"       // browsing or booking appointments
  | "RX_REFILL"        // prescription refill inquiry
  | "OFFICE_INFO"      // address, hours, contact
  | "CALL_REQUESTED"   // patient wants to switch to voice
  | "COMPLETED"        // booking confirmed
  | "OUT_OF_SCOPE"     // practice doesn't handle this
```

---

## Environment Variables

Every agent reads from a single .env file at the project root.
Never hardcode secrets. Never create new env var names not listed here.

OPENAI_API_KEY=              # OpenAI API — used by ai module
RESEND_API_KEY=              # Resend — used by notifications module
TWILIO_ACCOUNT_SID=          # SMS — used by notifications module
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=         # E.164 format
VAPI_API_KEY=                # voice AI — used by voice module
VAPI_PHONE_NUMBER=           # outbound number patients receive calls from
REDIS_URL=                # session store — used by context module
PORT=3001                 # backend port
FRONTEND_URL=             # e.g. https://kyron.yourdomain.com

---

## MODULE_READY Convention

When an agent finishes its module, it must:
1. Write an empty file at /modules/{name}/MODULE_READY
2. Ensure `uvicorn main:app` works from its folder (Python/FastAPI stack)
3. Ensure `pytest` passes with at least a basic smoke test

The integration agent will not wire a module until its MODULE_READY exists.

---

## What agents must NOT do

- Do not define types locally — import from /types.ts
- Do not create new API routes not listed above
- Do not read or write outside your own /modules/{name}/ folder
- Do not send SMS unless patient.smsOptIn is explicitly true
- Do not let any AI response contain medical advice or diagnosis



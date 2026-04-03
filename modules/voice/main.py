"""
Voice module for Kyron Medical patient portal.

Exposes:
  POST /api/voice/initiate-call  → triggers outbound Vapi call with session context
  POST /api/voice/webhook        → handles Vapi call events (tool-calls, call-ended)
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re as _re
import sys
from typing import Any, Optional

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Load env from project root .env
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_ROOT, ".env"))

VAPI_API_KEY: Optional[str] = os.getenv("VAPI_API_KEY")
VAPI_PHONE_NUMBER: Optional[str] = os.getenv("VAPI_PHONE_NUMBER")
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:8005")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [VOICE] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _banner(title: str) -> None:
    """Print a visible section divider in the console."""
    bar = "─" * 60
    logger.info("\n%s\n  %s\n%s", bar, title, bar)

# ---------------------------------------------------------------------------
# Import context module helpers
# ---------------------------------------------------------------------------
_ctx_path = os.path.join(_ROOT, "modules", "context", "main.py")
spec = importlib.util.spec_from_file_location("context_main", _ctx_path)
_ctx_module = importlib.util.module_from_spec(spec)
sys.modules["context_main"] = _ctx_module
spec.loader.exec_module(_ctx_module)  # type: ignore[union-attr]

get_session = _ctx_module.get_session
upsert_session = _ctx_module.upsert_session

from datetime import datetime

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

_UUID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.IGNORECASE
)


class InitiateCallRequest(BaseModel):
    sessionId: str
    customerPhone: Optional[str] = None   # E.164 number to dial, e.g. "+19195551234"


class InitiateCallResponse(BaseModel):
    callId: str
    status: str


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Kyron Medical — Voice Service",
    description="Initiates outbound Vapi calls with session context.",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/voice/initiate-call", response_model=InitiateCallResponse)
def initiate_call(body: InitiateCallRequest) -> InitiateCallResponse:
    """
    Fetch session from context store, build a context string from the last 10
    messages, and initiate an outbound Vapi call with that context injected
    into the assistant's systemPrompt.
    """
    _banner("INITIATE CALL")
    logger.info("sessionId=%s  customerPhone=%s", body.sessionId, body.customerPhone)

    session = get_session(body.sessionId)
    if session is None:
        logger.error("Session not found: %s", body.sessionId)
        raise HTTPException(status_code=404, detail="Session not found")

    # Build context string from the last 10 messages
    recent_messages = session.messages[-10:]
    logger.info("Session has %d total messages; using last %d for context",
                len(session.messages), len(recent_messages))
    context_lines = [
        f"{msg.role.capitalize()}: {msg.content}" for msg in recent_messages
    ]
    context_str = "\n".join(context_lines)

    # Graceful mock when VAPI_API_KEY is not set
    if not VAPI_API_KEY:
        logger.info("VAPI_API_KEY not set — returning mock call response.")
        return InitiateCallResponse(callId="mock-call-id", status="dialing")

    # VAPI_PHONE_NUMBER must be the UUID of the phone number in Vapi's dashboard
    # (Phone Numbers → click your number → copy the ID field, e.g. "a1b2c3d4-...")
    # NOT the E.164 number string like "+19195551234".
    if not VAPI_PHONE_NUMBER or not _UUID_RE.match(VAPI_PHONE_NUMBER):
        raise HTTPException(
            status_code=422,
            detail=(
                "VAPI_PHONE_NUMBER in .env must be the UUID of your Vapi phone number, "
                "not the E.164 phone number string. "
                "Find it in the Vapi dashboard under Phone Numbers → click your number → copy the 'ID' field "
                "(format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)."
            ),
        )

    # Resolve the customer phone: request body > session patient > error
    customer_phone = (
        body.customerPhone
        or (session.patient.phone if session.patient else None)
    )
    if not customer_phone:
        raise HTTPException(
            status_code=422,
            detail=(
                "No phone number to dial. Please provide a customerPhone in the request, "
                "or complete patient intake (with phone number) before initiating a voice call."
            ),
        )

    webhook_url = f"{FRONTEND_URL.rstrip('/')}/api/voice/webhook"

    # Fetch the live doctor list so the AI knows exact IDs to pass to tools
    doctors_str = "Unknown (call get_available_slots with no filter to discover)"
    try:
        with httpx.Client(timeout=5.0) as client:
            dr_resp = client.get("http://localhost:3001/api/schedule/doctors")
            if dr_resp.status_code == 200:
                doctors = dr_resp.json().get("doctors", [])
                doctor_lines = [
                    f"  - {d['name']} | specialty: {d['specialty']} | doctorId: {d['id']}"
                    for d in doctors
                ]
                doctors_str = "\n".join(doctor_lines)
                logger.info("Doctor lines - %d", doctor_lines)
                logger.info("Pre-fetched %d doctors for system prompt", len(doctors))
            else:
                logger.warning("Doctors endpoint returned %s", dr_resp.status_code)
    except Exception as exc:
        logger.warning("Could not pre-fetch doctors for system prompt: %s", exc)

    today_str = datetime.now().strftime("%Y-%m-%d")

    system_prompt = (
        "Your are technical recruiter at Google, you need to say sorry for the interviewer not making to the call and ask for availability to discuss a time for full time role. Congratulate the Candidate Abhinav for performing well in the technical round. Once they tell the availability just say 'ok great, I'll set up the meeting and send a calendar invite to you.'\n\n"
    )

    logger.info(system_prompt)

    tools_definition = [
        {
            "type": "function",
            "function": {
                "name": "request_appointment",
                "description": (
                    "Submit a complete appointment request. "
                    "Call this once you have confirmed the doctor or specialty, "
                    "preferred date, preferred time, and patient contact details. "
                    "The system will find the best matching slot, book it, and send a confirmation email."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doctorName": {
                            "type": "string",
                            "description": "Doctor name as spoken by patient (e.g. 'Dr. Sarah Chen', 'Dr. Chen')"
                        },
                        "specialty": {
                            "type": "string",
                            "description": "Specialty as spoken by patient (e.g. 'cardiology', 'knee specialist')"
                        },
                        "preferredDate": {
                            "type": "string",
                            "description": "Preferred date in YYYY-MM-DD format (e.g. 2026-03-25)"
                        },
                        "preferredTime": {
                            "type": "string",
                            "description": "Preferred time in HH:MM 24-hour format (e.g. '09:00', '14:00'). Use '09:00' for morning, '14:00' for afternoon if unspecific."
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for the visit as stated by the patient"
                        },
                        "patientFirstName": {
                            "type": "string",
                            "description": "Patient first name"
                        },
                        "patientLastName": {
                            "type": "string",
                            "description": "Patient last name"
                        },
                        "patientEmail": {
                            "type": "string",
                            "description": "Patient email address for confirmation"
                        },
                        "patientPhone": {
                            "type": "string",
                            "description": "Patient phone number in E.164 format (optional)"
                        }
                    },
                    "required": [
                        "preferredDate", "preferredTime",
                        "patientFirstName", "patientLastName", "patientEmail"
                    ]
                }
            },
            "server": {"url": webhook_url}
        }
    ]

    # Vapi schema for POST /call/phone:
    #   systemPrompt and tools belong INSIDE model (confirmed by 400 error
    #   when placed at assistant level).
    #   voice + transcriber are required for the assistant to actually speak
    #   and hear — without them the call connects but is silent.
    payload: dict[str, Any] = {
        "phoneNumberId": VAPI_PHONE_NUMBER,
        "customer":      {"number": customer_phone},
        "metadata":      {"sessionId": body.sessionId},
        "assistant": {
            "firstMessage": "Hi Abhinav, this is Laurie from Google, in regard to your interview process and firstly congratulations on clearing your first round. Since this is an Early career we would be discussing your relocation to Mountain view, California. When would be a good time to discuss this further with Bezoz - our talent recruiter?",
            # transcriber — tells Vapi how to convert patient speech to text
            "transcriber": {
                "provider": "deepgram",
                "model":    "nova-2",
                "language": "en",
            },
            # voice — tells Vapi how to convert assistant text to speech
            "voice": {
                "provider": "openai",
                "voiceId":  "alloy",
            },
            # model — LLM + system prompt + tools all live here
            "model": {
                "provider":     "openai",
                "model":        "gpt-4o-mini",
                "systemPrompt": system_prompt,
                # "tools":        tools_definition,
            },
        }
    }

    logger.info("Webhook URL for tools: %s", webhook_url)
    logger.info("Dispatching call to Vapi (phoneNumberId=%s, customer=%s)",
                VAPI_PHONE_NUMBER, customer_phone)

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                "https://api.vapi.ai/call/phone",
                json=payload,
                headers={
                    "Authorization": f"Bearer {VAPI_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # Try to extract Vapi's own error message for a useful response
        try:
            vapi_body = exc.response.json()
            vapi_msg = vapi_body.get("message") or vapi_body.get("error") or exc.response.text
        except Exception:
            vapi_msg = exc.response.text

        logger.error("Vapi API error: %s — %s", status, vapi_msg)

        if status == 401:
            raise HTTPException(
                status_code=401,
                detail=(
                    f"Vapi authentication failed: {vapi_msg}. "
                    "Check that VAPI_API_KEY in your .env is the correct key type "
                    "(Vapi uses a Private Key for server-side calls to /call/phone)."
                ),
            )
        raise HTTPException(
            status_code=502,
            detail=f"Vapi API returned {status}: {vapi_msg}",
        )
    except httpx.RequestError as exc:
        logger.error("Vapi request error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Failed to reach Vapi API: {exc}")

    call_id = data.get("id") or data.get("callId") or "unknown"
    logger.info("Vapi call created successfully. callId=%s", call_id)
    return InitiateCallResponse(callId=call_id, status="dialing")


# ---------------------------------------------------------------------------
# Tool implementations (called from webhook handler)
# ---------------------------------------------------------------------------

def _normalize_date(raw: str) -> Optional[str]:
    """
    Try to parse various date formats the AI might pass and return YYYY-MM-DD.
    Returns None if the date cannot be parsed.
    Examples handled: '2026-04-16', 'April 16', 'April 16th', 'Apr 16 2026', etc.
    """
    from datetime import date as _date
    import re as _re2
    raw = raw.strip()
    # Already correct format
    if _re2.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    # Try common formats
    for fmt in ("%B %d %Y", "%b %d %Y", "%B %dst %Y", "%B %dnd %Y",
                "%B %drd %Y", "%B %dth %Y", "%m/%d/%Y", "%m/%d/%y",
                "%B %d", "%b %d"):
        try:
            # Strip ordinal suffixes (1st, 2nd, 3rd, 4th)
            cleaned = _re2.sub(r"(\d+)(st|nd|rd|th)", r"\1", raw)
            parsed = datetime.strptime(cleaned, fmt)
            # If year is missing, assume next occurrence
            if parsed.year == 1900:
                today = datetime.now()
                parsed = parsed.replace(year=today.year)
                if parsed.date() < today.date():
                    parsed = parsed.replace(year=today.year + 1)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _resolve_doctor_id(args: dict, doctors: dict) -> Optional[str]:
    """Return a valid doctorId from args, using fuzzy matching as fallback."""
    # Try each possible field the AI might use
    for key in ("doctorId", "doctorName", "specialty"):
        needle = args.get(key, "").strip().lower()
        if not needle:
            continue
        # Exact ID match
        if needle in doctors:
            return needle
        # Fuzzy match on name or specialty
        for did, doc in doctors.items():
            if (needle in doc.get("name", "").lower()
                    or needle in doc.get("specialty", "").lower()):
                logger.info("Resolved '%s'='%s' → doctorId=%s", key, args[key], did)
                return did
    return None


def _tool_request_appointment(args: dict, session_id: str) -> str:
    """
    Single tool handler: the AI calls this once it has collected all needed info.

    Steps:
      1. Resolve doctorId from doctorName / specialty (fuzzy match)
      2. Normalise preferredDate → YYYY-MM-DD
      3. Fetch available slots (doctor + date filter)
      4. Pick the slot closest to preferredTime; fall back to first available
      5. POST /api/schedule/book
      6. POST /api/notify/email
      7. Update session
      8. Return JSON confirmation + spoken summary to AI

    The full appointment JSON is logged so the server console shows every field.
    """
    _banner("TOOL CALL → request_appointment")
    logger.info("Raw args from AI:\n%s", json.dumps(args, indent=2))
    logger.info("Session ID: %s", session_id)

    base = "http://localhost:3001"

    # ── Step 1: fetch doctors & resolve doctorId ─────────────────────────────
    logger.info("[1/5] Fetching doctor list")
    try:
        with httpx.Client(timeout=10.0) as c:
            dr = c.get(f"{base}/api/schedule/doctors")
        dr.raise_for_status()
        doctors = {d["id"]: d for d in dr.json().get("doctors", [])}
        logger.info("[1/5] Doctors available: %s", list(doctors.keys()))
    except Exception as exc:
        logger.error("[1/5] Could not fetch doctors: %s", exc)
        return "Sorry, I couldn't reach the scheduling service. Please try again."

    doctor_id = _resolve_doctor_id(args, doctors)
    doc_info  = doctors.get(doctor_id, {}) if doctor_id else {}
    logger.info("[1/5] doctorName=%r specialty=%r → resolved doctorId=%s (%s)",
                args.get("doctorName"), args.get("specialty"),
                doctor_id, doc_info.get("name", "unknown"))

    # ── Step 2: normalise date ───────────────────────────────────────────────
    raw_date  = (args.get("preferredDate") or "").strip()
    norm_date = _normalize_date(raw_date) if raw_date else None
    logger.info("[2/5] preferredDate=%r → normalised=%r", raw_date, norm_date)
    if not norm_date:
        logger.warning("[2/5] Could not parse date — will use first available slot")

    # ── Step 3: fetch slots ──────────────────────────────────────────────────
    params: dict = {}
    if doctor_id:
        params["doctorId"] = doctor_id
    if norm_date:
        params["date"] = norm_date
    logger.info("[3/5] GET /api/schedule/slots params=%s", params)
    try:
        with httpx.Client(timeout=10.0) as c:
            sr = c.get(f"{base}/api/schedule/slots", params=params)
        if sr.status_code == 400 and norm_date:
            # Date rejected — retry without date filter
            logger.warning("[3/5] Scheduler rejected date=%r (HTTP 400) — retrying without date", norm_date)
            params.pop("date")
            with httpx.Client(timeout=10.0) as c:
                sr = c.get(f"{base}/api/schedule/slots", params=params)
        sr.raise_for_status()
    except Exception as exc:
        logger.error("[3/5] Could not fetch slots: %s", exc)
        return "Sorry, I couldn't retrieve available slots right now. Please try again."

    all_slots = sr.json().get("slots", [])
    available = [s for s in all_slots if not s.get("booked")]
    logger.info("[3/5] %d total slots, %d available", len(all_slots), len(available))

    # If the requested date is a weekend or has no slots, try the next 7 weekdays
    if not available and norm_date:
        from datetime import date as _date, timedelta as _td
        try:
            requested = _date.fromisoformat(norm_date)
            is_weekend = requested.weekday() >= 5
            logger.info("[3/5] No slots on %s (%s) — scanning next 7 weekdays",
                        norm_date, "weekend" if is_weekend else "no availability")
            for delta in range(1, 8):
                candidate = (requested + _td(days=delta)).isoformat()
                if _date.fromisoformat(candidate).weekday() >= 5:
                    continue          # skip weekends
                fallback_params = {k: v for k, v in params.items()}
                fallback_params["date"] = candidate
                with httpx.Client(timeout=10.0) as c:
                    fb = c.get(f"{base}/api/schedule/slots", params=fallback_params)
                if fb.status_code == 200:
                    fb_slots = [s for s in fb.json().get("slots", []) if not s.get("booked")]
                    if fb_slots:
                        logger.info("[3/5] Found %d slots on fallback date %s", len(fb_slots), candidate)
                        available = fb_slots
                        norm_date = candidate
                        break
        except Exception as exc:
            logger.warning("[3/5] Weekday fallback scan failed: %s", exc)

    if not available:
        doc_hint = f" for {doc_info.get('name', doctor_id)}" if doctor_id else ""
        date_hint = f" on {norm_date or raw_date}" if (norm_date or raw_date) else ""
        msg = (f"No available slots found{doc_hint}{date_hint}. "
               "Please ask the patient to try a different date or doctor.")
        logger.warning("[3/5] %s", msg)
        return msg

    # ── Step 4: pick best slot by preferred time ─────────────────────────────
    pref_time = (args.get("preferredTime") or "09:00").strip()
    # Normalise "9 AM" → "09:00", "2pm" → "14:00" etc.
    _t = _re.sub(r"\s+", "", pref_time.lower())
    _t_match = _re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", _t)
    if _t_match:
        h, m_str, ampm = int(_t_match.group(1)), int(_t_match.group(2) or 0), _t_match.group(3)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        pref_time = f"{h:02d}:{m_str:02d}"
    logger.info("[4/5] preferredTime normalised → %r", pref_time)

    def _slot_distance(s: dict) -> int:
        """Minutes between slot time and preferred time (0 = perfect match)."""
        try:
            slot_t = s["datetime"].split("T")[1][:5]   # "HH:MM"
            sh, sm = map(int, slot_t.split(":"))
            ph, pm = map(int, pref_time.split(":"))
            return abs((sh * 60 + sm) - (ph * 60 + pm))
        except Exception:
            return 9999

    chosen = min(available, key=_slot_distance)
    logger.info("[4/5] Chosen slot: id=%s datetime=%s (distance=%d min from preferred %s)",
                chosen["id"], chosen["datetime"], _slot_distance(chosen), pref_time)

    # ── Step 5: book the slot ────────────────────────────────────────────────
    reason = args.get("reason") or "General visit"
    book_payload = {
        "sessionId": session_id or "voice-session",
        "slotId":    chosen["id"],
        "reason":    reason,
    }
    logger.info("[5/5] POST /api/schedule/book payload=%s", book_payload)
    try:
        with httpx.Client(timeout=10.0) as c:
            br = c.post(f"{base}/api/schedule/book", json=book_payload)
        logger.info("[5/5] Booking response: HTTP %s  body=%s", br.status_code, br.text[:400])
    except Exception as exc:
        logger.error("[5/5] Booking request failed: %s", exc)
        return "Sorry, I couldn't complete the booking. Please try again."

    if br.status_code not in (200, 201):
        try:
            detail = br.json().get("detail", br.text)
        except Exception:
            detail = br.text
        if br.status_code == 409:
            return ("That slot was just taken. Let me check for the next available slot — "
                    "please hold on while I look again.")
        return f"Booking failed: {detail}"

    appt = br.json().get("appointment", {})

    # Build the structured JSON result (logged in full)
    # Extract patient fields here so result_json and the email step share the same values
    patient_email = args.get("patientEmail", "").strip()
    patient_phone = args.get("patientPhone", "+10000000000").strip() or "+10000000000"
    patient_fn    = args.get("patientFirstName", "Patient").strip() or "Patient"
    patient_ln    = args.get("patientLastName", "").strip()

    result_json = {
        "status":           "confirmed",
        "appointmentId":    appt.get("id"),
        "doctorId":         appt.get("doctorId"),
        "doctorName":       doc_info.get("name") or args.get("doctorName", ""),
        "specialty":        doc_info.get("specialty") or args.get("specialty", ""),
        "slotId":           appt.get("slotId"),
        "datetime":         chosen["datetime"],
        "durationMinutes":  chosen.get("durationMinutes", 30),
        "reason":           appt.get("reason"),
        "patientFirstName": patient_fn,
        "patientLastName":  patient_ln,
        "patientEmail":     patient_email,
        "patientPhone":     patient_phone,
        "emailSent":        False,
    }
    logger.info("[5/5] Appointment JSON:\n%s", json.dumps(result_json, indent=2))

    # ── Step 6: send confirmation email (same flow as chat booking) ─────────
    logger.info("[6/6] Patient details — name: %s %s  email: %r  phone: %r",
                patient_fn, patient_ln, patient_email, patient_phone)

    if patient_email:
        patient_obj = {
            "id":        session_id or "voice-patient",
            "firstName": patient_fn,
            "lastName":  patient_ln,
            "dob":       "1900-01-01",
            "phone":     patient_phone,
            "email":     patient_email,
            "smsOptIn":  False,
        }
        # appt dict must match the Appointment model: id, patientId, doctorId,
        # slotId, reason, confirmedAt, emailSent, smsSent
        notify_payload = {"appointment": appt, "patient": patient_obj}
        logger.info("[6/6] POST /api/notify/email  payload keys: appointment.id=%s patient.email=%s",
                    appt.get("id"), patient_email)
        try:
            with httpx.Client(timeout=10.0) as c:
                er = c.post(f"{base}/api/notify/email", json=notify_payload)
            logger.info("[6/6] Email API: HTTP %s  body=%s", er.status_code, er.text[:300])
            result_json["emailSent"] = (er.status_code == 200)
            if er.status_code != 200:
                logger.warning("[6/6] Email returned non-200: %s — %s", er.status_code, er.text)
        except Exception as exc:
            logger.warning("[6/6] Email request failed (non-fatal): %s", exc)
    else:
        logger.warning("[6/6] patientEmail is empty — cannot send confirmation email")

    # ── Step 7: update session ───────────────────────────────────────────────
    if session_id:
        try:
            sess = get_session(session_id)
            if sess:
                from context_main import Appointment as CtxAppt  # type: ignore
                sess.appointment = CtxAppt(**appt)
                upsert_session(sess)
                logger.info("Session %s updated with appointment %s", session_id, appt.get("id"))
        except Exception as exc:
            logger.warning("Session update failed (non-fatal): %s", exc)

    # ── Return spoken summary + embedded JSON for downstream use ─────────────
    spoken = (
        f"Your appointment is confirmed with {result_json['doctorName']} "
        f"on {chosen['datetime'].replace('T', ' at ')}. "
        f"Your confirmation ID is {result_json['appointmentId']}. "
        + (f"A confirmation email will be sent to {patient_email}." if patient_email else "")
        + f" APPOINTMENT_JSON:{json.dumps(result_json)}"
    )
    logger.info("Returning to AI: %s", spoken[:300])
    return spoken


def handle_tool_calls(msg: dict) -> dict:
    """
    Dispatch Vapi tool-call events to the appropriate handler.

    Vapi sends:
      { "type": "tool-calls",
        "toolCallList": [{"id": "...", "function": {"name": "...", "arguments": "{...}"}}],
        "call": {"id": "...", "metadata": {"sessionId": "..."}} }

    We respond with:
      { "results": [{"toolCallId": "...", "result": "<string>"}] }
    """
    call_obj     = msg.get("call") or {}
    session_id   = call_obj.get("metadata", {}).get("sessionId", "")
    call_id_vapi = call_obj.get("id", "unknown")
    tool_list    = msg.get("toolCallList", [])

    logger.info("Tool-calls batch: callId=%s  sessionId=%s  %d tool(s)",
                call_id_vapi, session_id, len(tool_list))

    results = []
    for i, tool_call in enumerate(tool_list, start=1):
        tc_id    = tool_call.get("id", "")
        fn_name  = (tool_call.get("function") or {}).get("name", "")
        raw_args = (tool_call.get("function") or {}).get("arguments", "{}")
        # Vapi sometimes sends arguments as an already-parsed dict, sometimes as a JSON string.
        # json.loads(dict) raises TypeError, so we handle both explicitly.
        if isinstance(raw_args, dict):
            args = raw_args
            logger.info("Arguments already parsed as dict (Vapi pre-parsed)")
        else:
            try:
                args = json.loads(raw_args)
            except Exception:
                logger.warning("Could not parse args JSON for tool %r: %r", fn_name, raw_args)
                args = {}
        logger.info("Parsed args: %s", json.dumps(args, indent=2))

        logger.info("── Tool %d/%d  name=%r  toolCallId=%s", i, len(tool_list), fn_name, tc_id)

        try:
            if fn_name == "request_appointment":
                result_str = _tool_request_appointment(args, session_id)
            else:
                result_str = f"Unknown tool '{fn_name}'. Only request_appointment is supported."
                logger.warning("Unknown tool called: %r", fn_name)
        except Exception as exc:
            logger.exception("Tool %r raised unhandled exception: %s", fn_name, exc)
            result_str = f"Internal error in {fn_name}: {exc}"

        logger.info("── Tool %r result (%d chars): %s",
                    fn_name, len(result_str),
                    result_str[:300] + ("…" if len(result_str) > 300 else ""))
        results.append({"toolCallId": tc_id, "result": result_str})

    logger.info("Returning %d result(s) to Vapi", len(results))
    return {"results": results}


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/api/voice/webhook")
def webhook(body: dict[str, Any]) -> dict:
    """
    Handle inbound Vapi webhook events.
    Dispatches tool-calls to handle_tool_calls().
    Logs call-ended / end-of-call-report events.
    """
    msg = body.get("message", body)   # Vapi wraps events in "message"
    msg_type = msg.get("type") or body.get("type") or ""

    _banner(f"WEBHOOK EVENT: {msg_type.upper() or 'UNKNOWN'}")
    logger.info("Top-level keys : %s", list(body.keys()))
    logger.info("msg keys       : %s", list(msg.keys()))

    if msg_type == "tool-calls":
        # Log the full raw tool-call payload for debugging
        logger.info("Full tool-call body:\n%s",
                    json.dumps(body, indent=2, default=str)[:2000])
        return handle_tool_calls(msg)

    if msg_type == "speech-update":
        # Frequent event — log concisely to avoid log spam
        role   = (msg.get("speech") or {}).get("role", "?")
        status = (msg.get("speech") or {}).get("status", "?")
        logger.info("Speech update: role=%s status=%s", role, status)
        return {"received": True}

    if msg_type in ("end-of-call-report", "call-ended", "hang"):
        session_id = (msg.get("call") or {}).get("metadata", {}).get("sessionId")
        call_id    = (msg.get("call") or {}).get("id", "unknown")
        duration   = msg.get("durationSeconds") or (msg.get("call") or {}).get("duration")
        logger.info("Call ended. callId=%s sessionId=%s duration=%ss", call_id, session_id, duration)
        # Log transcript if included
        transcript = msg.get("transcript") or (msg.get("call") or {}).get("transcript")
        if transcript:
            logger.info("Call transcript:\n%s", transcript[:3000])

    logger.info("Returning received=True for event type=%r", msg_type)
    return {"received": True}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=False)

"""
AI Core Service for Kyron Medical Patient Portal.

Endpoints:
  POST /api/session          -> { sessionId: str }
  GET  /api/session/{id}     -> { session: Session }
  POST /api/chat             -> { reply: str, intent: Intent, session: Session }

Uses OpenAI gpt-4o-mini for conversation, intent classification.
Delegates session persistence to the context module.
Runs safety guardrails via the safety module.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

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

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
PORT: int = int(os.getenv("PORT", "3001"))

# ---------------------------------------------------------------------------
# Import context module helpers
# Use importlib to load context/main.py by file path to avoid name collision
# with this file (both are named "main").
# ---------------------------------------------------------------------------
import importlib.util as _ilu

_CONTEXT_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "context", "main.py"
)
_context_spec = _ilu.spec_from_file_location("context_main", _CONTEXT_MODULE_PATH)
_context_mod = _ilu.module_from_spec(_context_spec)  # type: ignore
# Register in sys.modules BEFORE exec so that internal forward-reference
# resolution and Pydantic model_rebuild work correctly.
sys.modules["context_main"] = _context_mod
_context_spec.loader.exec_module(_context_mod)  # type: ignore

# Call model_rebuild on Pydantic models to resolve any forward references
# that rely on Optional being available in the module namespace.
for _model_name in ("Patient", "Slot", "Doctor", "Appointment", "Message", "Session"):
    _model_cls = getattr(_context_mod, _model_name, None)
    if _model_cls is not None and hasattr(_model_cls, "model_rebuild"):
        _model_cls.model_rebuild()

Session = _context_mod.Session
Message = _context_mod.Message
Patient = _context_mod.Patient
Appointment = _context_mod.Appointment
get_session = _context_mod.get_session
upsert_session = _context_mod.upsert_session

# ---------------------------------------------------------------------------
# Import safety helpers
# Use importlib to load safety/guardrails.py by file path.
# ---------------------------------------------------------------------------
_SAFETY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "safety"
)
if _SAFETY_PATH not in sys.path:
    sys.path.append(_SAFETY_PATH)

from guardrails import sanitize_response, check_out_of_scope, SAFE_REDIRECT  # type: ignore  # noqa: E402

# ---------------------------------------------------------------------------
# OpenAI client (lazy import so tests can patch before import)
# ---------------------------------------------------------------------------
from openai import OpenAI  # noqa: E402

def _get_openai_client() -> OpenAI:
    return OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------------------------------------------------------
# Intent type
# ---------------------------------------------------------------------------
Intent = Literal[
    "INTAKE",
    "SCHEDULING",
    "RX_REFILL",
    "OFFICE_INFO",
    "CALL_REQUESTED",
    "COMPLETED",
    "OUT_OF_SCOPE",
]

VALID_INTENTS = {
    "INTAKE",
    "SCHEDULING",
    "RX_REFILL",
    "OFFICE_INFO",
    "CALL_REQUESTED",
    "COMPLETED",
    "OUT_OF_SCOPE",
}

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    sessionId: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    intent: str
    session: dict


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a helpful patient intake and scheduling assistant for Kyron Medical, a multi-specialty medical practice.

Your responsibilities:
1. Collect patient information (name, date of birth, phone, email) — intent: INTAKE
2. Help patients schedule appointments by matching their needs to appropriate doctors — intent: SCHEDULING
3. Handle prescription refill inquiries — intent: RX_REFILL
4. Answer questions about office hours, location, and contact information — intent: OFFICE_INFO
5. Arrange a callback when a patient wants to speak with someone — intent: CALL_REQUESTED
6. Confirm completed bookings — intent: COMPLETED
7. Redirect clearly off-topic requests — intent: OUT_OF_SCOPE

CRITICAL RULES — you must NEVER violate these:
- NEVER provide medical advice, treatment recommendations, or diagnoses of any kind.
- NEVER suggest medications, dosages, or drug interactions.
- NEVER interpret symptoms or tell a patient what condition they might have.
- If a patient asks for medical advice, politely decline and encourage them to speak with a doctor.

You must respond ONLY with valid JSON in this exact format:
{"reply": "<your response to the patient>", "intent": "<one of: INTAKE, SCHEDULING, RX_REFILL, OFFICE_INFO, CALL_REQUESTED, COMPLETED, OUT_OF_SCOPE>"}

When you have collected all patient information (firstName, lastName, dob, phone, email), include a "patient" object in your JSON response:
{"reply": "...", "intent": "INTAKE", "patient": {"firstName": "...", "lastName": "...", "dob": "YYYY-MM-DD", "phone": "+1...", "email": "..."}}

Choose the intent that best describes your response. Use OUT_OF_SCOPE for anything unrelated to healthcare scheduling or the practice."""


# ---------------------------------------------------------------------------
# Helper: create a fresh session
# ---------------------------------------------------------------------------

def _create_new_session() -> Session:
    now = datetime.now(timezone.utc).isoformat()
    session = Session(
        id=str(uuid.uuid4()),
        messages=[],
        createdAt=now,
        lastActiveAt=now,
    )
    upsert_session(session)
    return session


# ---------------------------------------------------------------------------
# Helper: call OpenAI and parse JSON reply
# ---------------------------------------------------------------------------

def _call_openai(messages: list[dict]) -> tuple[str, str, dict]:
    """
    Call OpenAI chat completions with the given message history.
    Returns (reply_text, intent, full_parsed_dict).
    """
    client = _get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    raw_content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw_content)
        reply = parsed.get("reply", "I'm sorry, I didn't understand that. Could you rephrase?")
        intent = parsed.get("intent", "INTAKE")
        if intent not in VALID_INTENTS:
            intent = "INTAKE"
    except (json.JSONDecodeError, AttributeError):
        parsed = {}
        reply = raw_content
        intent = "INTAKE"
    return reply, intent, parsed


# ---------------------------------------------------------------------------
# Helper: build OpenAI message list from session history
# ---------------------------------------------------------------------------

def _build_openai_messages(session: Session) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in session.messages:
        role = msg.role if msg.role in ("user", "assistant") else "user"
        messages.append({"role": role, "content": msg.content})
    return messages


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Kyron Medical — AI Core Service",
    description="AI-powered patient intake and scheduling assistant.",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/session")
def create_session():
    """Create a new empty session and return its ID."""
    session = _create_new_session()
    return {"sessionId": session.id}


@app.get("/api/session/{session_id}")
def read_session(session_id: str):
    """Retrieve a session by ID."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": session.model_dump()}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Process a patient message:
    1. Load or create session.
    2. Append user message.
    3. Check if out of scope (skip OpenAI call if so).
    4. Build message history and call OpenAI.
    5. Sanitize reply via safety guardrails.
    6. Append assistant message and persist session.
    7. Return reply, intent, and updated session.
    """
    # 1. Load session (create if missing)
    session = get_session(request.sessionId)
    if session is None:
        now = datetime.now(timezone.utc).isoformat()
        session = Session(
            id=request.sessionId,
            messages=[],
            createdAt=now,
            lastActiveAt=now,
        )

    # 2. Append user message
    user_msg = Message(
        role="user",
        content=request.message,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    session.messages.append(user_msg)

    # 3. Check out of scope early
    if check_out_of_scope(request.message):
        reply = (
            "I'm sorry, that topic is outside the scope of what I can help with here. "
            "I can assist you with scheduling appointments, prescription refill requests, "
            "or general information about Kyron Medical. How can I help you today?"
        )
        intent = "OUT_OF_SCOPE"
    else:
        # 4. Build message history and call OpenAI
        openai_messages = _build_openai_messages(session)
        # Build from all messages including the current user message
        reply, intent, parsed = _call_openai(openai_messages)

        # 5. Sanitize reply — if the safety module replaced the reply, set intent to OUT_OF_SCOPE
        reply = sanitize_response(reply)
        if reply == SAFE_REDIRECT:
            intent = "OUT_OF_SCOPE"

        # 5a. If the model returned a patient object with all required fields, store it
        if intent == "INTAKE" and session.patient is None:
            patient_data = parsed.get("patient")
            if isinstance(patient_data, dict):
                required_patient_fields = {"firstName", "lastName", "dob", "phone", "email"}
                if required_patient_fields.issubset(patient_data.keys()) and all(
                    patient_data.get(f) for f in required_patient_fields
                ):
                    session.patient = Patient(
                        id=str(uuid.uuid4()),
                        firstName=patient_data["firstName"],
                        lastName=patient_data["lastName"],
                        dob=patient_data["dob"],
                        phone=patient_data["phone"],
                        email=patient_data["email"],
                        smsOptIn=bool(patient_data.get("smsOptIn", False)),
                    )

    # 6. Append assistant message and update lastActiveAt
    assistant_msg = Message(
        role="assistant",
        content=reply,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    session.messages.append(assistant_msg)
    session.lastActiveAt = datetime.now(timezone.utc).isoformat()

    # 7. Persist session
    upsert_session(session)

    return ChatResponse(
        reply=reply,
        intent=intent,
        session=session.model_dump(),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

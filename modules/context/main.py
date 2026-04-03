"""
Context / Session sub-service for Kyron Medical.

Provides:
  POST /api/session          → { sessionId: str }
  GET  /api/session/{id}     → { session: Session }

Also exposes importable helpers for the AI core agent:
  get_session(session_id: str) -> Optional[Session]
  upsert_session(session: Session) -> None

Storage: Redis (via REDIS_URL env var) with in-memory dict fallback.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Load env from project root .env
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_ROOT, ".env"))

REDIS_URL: Optional[str] = os.getenv("REDIS_URL")
PORT: int = int(os.getenv("PORT", "3001"))

# ---------------------------------------------------------------------------
# Pydantic models  (mirroring types.ts — no local redefinition of business
# logic, just the shapes needed for serialisation)
# ---------------------------------------------------------------------------


class Patient(BaseModel):
    id: str
    firstName: str
    lastName: str
    dob: str          # "YYYY-MM-DD"
    phone: str        # E.164
    email: str
    smsOptIn: bool


class Slot(BaseModel):
    id: str
    doctorId: str
    datetime: str     # ISO 8601
    durationMinutes: int
    booked: bool


class Doctor(BaseModel):
    id: str
    name: str
    specialty: str
    bodyParts: list[str]
    slots: list[Slot]


class Appointment(BaseModel):
    id: str
    patientId: str
    doctorId: str
    slotId: str
    reason: str
    confirmedAt: str  # ISO 8601
    emailSent: bool
    smsSent: bool


class Message(BaseModel):
    role: str         # "user" | "assistant"
    content: str
    timestamp: str    # ISO 8601


class Session(BaseModel):
    id: str
    patient: Optional[Patient] = None
    appointment: Optional[Appointment] = None
    messages: list[Message] = []
    createdAt: str
    lastActiveAt: str


# ---------------------------------------------------------------------------
# Storage backend
# ---------------------------------------------------------------------------

_REDIS_KEY_PREFIX = "kyron:session:"
_in_memory_store: dict[str, dict] = {}

# Attempt to create a synchronous Redis client if REDIS_URL is set.
_redis_client = None
if REDIS_URL:
    try:
        import redis as _redis_lib  # type: ignore

        _redis_client = _redis_lib.from_url(REDIS_URL, decode_responses=True)
        # Ping to verify connectivity; fall back to in-memory on failure.
        _redis_client.ping()
    except Exception:
        _redis_client = None


def _serialize(session: Session) -> str:
    return session.model_dump_json()


def _deserialize(raw: str) -> Session:
    return Session.model_validate_json(raw)


def get_session(session_id: str) -> Optional[Session]:
    """Return a Session by ID, or None if not found."""
    if _redis_client is not None:
        raw = _redis_client.get(f"{_REDIS_KEY_PREFIX}{session_id}")
        if raw is None:
            return None
        return _deserialize(raw)
    # In-memory fallback
    data = _in_memory_store.get(session_id)
    if data is None:
        return None
    return Session.model_validate(data)


def upsert_session(session: Session) -> None:
    """Persist (create or overwrite) a session.

    Always updates ``lastActiveAt`` to the current UTC time so callers do not
    need to manage that timestamp themselves.
    """
    # Stamp the activity time on every write.
    session = session.model_copy(
        update={"lastActiveAt": datetime.now(timezone.utc).isoformat()}
    )
    if _redis_client is not None:
        _redis_client.set(
            f"{_REDIS_KEY_PREFIX}{session.id}",
            _serialize(session),
        )
        return
    # In-memory fallback
    _in_memory_store[session.id] = session.model_dump()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Kyron Medical — Context/Session Service",
    description="Session management for the Kyron Medical patient portal.",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/session", response_model=dict)
def create_session():
    """Create a new empty session and return its ID."""
    now = datetime.now(timezone.utc).isoformat()
    session = Session(
        id=str(uuid.uuid4()),
        messages=[],
        createdAt=now,
        lastActiveAt=now,
    )
    upsert_session(session)
    return {"sessionId": session.id}


@app.get("/api/session/{session_id}", response_model=dict)
def read_session(session_id: str):
    """Retrieve a session by ID."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": session.model_dump()}


@app.get("/api/session/{session_id}/messages", response_model=dict)
def read_session_messages(session_id: str):
    """Debug/diagnostic endpoint: return the messages stored in a session.

    Response shape:
      { sessionId: str, count: int, messages: list[Message] }

    Useful for verifying what the voice module will see when it fetches the
    session context.
    """
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "sessionId": session.id,
        "count": len(session.messages),
        "messages": [m.model_dump() for m in session.messages],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)

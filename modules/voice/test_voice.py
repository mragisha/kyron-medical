"""
Pytest smoke tests for the voice module.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Stub out the context_main module before importing main so the dynamic
# importlib.util load doesn't require Redis or a real context service.
# ---------------------------------------------------------------------------

def _make_stub_context():
    """Return a stub context module with get_session / upsert_session."""
    stub = types.ModuleType("context_main")

    _store: dict = {}

    def get_session(session_id: str):
        return _store.get(session_id)

    def upsert_session(session):
        _store[session.id] = session

    stub.get_session = get_session
    stub.upsert_session = upsert_session
    stub._store = _store
    return stub


# Inject stub before importing main
_stub_ctx = _make_stub_context()
sys.modules["context_main"] = _stub_ctx


# Patch importlib.util so the loader in main.py returns our stub instead of
# executing the real context/main.py (which would try to connect to Redis).
_real_spec_from_file = importlib.util.spec_from_file_location


def _patched_spec_from_file(name, location, *args, **kwargs):
    if name == "context_main":
        return None  # will be caught below
    return _real_spec_from_file(name, location, *args, **kwargs)


# We monkeypatch at the importlib.util level so main.py's top-level code
# falls back to the already-registered sys.modules["context_main"] entry.
with patch("importlib.util.spec_from_file_location", side_effect=_patched_spec_from_file):
    # Re-ensure stub is in sys.modules
    sys.modules["context_main"] = _stub_ctx
    # Now import main; but spec_from_file_location returns None for context_main
    # which means spec.loader.exec_module will fail.  Better approach:
    # just let the real path execute but pre-seed sys.modules so the module
    # isn't re-executed.  Reset and do it the simple way.
    pass

# Simpler approach: pre-seed sys.modules["context_main"] and then import
# main normally — main.py will overwrite sys.modules["context_main"] with the
# real module UNLESS we make the spec_from_file_location path fail gracefully.
# The safest way is to patch importlib.util.spec_from_file_location to return
# a spec whose loader does nothing (since stub is already in sys.modules).

import importlib.util as _ilu

_original_sffl = _ilu.spec_from_file_location


def _stub_sffl(name, location=None, *args, **kwargs):
    if name == "context_main":
        # Return a fake spec whose loader just no-ops
        fake_spec = MagicMock()
        fake_spec.loader = MagicMock()
        fake_spec.loader.exec_module = lambda mod: None
        return fake_spec
    return _original_sffl(name, location, *args, **kwargs)


_ilu.spec_from_file_location = _stub_sffl
sys.modules["context_main"] = _stub_ctx

# Now import main — it will call spec_from_file_location (gets our stub),
# call module_from_spec (returns a MagicMock), register it, call exec_module
# (no-op), then do get_session = ctx_module.get_session which is a MagicMock.
# We need to ensure the voice main module sees our real stub functions.
# Solution: after import, patch main.get_session / main.upsert_session.

import main as voice_main  # noqa: E402

# Restore original spec_from_file_location
_ilu.spec_from_file_location = _original_sffl

# Wire stub functions into the voice module
voice_main.get_session = _stub_ctx.get_session
voice_main.upsert_session = _stub_ctx.upsert_session

client = TestClient(voice_main.app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(messages=None):
    """Create and store a session in the stub store, return session id."""
    from context_main import upsert_session  # type: ignore

    # Build a minimal Session-like object compatible with the context module
    # Using the real Session pydantic model from context_main
    import importlib as _imp
    ctx = _imp.import_module("context_main")

    now = datetime.now(timezone.utc).isoformat()
    session_id = str(uuid.uuid4())

    # Build a simple namespace object that matches the Session shape
    # (the stub store stores whatever is passed to upsert_session)
    session = types.SimpleNamespace(
        id=session_id,
        patient=None,
        appointment=None,
        messages=messages or [],
        createdAt=now,
        lastActiveAt=now,
    )
    _stub_ctx._store[session_id] = session
    return session_id


def _make_message(role: str, content: str):
    now = datetime.now(timezone.utc).isoformat()
    return types.SimpleNamespace(role=role, content=content, timestamp=now)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInitiateCall:
    def test_valid_session_no_vapi_key_returns_mock(self):
        """With no VAPI_API_KEY, should return mock-call-id with status dialing."""
        session_id = _make_session(
            messages=[
                _make_message("user", "I need to book an appointment"),
                _make_message("assistant", "Sure, let me help you with that."),
            ]
        )
        voice_main.VAPI_API_KEY = None  # ensure no key

        resp = client.post("/api/voice/initiate-call", json={"sessionId": session_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["callId"] == "mock-call-id"
        assert data["status"] == "dialing"

    def test_missing_session_returns_404(self):
        """A sessionId that does not exist should return 404."""
        voice_main.VAPI_API_KEY = None

        resp = client.post(
            "/api/voice/initiate-call",
            json={"sessionId": "nonexistent-session-id"},
        )
        assert resp.status_code == 404

    def test_missing_session_id_field_returns_422(self):
        """Request body without sessionId should return 422 validation error."""
        resp = client.post("/api/voice/initiate-call", json={})
        assert resp.status_code == 422

    def test_valid_session_with_vapi_key_calls_vapi(self):
        """With a VAPI_API_KEY set, should call Vapi and return callId + dialing."""
        session_id = _make_session(
            messages=[
                _make_message("user", "Hello"),
                _make_message("assistant", "Hi there!"),
            ]
        )
        voice_main.VAPI_API_KEY = "test-key-123"
        # Must be a valid UUID — Vapi rejects anything else as phoneNumberId
        voice_main.VAPI_PHONE_NUMBER = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "vapi-call-xyz"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(
                return_value=mock_client_instance
            )
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client_instance.post.return_value = mock_response

            resp = client.post(
                "/api/voice/initiate-call",
                json={"sessionId": session_id, "customerPhone": "+19195551234"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["callId"] == "vapi-call-xyz"
        assert data["status"] == "dialing"

        # Verify the Vapi endpoint was called with correct args
        call_args = mock_client_instance.post.call_args
        assert call_args[0][0] == "https://api.vapi.ai/call/phone"
        payload = call_args[1]["json"]

        assert payload["assistant"]["firstMessage"] == (
            "Hi, I'm continuing from your chat with Kyron Medical. How can I help you today?"
        )

        # systemPrompt and tools are inside model (Vapi schema requirement)
        model = payload["assistant"]["model"]
        assert "Hello" in model["systemPrompt"]
        assert "PREVIOUS CHAT CONTEXT" in model["systemPrompt"]
        # Single request_appointment tool — collect-then-book design
        tools = model["tools"]
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "request_appointment"
        # Tool must include required booking fields
        required = tools[0]["function"]["parameters"]["required"]
        assert "preferredDate" in required
        assert "patientEmail" in required

        # voice + transcriber must be present so the assistant can speak/hear
        assert payload["assistant"]["voice"]["provider"] == "openai"
        assert payload["assistant"]["transcriber"]["provider"] == "deepgram"

        # customer.number is the correct Vapi field (not customerPhoneNumber)
        assert payload["customer"]["number"] == "+19195551234"

        # Reset key
        voice_main.VAPI_API_KEY = None


class TestWebhook:
    def test_generic_event_returns_received(self):
        """Any webhook body should return 200 with received: true."""
        resp = client.post(
            "/api/voice/webhook",
            json={"type": "call-started", "callId": "abc123"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"received": True}

    def test_call_ended_event_returns_received(self):
        """call-ended event should be logged and return received: true."""
        resp = client.post(
            "/api/voice/webhook",
            json={
                "type": "call-ended",
                "call": {"id": "ended-call-id"},
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"received": True}

    def test_empty_body_returns_received(self):
        """Empty JSON body is valid — Vapi may send sparse payloads."""
        resp = client.post("/api/voice/webhook", json={})
        assert resp.status_code == 200
        assert resp.json() == {"received": True}

    def test_webhook_tool_call_request_appointment(self):
        """
        POST a tool-calls message for request_appointment to /api/voice/webhook.
        Backend should resolve doctor, find the closest slot, book it, and return
        a confirmation string containing the appointment ID.
        """
        doctors_response = MagicMock()
        doctors_response.json.return_value = {
            "doctors": [
                {"id": "doc-1", "name": "Dr. Smith", "specialty": "General"}
            ]
        }

        slots_response = MagicMock()
        slots_response.status_code = 200
        slots_response.json.return_value = {
            "slots": [
                {
                    "id": "slot-1",
                    "doctorId": "doc-1",
                    "datetime": "2026-03-20T09:00:00",
                    "durationMinutes": 30,
                    "booked": False,
                }
            ]
        }

        book_response = MagicMock()
        book_response.status_code = 201
        book_response.json.return_value = {
            "appointment": {
                "id": "appt-999",
                "patientId": "session-xyz",
                "doctorId": "doc-1",
                "slotId": "slot-1",
                "reason": "checkup",
                "confirmedAt": "2026-03-20T09:00:00Z",
                "emailSent": False,
                "smsSent": False,
            }
        }

        tool_call_body = {
            "type": "tool-calls",
            "toolCallList": [
                {
                    "id": "tc-req-001",
                    "function": {
                        "name": "request_appointment",
                        "arguments": json.dumps({
                            "doctorName": "Dr. Smith",
                            "specialty": "General",
                            "preferredDate": "2026-03-20",
                            "preferredTime": "09:00",
                            "reason": "checkup",
                            "patientFirstName": "Jane",
                            "patientLastName": "Doe",
                            "patientEmail": "jane@example.com",
                        })
                    }
                }
            ],
            "call": {
                "id": "call-abc",
                "metadata": {"sessionId": "session-xyz"}
            }
        }

        with patch("httpx.Client") as mock_client_cls:
            mock_http = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_http)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            # doctors fetch → slots fetch → book POST → email POST
            mock_http.get.side_effect = [doctors_response, slots_response]
            mock_http.post.return_value = book_response

            resp = client.post("/api/voice/webhook", json=tool_call_body)

        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["toolCallId"] == "tc-req-001"
        result_text = data["results"][0]["result"]
        # Must contain confirmation ID and "confirmed"
        assert "appt-999" in result_text
        assert "confirmed" in result_text.lower()
        # Must embed the structured JSON
        assert "APPOINTMENT_JSON:" in result_text

    def test_webhook_unknown_tool_returns_error_string(self):
        """
        Calling an unknown tool should return an error string, not a 500.
        """
        tool_call_body = {
            "type": "tool-calls",
            "toolCallList": [
                {
                    "id": "tc-unknown-001",
                    "function": {
                        "name": "nonexistent_tool",
                        "arguments": "{}"
                    }
                }
            ],
            "call": {"id": "call-abc", "metadata": {"sessionId": "session-xyz"}}
        }
        resp = client.post("/api/voice/webhook", json=tool_call_body)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "Unknown tool" in data["results"][0]["result"]

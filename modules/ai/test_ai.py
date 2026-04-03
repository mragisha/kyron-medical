"""
Smoke tests for the Kyron Medical AI Core Service.

Tests run with TestClient (synchronous). OpenAI is mocked so no real API
key is required.
"""

from __future__ import annotations

import json
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

# Ensure the AI module's own directory is first in sys.path so that
# `import main` resolves to /modules/ai/main.py and not any other module
# named main (e.g. safety or context).
_AI_DIR = os.path.dirname(os.path.abspath(__file__))
if _AI_DIR not in sys.path:
    sys.path.insert(0, _AI_DIR)

# Ensure context and safety modules are importable before we import main
_MODULES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONTEXT_PATH = os.path.join(_MODULES_DIR, "context")
_SAFETY_PATH = os.path.join(_MODULES_DIR, "safety")
if _CONTEXT_PATH not in sys.path:
    sys.path.append(_CONTEXT_PATH)
if _SAFETY_PATH not in sys.path:
    sys.path.append(_SAFETY_PATH)

from fastapi.testclient import TestClient

# Import the app — this must come after the sys.path setup above
import importlib
import main as _ai_main  # type: ignore
# Re-import to ensure we have the right main module
app = _ai_main.app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_openai_response(reply: str = "Hello! How can I help you today?", intent: str = "INTAKE"):
    """Build a mock object that looks like an OpenAI ChatCompletion response."""
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({"reply": reply, "intent": intent})

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def _make_mock_openai_response_with_payload(payload: dict):
    """Build a mock OpenAI response whose content is an arbitrary JSON payload."""
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(payload)

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_post_session_returns_session_id(self):
        response = client.post("/api/session")
        assert response.status_code == 200
        data = response.json()
        assert "sessionId" in data
        assert isinstance(data["sessionId"], str)
        assert len(data["sessionId"]) > 0

    def test_each_session_has_unique_id(self):
        resp1 = client.post("/api/session")
        resp2 = client.post("/api/session")
        assert resp1.json()["sessionId"] != resp2.json()["sessionId"]


class TestGetSession:
    def test_get_existing_session_returns_session(self):
        # Create a session first
        create_resp = client.post("/api/session")
        session_id = create_resp.json()["sessionId"]

        # Retrieve it
        get_resp = client.get(f"/api/session/{session_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert "session" in data
        session = data["session"]

        # Verify shape
        assert session["id"] == session_id
        assert "messages" in session
        assert isinstance(session["messages"], list)
        assert "createdAt" in session
        assert "lastActiveAt" in session

    def test_get_nonexistent_session_returns_404(self):
        response = client.get("/api/session/nonexistent-id-12345")
        assert response.status_code == 404

    def test_session_optional_fields_absent_by_default(self):
        create_resp = client.post("/api/session")
        session_id = create_resp.json()["sessionId"]

        get_resp = client.get(f"/api/session/{session_id}")
        session = get_resp.json()["session"]

        # patient and appointment are optional — may be None or absent
        assert session.get("patient") is None
        assert session.get("appointment") is None


class TestChat:
    def test_chat_returns_required_fields(self):
        # Create a session
        session_id = client.post("/api/session").json()["sessionId"]

        mock_response = _make_mock_openai_response(
            reply="Welcome to Kyron Medical! Could I get your name please?",
            intent="INTAKE",
        )

        with patch("main._get_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            response = client.post(
                "/api/chat",
                json={"sessionId": session_id, "message": "I need to book an appointment"},
            )

        assert response.status_code == 200
        data = response.json()

        assert "reply" in data
        assert "intent" in data
        assert "session" in data

    def test_chat_reply_is_string(self):
        session_id = client.post("/api/session").json()["sessionId"]
        mock_response = _make_mock_openai_response("I can help with scheduling.", "SCHEDULING")

        with patch("main._get_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            response = client.post(
                "/api/chat",
                json={"sessionId": session_id, "message": "I want to see a doctor"},
            )

        data = response.json()
        assert isinstance(data["reply"], str)
        assert len(data["reply"]) > 0

    def test_chat_intent_is_valid(self):
        session_id = client.post("/api/session").json()["sessionId"]
        valid_intents = {
            "INTAKE", "SCHEDULING", "RX_REFILL", "OFFICE_INFO",
            "CALL_REQUESTED", "COMPLETED", "OUT_OF_SCOPE",
        }
        mock_response = _make_mock_openai_response("Sure, let me help.", "SCHEDULING")

        with patch("main._get_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            response = client.post(
                "/api/chat",
                json={"sessionId": session_id, "message": "Can I schedule an appointment?"},
            )

        data = response.json()
        assert data["intent"] in valid_intents

    def test_chat_session_contains_messages(self):
        session_id = client.post("/api/session").json()["sessionId"]
        mock_response = _make_mock_openai_response("Hello!", "INTAKE")

        with patch("main._get_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            response = client.post(
                "/api/chat",
                json={"sessionId": session_id, "message": "Hello"},
            )

        data = response.json()
        session = data["session"]
        assert "messages" in session
        # Should have user message + assistant message
        assert len(session["messages"]) >= 2

        roles = [m["role"] for m in session["messages"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_chat_appends_to_existing_session(self):
        session_id = client.post("/api/session").json()["sessionId"]
        mock_response = _make_mock_openai_response("Got it!", "INTAKE")

        with patch("main._get_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            # First message
            client.post("/api/chat", json={"sessionId": session_id, "message": "First"})
            # Second message
            response = client.post(
                "/api/chat", json={"sessionId": session_id, "message": "Second"}
            )

        session = response.json()["session"]
        assert len(session["messages"]) >= 4  # 2 exchanges = 4 messages

    def test_chat_out_of_scope_message(self):
        """Out-of-scope messages should return OUT_OF_SCOPE intent without calling OpenAI."""
        session_id = client.post("/api/session").json()["sessionId"]

        with patch("main._get_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client

            response = client.post(
                "/api/chat",
                json={"sessionId": session_id, "message": "What's the weather forecast today?"},
            )

        data = response.json()
        assert data["intent"] == "OUT_OF_SCOPE"
        # OpenAI should NOT have been called
        mock_client.chat.completions.create.assert_not_called()

    def test_chat_creates_session_if_missing(self):
        """If sessionId does not exist, a new session should be created transparently."""
        mock_response = _make_mock_openai_response("Welcome!", "INTAKE")

        with patch("main._get_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            response = client.post(
                "/api/chat",
                json={"sessionId": "brand-new-id-xyz", "message": "Hi"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert "intent" in data
        assert "session" in data

    def test_chat_session_shape_is_complete(self):
        session_id = client.post("/api/session").json()["sessionId"]
        mock_response = _make_mock_openai_response("Hi there!", "INTAKE")

        with patch("main._get_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            response = client.post(
                "/api/chat",
                json={"sessionId": session_id, "message": "Hello"},
            )

        session = response.json()["session"]
        required_keys = {"id", "messages", "createdAt", "lastActiveAt"}
        for key in required_keys:
            assert key in session, f"Missing key: {key}"


class TestPatientExtraction:
    def test_patient_stored_on_session_when_all_fields_returned(self):
        """When OpenAI returns an INTAKE response with a complete patient object,
        the session should have patient populated and GET /api/session/{id}
        should return that patient data."""
        session_id = client.post("/api/session").json()["sessionId"]

        intake_payload = {
            "reply": "Thank you! I have all your information.",
            "intent": "INTAKE",
            "patient": {
                "firstName": "Jane",
                "lastName": "Doe",
                "dob": "1990-05-15",
                "phone": "+15551234567",
                "email": "jane.doe@example.com",
            },
        }
        mock_response = _make_mock_openai_response_with_payload(intake_payload)

        with patch("main._get_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            chat_resp = client.post(
                "/api/chat",
                json={
                    "sessionId": session_id,
                    "message": "My name is Jane Doe, DOB 1990-05-15, phone +15551234567, email jane.doe@example.com",
                },
            )

        assert chat_resp.status_code == 200
        assert chat_resp.json()["intent"] == "INTAKE"

        # Now verify via GET that patient is persisted on the session
        get_resp = client.get(f"/api/session/{session_id}")
        assert get_resp.status_code == 200
        session = get_resp.json()["session"]

        assert session["patient"] is not None, "patient should be populated on session"
        patient = session["patient"]
        assert patient["firstName"] == "Jane"
        assert patient["lastName"] == "Doe"
        assert patient["dob"] == "1990-05-15"
        assert patient["phone"] == "+15551234567"
        assert patient["email"] == "jane.doe@example.com"

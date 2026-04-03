"""
Smoke tests for the context/session module.

Tests:
  1. POST /api/session returns a sessionId.
  2. GET /api/session/{id} returns that session.
  3. Session has correct shape (id, messages list, createdAt, lastActiveAt).
  4. upsert_session persists messages; round-trip and /messages endpoint agree.
"""

import pytest
from fastapi.testclient import TestClient

# Import the app directly so tests run without a live server.
from main import app, _in_memory_store, upsert_session, get_session, Session, Message

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_store():
    """Ensure a clean in-memory store before every test."""
    _in_memory_store.clear()
    yield
    _in_memory_store.clear()


def test_create_session_returns_session_id():
    response = client.post("/api/session")
    assert response.status_code == 200
    body = response.json()
    assert "sessionId" in body
    assert isinstance(body["sessionId"], str)
    assert len(body["sessionId"]) > 0


def test_get_session_returns_created_session():
    # Create a session first.
    create_resp = client.post("/api/session")
    assert create_resp.status_code == 200
    session_id = create_resp.json()["sessionId"]

    # Retrieve it.
    get_resp = client.get(f"/api/session/{session_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert "session" in body
    session = body["session"]
    assert session["id"] == session_id


def test_session_has_correct_shape():
    create_resp = client.post("/api/session")
    session_id = create_resp.json()["sessionId"]

    get_resp = client.get(f"/api/session/{session_id}")
    session = get_resp.json()["session"]

    # Required fields
    assert "id" in session
    assert isinstance(session["id"], str)

    assert "messages" in session
    assert isinstance(session["messages"], list)

    assert "createdAt" in session
    assert isinstance(session["createdAt"], str)
    assert len(session["createdAt"]) > 0

    assert "lastActiveAt" in session
    assert isinstance(session["lastActiveAt"], str)
    assert len(session["lastActiveAt"]) > 0

    # Optional fields are absent or None when not set
    assert session.get("patient") is None
    assert session.get("appointment") is None


def test_get_nonexistent_session_returns_404():
    resp = client.get("/api/session/does-not-exist-00000")
    assert resp.status_code == 404


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_messages_persist_and_are_returned_by_messages_endpoint():
    """Verify the full round-trip for message persistence.

    Steps:
      1. Create a session via POST /api/session.
      2. Manually call upsert_session with 3 messages.
      3. Call get_session and assert all 3 messages are present with correct
         role and content.
      4. Call GET /api/session/{id}/messages and assert count == 3.
      5. Assert lastActiveAt was updated by the upsert call.
    """
    # ---- 1. Create session ----
    create_resp = client.post("/api/session")
    assert create_resp.status_code == 200
    session_id = create_resp.json()["sessionId"]

    # Capture lastActiveAt before upsert so we can compare later.
    initial_session = get_session(session_id)
    assert initial_session is not None
    initial_last_active = initial_session.lastActiveAt

    # ---- 2. Upsert with 3 messages ----
    messages = [
        Message(role="user",      content="Hello",          timestamp="2026-03-17T10:00:00+00:00"),
        Message(role="assistant", content="Hi there!",      timestamp="2026-03-17T10:00:01+00:00"),
        Message(role="user",      content="Book me a slot", timestamp="2026-03-17T10:00:02+00:00"),
    ]
    updated_session = initial_session.model_copy(update={"messages": messages})
    upsert_session(updated_session)

    # ---- 3. get_session round-trip ----
    fetched = get_session(session_id)
    assert fetched is not None
    assert len(fetched.messages) == 3

    assert fetched.messages[0].role == "user"
    assert fetched.messages[0].content == "Hello"

    assert fetched.messages[1].role == "assistant"
    assert fetched.messages[1].content == "Hi there!"

    assert fetched.messages[2].role == "user"
    assert fetched.messages[2].content == "Book me a slot"

    # ---- 4. GET /api/session/{id}/messages ----
    msgs_resp = client.get(f"/api/session/{session_id}/messages")
    assert msgs_resp.status_code == 200
    body = msgs_resp.json()
    assert body["sessionId"] == session_id
    assert body["count"] == 3
    assert len(body["messages"]) == 3

    # ---- 5. lastActiveAt was updated ----
    assert fetched.lastActiveAt != initial_last_active, (
        "upsert_session must update lastActiveAt on every call"
    )

"""
Smoke tests for the notifications module.

Tests are designed to pass regardless of whether real API keys are present,
because the module gracefully degrades when credentials are missing.
"""

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

PATIENT_OPT_IN = {
    "id": "pat-001",
    "firstName": "Jane",
    "lastName": "Doe",
    "dob": "1990-05-15",
    "phone": "+19195551234",
    "email": "jane.doe@example.com",
    "smsOptIn": True,
}

PATIENT_OPT_OUT = {**PATIENT_OPT_IN, "smsOptIn": False}

APPOINTMENT = {
    "id": "appt-abc-123",
    "patientId": "pat-001",
    "doctorId": "doc-007",
    "slotId": "slot-42",
    "reason": "Annual check-up",
    "confirmedAt": "2026-04-14T10:00:00",
    "emailSent": False,
    "smsSent": False,
}


# ---------------------------------------------------------------------------
# Email tests
# ---------------------------------------------------------------------------

def test_email_returns_200_and_success_shape():
    """POST /api/notify/email must respond 200 with {success: bool}."""
    response = client.post(
        "/api/notify/email",
        json={"appointment": APPOINTMENT, "patient": PATIENT_OPT_IN},
    )
    assert response.status_code == 200
    body = response.json()
    assert "success" in body
    assert isinstance(body["success"], bool)


# ---------------------------------------------------------------------------
# SMS tests
# ---------------------------------------------------------------------------

def test_sms_opt_out_returns_success_false():
    """POST /api/notify/sms with smsOptIn=False must always return {success: false}."""
    response = client.post(
        "/api/notify/sms",
        json={"appointment": APPOINTMENT, "patient": PATIENT_OPT_OUT},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False


def test_sms_opt_in_no_creds_returns_success_false(monkeypatch):
    """POST /api/notify/sms with smsOptIn=True but missing Twilio creds must return {success: false}."""
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_PHONE_NUMBER", raising=False)

    response = client.post(
        "/api/notify/sms",
        json={"appointment": APPOINTMENT, "patient": PATIENT_OPT_IN},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False

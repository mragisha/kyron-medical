import logging
import os

import resend
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from twilio.rest import Client as TwilioClient

# Load .env from project root (two levels up from this file)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Kyron Medical — Notifications Service")


# ---------------------------------------------------------------------------
# Pydantic models — shapes mirror CONTRACTS.md / types.ts
# ---------------------------------------------------------------------------

class Patient(BaseModel):
    id: str
    firstName: str
    lastName: str
    dob: str
    phone: str          # E.164
    email: str
    smsOptIn: bool


class Appointment(BaseModel):
    id: str
    patientId: str
    doctorId: str
    slotId: str
    reason: str
    confirmedAt: str
    emailSent: bool
    smsSent: bool


class NotifyEmailRequest(BaseModel):
    appointment: Appointment
    patient: Patient


class NotifySmsRequest(BaseModel):
    appointment: Appointment
    patient: Patient


class NotifyResponse(BaseModel):
    success: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_email_html(appointment: Appointment, patient: Patient) -> str:
    return f"""
    <h2>Appointment Confirmation</h2>
    <p>Dear {patient.firstName} {patient.lastName},</p>
    <p>Your appointment has been confirmed. Here are the details:</p>
    <ul>
      <li><strong>Doctor ID:</strong> {appointment.doctorId}</li>
      <li><strong>Date / Time:</strong> {appointment.confirmedAt}</li>
      <li><strong>Reason for visit:</strong> {appointment.reason}</li>
      <li><strong>Confirmation number:</strong> {appointment.id}</li>
    </ul>
    <p>Please arrive 10 minutes early. If you need to reschedule, contact our office.</p>
    <p>Thank you,<br/>Kyron Medical</p>
    """


def _build_sms_body(appointment: Appointment) -> str:
    return (
        f"Kyron Medical appt confirmed. "
        f"Dr. ID: {appointment.doctorId} | "
        f"{appointment.confirmedAt} | "
        f"Confirmation: {appointment.id}"
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/notify/email", response_model=NotifyResponse)
def notify_email(req: NotifyEmailRequest) -> NotifyResponse:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        logger.warning("RESEND_API_KEY is not set — skipping email send.")
        return NotifyResponse(success=False)

    try:
        resend.api_key = api_key
        # Use verified sender domain if set, otherwise fall back to Resend's
        # sandbox sender (onboarding@resend.dev) for testing.
        # Set RESEND_FROM_EMAIL=no-reply@kyronmedical.com in .env once the
        # domain DNS records are verified in Resend.
        from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
        from_label = "Kyron Medical" if "kyronmedical" in from_email else "Kyron Medical (Test)"

        # RESEND_SANDBOX_OVERRIDE: when set, all emails are delivered to this address
        # instead of the patient's email. Use this while the sending domain is unverified
        # (Resend sandbox only allows delivery to the account owner's email).
        # Remove this env var once kyronmedical.com is verified in Resend.
        sandbox_override = os.environ.get("RESEND_SANDBOX_OVERRIDE", "")
        to_address = sandbox_override if sandbox_override else req.patient.email
        if sandbox_override:
            logger.info(
                "RESEND_SANDBOX_OVERRIDE active — sending to %s instead of %s",
                sandbox_override, req.patient.email,
            )

        params: resend.Emails.SendParams = {
            "from": f"{from_label} <{from_email}>",
            "to": [to_address],
            "subject": f"Appointment Confirmation — {req.appointment.id} (for {req.patient.firstName} {req.patient.lastName})",
            "html": _build_email_html(req.appointment, req.patient),
        }
        resend.Emails.send(params)
        logger.info("Email sent to %s for appointment %s", req.patient.email, req.appointment.id)
        return NotifyResponse(success=True)
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return NotifyResponse(success=False)


@app.post("/api/notify/sms", response_model=NotifyResponse)
def notify_sms(req: NotifySmsRequest) -> NotifyResponse:
    if not req.patient.smsOptIn:
        logger.info("SMS not sent — patient %s has smsOptIn=False.", req.patient.id)
        return NotifyResponse(success=False)

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_PHONE_NUMBER")

    if not all([account_sid, auth_token, from_number]):
        logger.warning(
            "One or more Twilio env vars are missing (TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER) — skipping SMS send."
        )
        return NotifyResponse(success=False)

    try:
        client = TwilioClient(account_sid, auth_token)
        client.messages.create(
            body=_build_sms_body(req.appointment),
            from_=from_number,
            to=req.patient.phone,
        )
        logger.info("SMS sent to %s for appointment %s", req.patient.phone, req.appointment.id)
        return NotifyResponse(success=True)
    except Exception as exc:
        logger.error("Failed to send SMS: %s", exc)
        return NotifyResponse(success=False)

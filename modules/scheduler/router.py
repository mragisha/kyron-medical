import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

import db
from models import (
    Appointment,
    AppointmentResponse,
    BookRequest,
    DoctorsResponse,
    SlotsResponse,
)

router = APIRouter(prefix="/api/schedule")


# ---------------------------------------------------------------------------
# GET /api/schedule/doctors
# ---------------------------------------------------------------------------

@router.get("/doctors", response_model=DoctorsResponse)
def get_doctors():
    """Return all doctors with their full slot lists."""
    return DoctorsResponse(doctors=list(db.DOCTORS.values()))


# ---------------------------------------------------------------------------
# GET /api/schedule/slots?doctorId=&date=
# ---------------------------------------------------------------------------

@router.get("/slots", response_model=SlotsResponse)
def get_slots(
    doctorId: Optional[str] = Query(default=None),
    date: Optional[str] = Query(default=None),
):
    """
    Return slots optionally filtered by doctorId and/or date (YYYY-MM-DD).
    Returns 404 if doctorId is provided but not found.
    Returns 400 if date format is invalid.
    """
    # Validate doctorId
    if doctorId is not None and doctorId not in db.DOCTORS:
        raise HTTPException(status_code=404, detail=f"Doctor '{doctorId}' not found.")

    # Validate date format
    date_prefix: Optional[str] = None
    if date is not None:
        try:
            datetime.strptime(date, "%Y-%m-%d")
            date_prefix = date  # slots datetimes start with "YYYY-MM-DD"
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Expected YYYY-MM-DD.",
            )

    # Collect candidate slots
    if doctorId is not None:
        candidate_slots = db.DOCTORS[doctorId].slots
    else:
        candidate_slots = list(db.SLOTS.values())

    # Filter by date prefix
    if date_prefix:
        candidate_slots = [s for s in candidate_slots if s.datetime.startswith(date_prefix)]

    return SlotsResponse(slots=candidate_slots)


# ---------------------------------------------------------------------------
# POST /api/schedule/book
# ---------------------------------------------------------------------------

@router.post("/book", response_model=AppointmentResponse, status_code=201)
def book_slot(payload: BookRequest):
    """
    Book a slot.

    - 404 if slotId does not exist.
    - 409 if slot is already booked.
    - Creates an Appointment, marks the slot booked=True.
    """
    slot = db.SLOTS.get(payload.slotId)

    if slot is None:
        raise HTTPException(status_code=404, detail=f"Slot '{payload.slotId}' not found.")

    if slot.booked:
        raise HTTPException(
            status_code=409,
            detail=f"Slot '{payload.slotId}' is already booked.",
        )

    # Mark slot as booked (mutate in-place so DOCTORS dict also reflects the change)
    slot.booked = True

    # Create appointment
    appointment = Appointment(
        id=str(uuid.uuid4()),
        patientId=payload.sessionId,  # sessionId is used as patientId per contract
        doctorId=slot.doctorId,
        slotId=slot.id,
        reason=payload.reason,
        confirmedAt=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        emailSent=False,
        smsSent=False,
    )

    db.APPOINTMENTS[appointment.id] = appointment

    return AppointmentResponse(appointment=appointment)

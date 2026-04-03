from pydantic import BaseModel
from typing import List, Optional


class Slot(BaseModel):
    id: str
    doctorId: str
    datetime: str        # ISO 8601 e.g. "2026-04-14T10:00:00"
    durationMinutes: int
    booked: bool


class Doctor(BaseModel):
    id: str
    name: str
    specialty: str
    bodyParts: List[str]
    slots: List[Slot]


class Appointment(BaseModel):
    id: str
    patientId: str
    doctorId: str
    slotId: str
    reason: str
    confirmedAt: str     # ISO 8601
    emailSent: bool
    smsSent: bool


# Request / Response wrappers

class DoctorsResponse(BaseModel):
    doctors: List[Doctor]


class SlotsResponse(BaseModel):
    slots: List[Slot]


class BookRequest(BaseModel):
    sessionId: str
    slotId: str
    reason: str


class AppointmentResponse(BaseModel):
    appointment: Appointment

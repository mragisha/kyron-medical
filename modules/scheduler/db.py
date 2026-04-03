"""
In-memory data store seeded with 4 doctors and availability slots.

Slots are generated for weekdays only across the next 30-60 days from
today (relative to module startup time). Each doctor gets 3 slots per
weekday: 09:00, 11:00, and 14:00.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List

from models import Appointment, Doctor, Slot

# ---------------------------------------------------------------------------
# Slot generation helpers
# ---------------------------------------------------------------------------

SLOT_TIMES = ["09:00", "11:00", "14:00"]
SLOT_DURATION = 30  # minutes


def _generate_slots(doctor_id: str, start_offset_days: int = 1, end_offset_days: int = 30) -> List[Slot]:
    """Return weekday slots between start_offset_days and end_offset_days from today."""
    slots: List[Slot] = []
    today = date.today()
    start = today + timedelta(days=start_offset_days)
    end = today + timedelta(days=end_offset_days)

    current = start
    while current <= end:
        # weekday() returns 0=Monday … 4=Friday, 5=Saturday, 6=Sunday
        if current.weekday() < 5:
            for time_str in SLOT_TIMES:
                hour, minute = map(int, time_str.split(":"))
                dt = datetime(current.year, current.month, current.day, hour, minute, 0)
                slots.append(
                    Slot(
                        id=str(uuid.uuid4()),
                        doctorId=doctor_id,
                        datetime=dt.strftime("%Y-%m-%dT%H:%M:%S"),
                        durationMinutes=SLOT_DURATION,
                        booked=False,
                    )
                )
        current += timedelta(days=1)

    return slots


# ---------------------------------------------------------------------------
# Doctor seed data
# ---------------------------------------------------------------------------

def _build_doctors() -> Dict[str, Doctor]:
    raw = [
        {
            "id": "doc-sarah-chen",
            "name": "Dr. Sarah Chen",
            "specialty": "cardiology",
            "bodyParts": ["heart", "chest", "cardiovascular", "blood pressure", "palpitations"],
        },
        {
            "id": "doc-marcus-webb",
            "name": "Dr. Marcus Webb",
            "specialty": "orthopedics",
            "bodyParts": ["bone", "joint", "spine", "knee", "shoulder", "hip", "fracture"],
        },
        {
            "id": "doc-priya-nair",
            "name": "Dr. Priya Nair",
            "specialty": "neurology",
            "bodyParts": ["brain", "headache", "migraine", "nervous system", "seizure", "dizziness"],
        },
        {
            "id": "doc-james-okafor",
            "name": "Dr. James Okafor",
            "specialty": "dermatology",
            "bodyParts": ["skin", "rash", "mole", "acne", "eczema", "psoriasis"],
        },
    ]

    doctors: Dict[str, Doctor] = {}
    for d in raw:
        slots = _generate_slots(d["id"])
        doctor = Doctor(
            id=d["id"],
            name=d["name"],
            specialty=d["specialty"],
            bodyParts=d["bodyParts"],
            slots=slots,
        )
        doctors[d["id"]] = doctor

    return doctors


# ---------------------------------------------------------------------------
# Module-level in-memory stores (singleton for the process lifetime)
# ---------------------------------------------------------------------------

# Keyed by doctor_id
DOCTORS: Dict[str, Doctor] = _build_doctors()

# Flat slot lookup: slot_id -> Slot  (mutable reference shared with doctor objects)
SLOTS: Dict[str, Slot] = {}
for _doc in DOCTORS.values():
    for _slot in _doc.slots:
        SLOTS[_slot.id] = _slot

# Appointments: appointment_id -> Appointment
APPOINTMENTS: Dict[str, Appointment] = {}

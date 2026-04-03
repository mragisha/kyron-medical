"""
pytest test suite for the Kyron Medical Scheduler service.

Run with:
    cd /modules/scheduler && pytest test_scheduler.py -v
"""

import sys
import os

# Ensure the scheduler package directory is on the path so imports resolve.
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_available_slot():
    """Return the first unbooked slot id and its doctorId from the DB."""
    import db
    for slot in db.SLOTS.values():
        if not slot.booked:
            return slot.id, slot.doctorId
    raise RuntimeError("No available slots found in seed data.")


def _first_doctor_id():
    import db
    return next(iter(db.DOCTORS))


# ---------------------------------------------------------------------------
# GET /api/schedule/doctors
# ---------------------------------------------------------------------------

class TestGetDoctors:
    def test_returns_200(self):
        resp = client.get("/api/schedule/doctors")
        assert resp.status_code == 200

    def test_response_has_doctors_key(self):
        resp = client.get("/api/schedule/doctors")
        body = resp.json()
        assert "doctors" in body

    def test_returns_four_doctors(self):
        resp = client.get("/api/schedule/doctors")
        doctors = resp.json()["doctors"]
        assert len(doctors) == 4

    def test_doctor_shape(self):
        resp = client.get("/api/schedule/doctors")
        doctor = resp.json()["doctors"][0]
        for field in ("id", "name", "specialty", "bodyParts", "slots"):
            assert field in doctor, f"Missing field: {field}"

    def test_each_doctor_has_slots(self):
        resp = client.get("/api/schedule/doctors")
        for doctor in resp.json()["doctors"]:
            assert len(doctor["slots"]) > 0, f"{doctor['name']} has no slots"

    def test_slot_shape(self):
        resp = client.get("/api/schedule/doctors")
        slot = resp.json()["doctors"][0]["slots"][0]
        for field in ("id", "doctorId", "datetime", "durationMinutes", "booked"):
            assert field in slot, f"Missing slot field: {field}"

    def test_slots_are_weekdays_only(self):
        from datetime import datetime
        resp = client.get("/api/schedule/doctors")
        for doctor in resp.json()["doctors"]:
            for slot in doctor["slots"]:
                dt = datetime.fromisoformat(slot["datetime"])
                assert dt.weekday() < 5, f"Weekend slot found: {slot['datetime']}"

    def test_known_doctors_present(self):
        resp = client.get("/api/schedule/doctors")
        names = {d["name"] for d in resp.json()["doctors"]}
        assert "Dr. Sarah Chen" in names
        assert "Dr. Marcus Webb" in names
        assert "Dr. Priya Nair" in names
        assert "Dr. James Okafor" in names


# ---------------------------------------------------------------------------
# GET /api/schedule/slots
# ---------------------------------------------------------------------------

class TestGetSlots:
    def test_returns_200_no_filters(self):
        resp = client.get("/api/schedule/slots")
        assert resp.status_code == 200

    def test_response_has_slots_key(self):
        resp = client.get("/api/schedule/slots")
        assert "slots" in resp.json()

    def test_filter_by_valid_doctor_id(self):
        doctor_id = _first_doctor_id()
        resp = client.get(f"/api/schedule/slots?doctorId={doctor_id}")
        assert resp.status_code == 200
        slots = resp.json()["slots"]
        assert len(slots) > 0
        for slot in slots:
            assert slot["doctorId"] == doctor_id

    def test_filter_by_invalid_doctor_id_returns_404(self):
        resp = client.get("/api/schedule/slots?doctorId=nonexistent-doctor")
        assert resp.status_code == 404

    def test_filter_by_valid_date(self):
        # Grab a date that appears in the seed data
        import db
        some_slot = next(iter(db.SLOTS.values()))
        date_str = some_slot.datetime[:10]  # "YYYY-MM-DD"
        resp = client.get(f"/api/schedule/slots?date={date_str}")
        assert resp.status_code == 200
        for slot in resp.json()["slots"]:
            assert slot["datetime"].startswith(date_str)

    def test_filter_by_invalid_date_returns_400(self):
        resp = client.get("/api/schedule/slots?date=not-a-date")
        assert resp.status_code == 400

    def test_filter_by_doctor_and_date(self):
        import db
        doctor_id = _first_doctor_id()
        doctor = db.DOCTORS[doctor_id]
        date_str = doctor.slots[0].datetime[:10]
        resp = client.get(f"/api/schedule/slots?doctorId={doctor_id}&date={date_str}")
        assert resp.status_code == 200
        for slot in resp.json()["slots"]:
            assert slot["doctorId"] == doctor_id
            assert slot["datetime"].startswith(date_str)

    def test_unknown_date_returns_empty_list(self):
        resp = client.get("/api/schedule/slots?date=1900-01-01")
        assert resp.status_code == 200
        assert resp.json()["slots"] == []


# ---------------------------------------------------------------------------
# POST /api/schedule/book
# ---------------------------------------------------------------------------

class TestBookSlot:
    def test_successful_booking_returns_201(self):
        slot_id, _ = _first_available_slot()
        payload = {"sessionId": "session-abc", "slotId": slot_id, "reason": "Chest pain follow-up"}
        resp = client.post("/api/schedule/book", json=payload)
        assert resp.status_code == 201

    def test_successful_booking_returns_appointment(self):
        slot_id, doctor_id = _first_available_slot()
        payload = {"sessionId": "session-xyz", "slotId": slot_id, "reason": "Annual checkup"}
        resp = client.post("/api/schedule/book", json=payload)
        body = resp.json()
        assert "appointment" in body
        appt = body["appointment"]
        for field in ("id", "patientId", "doctorId", "slotId", "reason", "confirmedAt", "emailSent", "smsSent"):
            assert field in appt, f"Missing appointment field: {field}"

    def test_booking_sets_correct_fields(self):
        slot_id, doctor_id = _first_available_slot()
        session_id = "session-patient-001"
        reason = "Knee pain evaluation"
        payload = {"sessionId": session_id, "slotId": slot_id, "reason": reason}
        resp = client.post("/api/schedule/book", json=payload)
        appt = resp.json()["appointment"]
        assert appt["slotId"] == slot_id
        assert appt["doctorId"] == doctor_id
        assert appt["patientId"] == session_id
        assert appt["reason"] == reason
        assert appt["emailSent"] is False
        assert appt["smsSent"] is False

    def test_booking_marks_slot_as_booked(self):
        slot_id, _ = _first_available_slot()
        payload = {"sessionId": "session-mark", "slotId": slot_id, "reason": "Test"}
        client.post("/api/schedule/book", json=payload)

        import db
        assert db.SLOTS[slot_id].booked is True

    def test_double_booking_returns_409(self):
        slot_id, _ = _first_available_slot()
        payload = {"sessionId": "session-first", "slotId": slot_id, "reason": "First booking"}
        client.post("/api/schedule/book", json=payload)

        payload2 = {"sessionId": "session-second", "slotId": slot_id, "reason": "Second booking"}
        resp2 = client.post("/api/schedule/book", json=payload2)
        assert resp2.status_code == 409

    def test_booking_nonexistent_slot_returns_404(self):
        payload = {"sessionId": "session-ghost", "slotId": "slot-does-not-exist", "reason": "Test"}
        resp = client.post("/api/schedule/book", json=payload)
        assert resp.status_code == 404

    def test_booking_missing_fields_returns_422(self):
        # Missing slotId entirely
        resp = client.post("/api/schedule/book", json={"sessionId": "s1", "reason": "x"})
        assert resp.status_code == 422

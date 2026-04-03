"""
main.py — Kyron Medical Safety Module HTTP wrapper

Run:  uvicorn main:app --host 0.0.0.0 --port 8004
"""

from fastapi import FastAPI
from pydantic import BaseModel

from guardrails import is_medical_advice, sanitize_response, SAFE_REDIRECT

app = FastAPI(title="Kyron Medical Safety API", version="1.0.0")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SafetyCheckRequest(BaseModel):
    text: str
    role: str = "assistant"   # expected: "assistant" | "user"


class SafetyCheckResponse(BaseModel):
    safe: bool
    sanitized: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/safety/check", response_model=SafetyCheckResponse)
def check_safety(body: SafetyCheckRequest) -> SafetyCheckResponse:
    """
    Evaluate whether the supplied text is safe to surface to the patient.

    - safe=True  → text passed all guardrails; sanitized == original text
    - safe=False → text triggered a medical-advice guardrail;
                   sanitized contains the safe redirect message
    """
    flagged = is_medical_advice(body.text)
    return SafetyCheckResponse(
        safe=not flagged,
        sanitized=sanitize_response(body.text),
    )

"""
Live integration test — actually calls Resend with your real RESEND_API_KEY.
Run with:
    cd modules/notifications
    pytest test_email_live.py -v -s

Set TEST_RECIPIENT in your .env or export it before running:
    export TEST_RECIPIENT=you@youremail.com
"""

import os
import sys

import pytest
import resend
from dotenv import load_dotenv

# Load project-root .env
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
load_dotenv(os.path.join(_ROOT, ".env"))

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
# Recipient to test with — set TEST_RECIPIENT in .env or as env var
TEST_RECIPIENT = os.getenv("TEST_RECIPIENT", "")


# ---------------------------------------------------------------------------
# Diagnostic: print key shape so we can spot obvious problems
# ---------------------------------------------------------------------------

def test_resend_key_is_present():
    """RESEND_API_KEY must be set and look like a Resend key (starts with 're_')."""
    assert RESEND_API_KEY, "RESEND_API_KEY is not set in .env"
    assert RESEND_API_KEY.startswith("re_"), (
        f"RESEND_API_KEY does not start with 're_' — got prefix: {RESEND_API_KEY[:6]}..."
        " This may be the wrong key."
    )
    print(f"\n  Key prefix: {RESEND_API_KEY[:8]}...  length={len(RESEND_API_KEY)}")


def test_resend_send_real_email():
    """
    Actually calls Resend. Requires TEST_RECIPIENT to be set.
    Run:  export TEST_RECIPIENT=you@example.com
    """
    if not RESEND_API_KEY:
        pytest.skip("RESEND_API_KEY not set")
    if not TEST_RECIPIENT:
        pytest.skip(
            "TEST_RECIPIENT not set — export TEST_RECIPIENT=you@example.com and re-run"
        )

    resend.api_key = RESEND_API_KEY

    # Use RESEND_FROM_EMAIL if set (verified domain), else Resend sandbox sender
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    print(f"\n  Sending from: {from_email}")
    print(f"  Sending to:   {TEST_RECIPIENT}")

    params: resend.Emails.SendParams = {
        "from": f"Kyron Medical <{from_email}>",
        "to": [TEST_RECIPIENT],
        "subject": "Kyron Medical — Live Send Test",
        "html": """
            <h2>Test Email</h2>
            <p>This is a live test from the Kyron Medical notifications module.</p>
            <p>If you received this, Resend is configured correctly.</p>
        """,
    }

    try:
        result = resend.Emails.send(params)
        print(f"\n  Resend response: {result}")
        # result is a dict with 'id' on success
        assert result.get("id"), f"Expected an email ID in response, got: {result}"
        print(f"  ✅ Email sent successfully! Resend ID: {result['id']}")
    except Exception as exc:
        # Print the full exception so we can see exactly what Resend said
        print(f"\n  ❌ Resend error: {type(exc).__name__}: {exc}")
        raise


def test_resend_domains_list():
    """
    Calls the Resend Domains API to show which domains are verified.
    Helpful for confirming kyronmedical.com shows 'verified' status.
    """
    if not RESEND_API_KEY:
        pytest.skip("RESEND_API_KEY not set")

    import httpx

    resp = httpx.get(
        "https://api.resend.com/domains",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        timeout=10,
    )
    print(f"\n  Domains API status: {resp.status_code}")
    try:
        body = resp.json()
        domains = body.get("data", [])
        if not domains:
            print("  No domains found in this Resend account.")
        for d in domains:
            print(f"  Domain: {d.get('name')} | status: {d.get('status')} | region: {d.get('region')}")
    except Exception:
        print(f"  Raw response: {resp.text}")

    assert resp.status_code == 200, f"Domains API returned {resp.status_code}: {resp.text}"

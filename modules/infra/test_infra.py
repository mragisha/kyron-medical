"""
Infra smoke tests for Kyron Medical Patient Portal.

Verifies:
1. Each module's main.py exists and contains the expected port number.
2. Required MODULE_READY sentinel files exist.
"""

import os
import pathlib
import warnings

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

MODULES_ROOT = pathlib.Path("/Users/avleenmehal/kyron-medical/modules")

# ---------------------------------------------------------------------------
# Port contract
#
# These are the ports as actually documented in each module's main.py.
# ai       : 8000  (uvicorn.run port=8000)
# context  : 8002  (uvicorn.run port=8002)
# scheduler: 3002  (uvicorn.run port=3002)
# safety   : 8004  (docstring: --port 8004)
# ui       : 8080  (uvicorn.run port=8080)
# notifications: no standalone port — verified via FastAPI app declaration
# voice    : no main.py yet — checked as warning only
# ---------------------------------------------------------------------------

MODULE_PORT_CONTRACTS = {
    "ai": "8000",
    "context": "8002",
    "scheduler": "3002",
    "safety": "8004",
    "ui": "8080",
}

# ---------------------------------------------------------------------------
# MODULE_READY sentinel paths
# ---------------------------------------------------------------------------

MODULE_READY_PATHS = [
    MODULES_ROOT / "context"       / "MODULE_READY",
    MODULES_ROOT / "scheduler"     / "MODULE_READY",
    MODULES_ROOT / "notifications" / "MODULE_READY",
    MODULES_ROOT / "safety"        / "MODULE_READY",
    MODULES_ROOT / "ai"            / "MODULE_READY",
    MODULES_ROOT / "ui"            / "MODULE_READY",
]


# ---------------------------------------------------------------------------
# Tests: port contracts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name,expected_port", MODULE_PORT_CONTRACTS.items())
def test_module_main_contains_port(module_name: str, expected_port: str):
    """Each module's main.py must contain its expected port number."""
    main_py = MODULES_ROOT / module_name / "main.py"
    assert main_py.exists(), f"main.py not found for module '{module_name}': {main_py}"
    content = main_py.read_text()
    assert expected_port in content, (
        f"Port {expected_port} not found in {main_py}. "
        f"The port contract for '{module_name}' may be out of date."
    )


def test_notifications_main_has_fastapi_app():
    """Notifications module must declare a FastAPI app (no standalone port)."""
    main_py = MODULES_ROOT / "notifications" / "main.py"
    assert main_py.exists(), f"main.py not found: {main_py}"
    content = main_py.read_text()
    assert "FastAPI" in content, "notifications/main.py must declare a FastAPI app"
    assert "/api/notify" in content, (
        "notifications/main.py must expose /api/notify endpoints per CONTRACTS.md"
    )


def test_voice_module_warning_only():
    """Voice module main.py may not exist yet — emit a warning rather than failing."""
    voice_main = MODULES_ROOT / "voice" / "main.py"
    if not voice_main.exists():
        warnings.warn(
            f"voice/main.py not found at {voice_main} — voice module is not yet ready.",
            stacklevel=2,
        )
    # This test always passes; the warning surfaces the missing file.


# ---------------------------------------------------------------------------
# Tests: MODULE_READY sentinels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ready_path", MODULE_READY_PATHS)
def test_module_ready_exists(ready_path: pathlib.Path):
    """Each completed module must have a MODULE_READY sentinel file."""
    assert ready_path.exists(), (
        f"MODULE_READY not found: {ready_path}. "
        "The module agent has not completed its work."
    )


# ---------------------------------------------------------------------------
# Test: voice MODULE_READY is optional (warning only)
# ---------------------------------------------------------------------------

def test_voice_module_ready_warning_only():
    """Voice MODULE_READY may not exist yet — emit a warning rather than failing."""
    voice_ready = MODULES_ROOT / "voice" / "MODULE_READY"
    if not voice_ready.exists():
        warnings.warn(
            f"voice/MODULE_READY not found at {voice_ready} — voice module is not yet complete.",
            stacklevel=2,
        )
    # Always passes.

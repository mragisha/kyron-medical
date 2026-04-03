"""
Kyron Medical Patient Portal — Master FastAPI Application

Mounts all module routers into a single unified app.

Route prefixes per CONTRACTS.md (all already embedded in each module's routes):
  ai core        → /api/session, /api/chat
  scheduler      → /api/schedule/*
  notifications  → /api/notify/*
  safety         → /api/safety/*
  voice          → /api/voice/*
  ui             → / (index) + /static/*

IMPORTANT: use include_router (not mount) for API modules so that the full
route paths (/api/session etc.) are preserved. mount() strips the prefix
before forwarding, which causes 404s when routes are already prefixed.

Run:
  uvicorn app.main:app --host 0.0.0.0 --port 3001
  — or —
  python app/main.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import warnings
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent          # /app
_MODULES_ROOT = _HERE.parent / "modules"         # /modules


def _load_module(logical_name: str, file_path: Path):
    """
    Load a Python file as a module using importlib, registering it in
    sys.modules under *logical_name* to avoid collisions between the
    many files all named "main.py".

    Returns the loaded module object, or None if the file does not exist.
    """
    if not file_path.exists():
        warnings.warn(
            f"Module file not found, skipping: {file_path}",
            stacklevel=2,
        )
        return None

    # If already loaded (e.g. during hot-reload), return cached version.
    if logical_name in sys.modules:
        return sys.modules[logical_name]

    spec = importlib.util.spec_from_file_location(logical_name, str(file_path))
    if spec is None or spec.loader is None:
        warnings.warn(f"Could not create module spec for {file_path}", stacklevel=2)
        return None

    mod = importlib.util.module_from_spec(spec)
    sys.modules[logical_name] = mod

    # Add the module's own directory to sys.path so that relative imports
    # (e.g. `from router import router` inside scheduler/main.py) work.
    module_dir = str(file_path.parent)
    _path_inserted = module_dir not in sys.path
    if _path_inserted:
        sys.path.insert(0, module_dir)

    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"Failed to load {file_path}: {exc}", stacklevel=2)
        del sys.modules[logical_name]
        return None
    finally:
        # Remove the dir again to avoid polluting sys.path with every module's folder.
        if _path_inserted and module_dir in sys.path:
            sys.path.remove(module_dir)

    return mod


# ---------------------------------------------------------------------------
# Create master app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Kyron Medical Patient Portal",
    description=(
        "Unified gateway for the Kyron Medical patient portal. "
        "Mounts AI core, scheduler, notifications, safety, voice, and UI modules."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok", "service": "kyron-medical-gateway"}


# ---------------------------------------------------------------------------
# AI Core  →  /api/session, /api/chat
# Use include_router so the routes' full paths (/api/session etc.) are kept.
# mount("/api", sub_app) would strip the /api prefix and cause 404s.
# ---------------------------------------------------------------------------

_ai_mod = _load_module("kyron_ai_main", _MODULES_ROOT / "ai" / "main.py")
if _ai_mod is not None and hasattr(_ai_mod, "app"):
    app.include_router(_ai_mod.app.router)


# ---------------------------------------------------------------------------
# Scheduler  →  /api/schedule/*
# ---------------------------------------------------------------------------

_scheduler_mod = _load_module("kyron_scheduler_main", _MODULES_ROOT / "scheduler" / "main.py")
if _scheduler_mod is not None and hasattr(_scheduler_mod, "app"):
    app.include_router(_scheduler_mod.app.router)


# ---------------------------------------------------------------------------
# Notifications  →  /api/notify/*  (internal; not browser-facing)
# ---------------------------------------------------------------------------

_notifications_mod = _load_module(
    "kyron_notifications_main", _MODULES_ROOT / "notifications" / "main.py"
)
if _notifications_mod is not None and hasattr(_notifications_mod, "app"):
    app.include_router(_notifications_mod.app.router)


# ---------------------------------------------------------------------------
# Safety  →  /api/safety/*  (internal)
# ---------------------------------------------------------------------------

_safety_mod = _load_module("kyron_safety_main", _MODULES_ROOT / "safety" / "main.py")
if _safety_mod is not None and hasattr(_safety_mod, "app"):
    app.include_router(_safety_mod.app.router)


# ---------------------------------------------------------------------------
# Voice  →  /api/voice/*
# ---------------------------------------------------------------------------

_voice_mod = _load_module("kyron_voice_main", _MODULES_ROOT / "voice" / "main.py")
if _voice_mod is not None and hasattr(_voice_mod, "app"):
    app.include_router(_voice_mod.app.router)


# ---------------------------------------------------------------------------
# UI  →  / (index.html) + /static/*
# Mounted last so API routes above take precedence.
# ---------------------------------------------------------------------------

_ui_mod = _load_module("kyron_ui_main", _MODULES_ROOT / "ui" / "main.py")
if _ui_mod is not None and hasattr(_ui_mod, "app"):
    # Include the UI router (serves index.html at /)
    app.include_router(_ui_mod.app.router)

# Mount the static directory directly from the known path.
_static_dir = _MODULES_ROOT / "ui" / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3001"))
    uvicorn.run(app, host="0.0.0.0", port=port)

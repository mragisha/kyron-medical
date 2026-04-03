"""Smoke tests for the Kyron Medical UI module."""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_get_root_returns_200():
    """GET / must return HTTP 200."""
    response = client.get("/")
    assert response.status_code == 200


def test_get_root_returns_html():
    """GET / must return HTML content."""
    response = client.get("/")
    content_type = response.headers.get("content-type", "")
    assert "text/html" in content_type
    # Verify the page contains expected portal content
    assert b"Kyron Medical" in response.content


def test_static_files_endpoint_exists():
    """The /static mount must exist and serve files from the static directory."""
    # index.html is also served at /static/index.html via the StaticFiles mount
    response = client.get("/static/index.html")
    assert response.status_code == 200


def test_root_html_has_chat_elements():
    """The served HTML must include the core chat UI elements."""
    response = client.get("/")
    body = response.text
    assert "messages" in body        # chat messages container
    assert "user-input" in body      # text input
    assert "send-btn" in body        # send button
    assert "/api/session" in body    # calls session endpoint
    assert "/api/chat" in body       # calls chat endpoint

"""Tests for provider API endpoints (Steps 10.c–10.d)."""
import pytest


def test_list_providers_endpoint(client):
    """GET /api/v1/providers returns a response."""
    resp = client.get('/api/v1/providers')
    assert resp.status_code in (200, 502)

"""Tests for CarePlan API endpoints (Steps 7.d–7.e)."""
import pytest


def test_list_careplans_endpoint(client):
    """GET /api/v1/CarePlan returns a response."""
    resp = client.get('/api/v1/CarePlan')
    assert resp.status_code in (200, 502)


def test_get_careplan_endpoint(client):
    """GET /api/v1/CarePlan/<guid> returns a response."""
    resp = client.get('/api/v1/CarePlan/test-cp-guid')
    assert resp.status_code in (200, 404, 502)

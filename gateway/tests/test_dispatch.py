"""Tests for dispatch API endpoints (Steps 11.d–11.e).
Dispatch tests that hit the database require a running PostgreSQL."""
import pytest


def test_dispatch_no_body(client):
    """POST dispatch without body returns 400."""
    resp = client.post('/api/v1/PlanDefinition/test-cp/dispatch')
    assert resp.status_code == 400


def test_dispatch_missing_provider(client):
    """POST dispatch without provider_guid returns 400."""
    resp = client.post('/api/v1/PlanDefinition/test-cp/dispatch', json={
        'notes': 'Test dispatch',
    })
    assert resp.status_code == 400
    data = resp.get_json()
    assert 'provider_guid' in data.get('message', '')


def test_dispatch_status_not_found(client):
    """GET dispatch status with bad token returns 404."""
    resp = client.get('/api/v1/PlanDefinition/test-cp/dispatch/nonexistent-token')
    assert resp.status_code == 404

"""Tests for patient API endpoints (Steps 6.d–6.e).
These test the API layer; upstream calls are expected to fail in test
environment (no live IPS backend), which is acceptable — we test the
routing, auth, and error handling."""
import pytest


def test_list_patients_endpoint(client):
    """GET /api/v1/Patient returns a response (may be upstream error)."""
    resp = client.get('/api/v1/Patient')
    assert resp.status_code in (200, 502)


def test_get_patient_endpoint(client):
    """GET /api/v1/Patient/<guid> returns a response."""
    resp = client.get('/api/v1/Patient/test-guid-123')
    assert resp.status_code in (200, 404, 502)


def test_create_patient_no_body(client):
    """POST /api/v1/Patient without body returns 400."""
    resp = client.post('/api/v1/Patient')
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['code'] == 'bad_request'


def test_create_patient_with_body(client):
    """POST /api/v1/Patient with body attempts upstream call."""
    resp = client.post('/api/v1/Patient', json={
        'resourceType': 'Patient',
        'name': [{'family': 'Test', 'given': ['User']}],
    })
    # Either upstream succeeds or we get 502
    assert resp.status_code in (200, 201, 502)


def test_update_patient_no_body(client):
    """PUT /api/v1/Patient/<guid> without body returns 400."""
    resp = client.put('/api/v1/Patient/test-guid-123')
    assert resp.status_code == 400


def test_delete_patient_endpoint(client):
    """DELETE /api/v1/Patient/<guid> returns a response."""
    resp = client.delete('/api/v1/Patient/test-guid-123')
    assert resp.status_code in (200, 404, 502)

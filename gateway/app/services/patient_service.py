import requests
from flask import current_app
from app.services.auth_service import get_upstream_token


def _headers():
    """Build headers for upstream IPS requests."""
    headers = {'Content-Type': 'application/fhir+json', 'Accept': 'application/fhir+json'}
    token = get_upstream_token()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _ips_url(path=''):
    base = current_app.config['IPS_BASE_URL'].rstrip('/')
    return f"{base}/api/v1/Patient{path}"


def list_patients(params=None):
    """List/search patients from IPS backend."""
    try:
        resp = requests.get(_ips_url(), headers=_headers(), params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def get_patient(guid):
    """Get a single patient by GUID from IPS backend."""
    try:
        resp = requests.get(_ips_url(f'/{guid}'), headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return {'code': 'not_found', 'message': f'Patient {guid} not found'}, 404
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def create_patient(payload):
    """Create a patient on IPS backend."""
    try:
        resp = requests.post(_ips_url(), headers=_headers(), json=payload, timeout=15)
        if resp.status_code in (400, 422):
            return resp.json(), resp.status_code
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def update_patient(guid, payload):
    """Update a patient on IPS backend."""
    try:
        resp = requests.put(_ips_url(f'/{guid}'), headers=_headers(), json=payload, timeout=15)
        if resp.status_code in (400, 404, 422):
            return resp.json(), resp.status_code
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def delete_patient(guid):
    """Delete a patient on IPS backend."""
    try:
        resp = requests.delete(_ips_url(f'/{guid}'), headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return {'code': 'not_found', 'message': f'Patient {guid} not found'}, 404
        resp.raise_for_status()
        if resp.status_code == 204:
            return {'message': 'Patient deleted'}, 200
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502

import requests
from flask import current_app


def _headers():
    """Build headers for upstream IPS requests using service API key."""
    headers = {'Content-Type': 'application/fhir+json', 'Accept': 'application/fhir+json'}
    api_key = current_app.config.get('IPS_API_KEY')
    if api_key:
        headers['Authorization'] = f'ApiKey {api_key}'
    return headers


def _ips_url(path=''):
    base = current_app.config['IPS_BASE_URL'].rstrip('/')
    return f"{base}/fhir/Patient{path}"


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


def get_patient_clinic_guids(patient_guid):
    """Return the list of clinic GUIDs a patient is assigned to via
    ips.pdhc PatientClinicAssignment.

    Used by ServiceRequest create to enforce patient-org need-to-know
    (PDL Ch 4 §§ 1-2; ticket #225).

    Returns:
        (clinic_guids: list[str], status: int)
        On success: ([...], 200) — may be empty list when patient has
        no assignments.
        On not-found: ([], 404).
        On upstream error: ([], 502 or 5xx as returned).
    """
    base = current_app.config['IPS_BASE_URL'].rstrip('/')
    url = f"{base}/api/v1/patients/{patient_guid}/clinics"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return [], 404
        resp.raise_for_status()
        clinics = resp.json() or []
        return [c.get('guid') for c in clinics if c.get('guid')], 200
    except requests.RequestException as e:
        current_app.logger.warning(
            "ips.pdhc patient-clinics lookup failed for %s: %s",
            patient_guid, e,
        )
        return [], 502

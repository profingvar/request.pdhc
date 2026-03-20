import requests
from flask import current_app
from app.services.auth_service import get_upstream_token


def _headers():
    """Build headers for upstream Plan requests."""
    headers = {'Content-Type': 'application/fhir+json', 'Accept': 'application/fhir+json'}
    token = get_upstream_token()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _plan_url(path=''):
    base = current_app.config['PLAN_BASE_URL'].rstrip('/')
    return f"{base}/api/v1/CarePlan{path}"


def list_careplans(params=None):
    """List/search careplans from Plan backend."""
    default_params = {'_count': '100'}
    if params:
        default_params.update(params)
    try:
        resp = requests.get(_plan_url(), headers=_headers(), params=default_params, timeout=15)
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def get_careplan(guid):
    """Get a single careplan by GUID from Plan backend."""
    try:
        resp = requests.get(_plan_url(f'/{guid}'), headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return {'code': 'not_found', 'message': f'CarePlan {guid} not found'}, 404
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502

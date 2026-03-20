import requests
from flask import current_app
from app.services.auth_service import get_upstream_token


def _headers():
    headers = {'Accept': 'application/json'}
    token = get_upstream_token()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def list_providers(params=None):
    """List providers from upstream Plan backend."""
    base = current_app.config['PLAN_BASE_URL'].rstrip('/')
    try:
        resp = requests.get(f"{base}/api/v1/providers", headers=_headers(), params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502

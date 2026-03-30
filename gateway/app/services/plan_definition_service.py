import requests
from flask import current_app


def _headers():
    """Build headers for upstream Plan requests."""
    return {'Accept': 'application/json'}


def _plan_url(path=''):
    base = current_app.config['PLAN_BASE_URL'].rstrip('/')
    return f"{base}/api/v1/plandefinitions{path}"


def list_plan_definitions(params=None):
    """List PlanDefinitions from Plan backend."""
    default_params = {'per_page': '200'}
    if params:
        default_params.update(params)
    try:
        resp = requests.get(_plan_url(), headers=_headers(), params=default_params, timeout=15)
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def get_plan_definition(guid):
    """Get a single PlanDefinition by GUID from Plan backend."""
    try:
        resp = requests.get(_plan_url(f'/{guid}'), headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return {'code': 'not_found', 'message': f'PlanDefinition {guid} not found'}, 404
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def _plan_base(path):
    base = current_app.config['PLAN_BASE_URL'].rstrip('/')
    return f"{base}/api/v1{path}"


def list_concepts():
    """Fetch all concepts from Plan backend."""
    try:
        resp = requests.get(_plan_base('/concepts'), headers=_headers(),
                            params={'per_page': '500'}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get('items', data) if isinstance(data, dict) else data
    except requests.RequestException:
        return []


def list_units():
    """Fetch all units from Plan backend."""
    try:
        resp = requests.get(_plan_base('/units'), headers=_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return []


def list_valuesets():
    """Fetch all valuesets (with values) from Plan backend."""
    try:
        resp = requests.get(_plan_base('/valuesets'), headers=_headers(),
                            params={'per_page': '200'}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data.get('items', data) if isinstance(data, dict) else data
        # Fetch values for each valueset
        for vs in items:
            guid = vs.get('guid')
            if guid:
                try:
                    vresp = requests.get(_plan_base(f'/valuesets/{guid}/values'),
                                         headers=_headers(), timeout=10)
                    if vresp.status_code == 200:
                        vs['values'] = vresp.json()
                except requests.RequestException:
                    vs['values'] = []
        return items
    except requests.RequestException:
        return []


def list_plandef_types():
    """Fetch all PlanDefinition types from Plan backend."""
    try:
        resp = requests.get(_plan_base('/plandef-types'), headers=_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return []

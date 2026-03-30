import requests
from flask import current_app


def _headers():
    """Build headers for upstream Contract requests."""
    return {'Accept': 'application/fhir+json'}


def _contract_url(path=''):
    base = current_app.config['CONTRACT_BASE_URL'].rstrip('/')
    return f"{base}/fhir/Contract{path}"


def list_contracts():
    """List all contracts from contract.pdhc."""
    try:
        resp = requests.get(_contract_url(), headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        entries = data.get('entry', [])
        return [e.get('resource', e) for e in entries], 200
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def get_contract(guid):
    """Get a single contract by GUID."""
    try:
        resp = requests.get(_contract_url(f'/{guid}'), headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return {'code': 'not_found', 'message': f'Contract {guid} not found'}, 404
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def find_matching_contracts(plan_definition_guid=None):
    """Find contracts that could match a ServiceRequest.

    Currently fetches all active contracts. Future: filter by PlanDefinition
    scope, service type, or provider capabilities.
    """
    result, status = list_contracts()
    if status != 200:
        return result, status

    # Filter to active contracts only
    active = [c for c in result if c.get('status') == 'executed' or c.get('status') == 'active']
    return active, 200

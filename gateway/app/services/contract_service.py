import requests
from flask import current_app

from app.services.session_headers import outbound_session_headers


def _headers():
    """Build headers for upstream Contract requests."""
    return {'Accept': 'application/fhir+json', **outbound_session_headers()}


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


ACTIVE_CONTRACT_STATUSES = ('executed', 'active', 'offered', 'executable', 'renewed')


def find_matching_contracts(plan_definition_guid=None, plan_definition_fhir_id=None):
    """Find contracts whose topic references the given PlanDefinition.

    Accepts the database guid and/or the FHIR id and matches against either,
    since contracts may reference whichever was assigned at contract-creation time.
    """
    result, status = list_contracts()
    if status != 200:
        return result, status

    active = [c for c in result if c.get('status') in ACTIVE_CONTRACT_STATUSES]

    if not plan_definition_guid and not plan_definition_fhir_id:
        return active, 200

    candidate_refs = set()
    if plan_definition_guid:
        candidate_refs.add(f'PlanDefinition/{plan_definition_guid}')
    if plan_definition_fhir_id:
        candidate_refs.add(f'PlanDefinition/{plan_definition_fhir_id}')

    matched = []
    for c in active:
        for topic in c.get('topic', []):
            if topic.get('reference', '') in candidate_refs:
                matched.append(c)
                break
    return matched, 200

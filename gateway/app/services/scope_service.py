"""Request-side contract scope service (ticket #135).

Wraps the contract.pdhc `/internal/contract/<guid>/scope` endpoint so
that ServiceRequest creation can refuse to author SRs whose concepts
fall outside the contract's `request_scope`.

Mirrors `gateway.pdhc/services/contract_scope.py` deliberately — the
two services share the upstream API and the same DEAD_STATUSES, but
they enforce different sides of the contract: gateway.pdhc checks
`return_scope` on submitted reports; request.pdhc checks
`request_scope` when a requester drafts an SR.
"""
import logging

import requests
from flask import current_app

from app.services.session_headers import outbound_session_headers

logger = logging.getLogger(__name__)

DEAD_STATUSES = {'revoked', 'terminated', 'cancelled'}


def fetch_scope(contract_guid):
    """Fetch scope from contract.pdhc's internal endpoint.

    Returns:
        dict with keys: contract_guid, status, scope_defined,
        request_scope (list of concept GUIDs or None),
        return_scope (dict or None). Returns None on transport
        failure or 404 — caller decides whether to fail-open.
    """
    base = current_app.config.get('CONTRACT_BASE_URL', '').rstrip('/')
    if not base:
        logger.warning('CONTRACT_BASE_URL not configured; cannot validate scope')
        return None

    service_key = current_app.config.get('INTERNAL_SERVICE_KEY', '')
    if not service_key:
        logger.warning('INTERNAL_SERVICE_KEY not configured; cannot validate scope')
        return None

    url = f'{base}/internal/contract/{contract_guid}/scope'
    try:
        resp = requests.get(
            url,
            headers={'X-Service-Key': service_key,
                     'X-Source-Service': 'request.pdhc',
                     **outbound_session_headers()},
            timeout=10,
        )
    except requests.RequestException as e:
        logger.warning('contract scope fetch failed: %s', e)
        return None

    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        logger.warning('contract scope fetch returned %d', resp.status_code)
        return None

    try:
        return resp.json()
    except ValueError:
        logger.warning('contract scope response was not valid JSON')
        return None


def _coerce_to_guids(items):
    """Scope rows can be strings or dicts with concept_guid."""
    out = set()
    for v in items or []:
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, dict):
            g = v.get('concept_guid') or v.get('guid')
            if g:
                out.add(g)
    return out


def request_scope_guids(scope):
    """Return the set of permitted request_scope concept GUIDs."""
    return _coerce_to_guids((scope or {}).get('request_scope'))


def extract_concept_guids_from_snapshot(snapshot):
    """Collect every concept GUID referenced by a PlanDefinition snapshot.

    Walks both the procedure/goal concept on each Activity and the
    measurement concept on each Transaction. Returns a set so it
    deduplicates naturally.
    """
    guids = set()
    if not isinstance(snapshot, dict):
        return guids

    for act in snapshot.get('activities', []) or []:
        if not isinstance(act, dict):
            continue
        if act.get('concept_guid'):
            guids.add(act['concept_guid'])
        for t in act.get('transactions', []) or []:
            if not isinstance(t, dict):
                continue
            if t.get('concept_guid'):
                guids.add(t['concept_guid'])
            if t.get('goal_concept_guid'):
                guids.add(t['goal_concept_guid'])

    for g in snapshot.get('goals', []) or []:
        if isinstance(g, dict) and g.get('concept_guid'):
            guids.add(g['concept_guid'])

    return guids


def validate_snapshot_against_scope(snapshot, contract_guid):
    """Validate a PlanDefinition snapshot against the contract scope.

    Returns (verdict, payload) where verdict ∈ {
        'allow'           — scope_defined=False or contract has no
                            request_scope (backward compatible), or
                            scope service is unreachable (fail-open
                            for availability).
        'allow_active'    — scope_defined=True, all concepts in scope.
        'contract_inactive' — scope service reports a dead contract.
        'out_of_scope'    — at least one concept is not in
                            request_scope. payload includes
                            'out_of_scope_concept_guids'.
        'scope_unavailable' — wired this way for the future; today we
                              fall through to 'allow' on transport
                              failure.
    }
    """
    if not contract_guid:
        return 'allow', {}

    scope = fetch_scope(contract_guid)
    if scope is None:
        # Fail-open: do not block legitimate authoring when contract
        # service is unreachable. Logged in fetch_scope.
        return 'allow', {}

    status = scope.get('status')
    if status in DEAD_STATUSES:
        return 'contract_inactive', {'status': status}

    if not scope.get('scope_defined'):
        return 'allow', {}

    permitted = request_scope_guids(scope)
    if not permitted:
        # scope_defined=True but no request_scope list — treat as
        # "every concept allowed for requests" (the contract only
        # restricts return_scope on this contract). The provider
        # integration guide is explicit that request_scope is optional;
        # absence ≠ "deny all".
        return 'allow_active', {}

    referenced = extract_concept_guids_from_snapshot(snapshot)
    out_of_scope = sorted(referenced - permitted)
    if out_of_scope:
        return 'out_of_scope', {
            'out_of_scope_concept_guids': out_of_scope,
            'permitted_count': len(permitted),
            'referenced_count': len(referenced),
        }
    return 'allow_active', {}

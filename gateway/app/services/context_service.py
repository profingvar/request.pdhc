"""SR context extraction for gateway.pdhc internal API."""
import time

import requests
from flask import current_app

from app.models.service_request_models import ServiceRequest


# plan.pdhc response_type_name (lower-cased) -> gateway ObservationValidator
# vocab (numeric | categorical | text | boolean | dateTime | graph).
_PLAN_RT_TO_GATEWAY = {
    'numerical': 'numeric',
    'integer': 'numeric',
    'slider': 'numeric',
    'boolean': 'boolean',
    'single choice': 'categorical',
    'multiple choice': 'categorical',
    'free text': 'text',
    'text': 'text',
}

# Cache of {concept_guid: gateway_response_type}, refreshed from plan.pdhc.
_rt_cache = {'ts': 0.0, 'by_concept': {}}
_RT_TTL = 300.0


def _plan_concept_response_types():
    """Resolve ``{concept_guid: gateway_response_type}`` from plan.pdhc.

    plan.pdhc is the authority on a concept's response_type; the SR snapshot
    does not carry it, so we resolve concept -> response_type_guid -> name ->
    gateway vocab. The terminology endpoints are public-read. Cached for
    ``_RT_TTL`` seconds; on any failure returns the last good map (stale-if-
    error) so a plan.pdhc blip doesn't regress every concept to 'text'.
    """
    now = time.monotonic()
    if _rt_cache['by_concept'] and (now - _rt_cache['ts']) < _RT_TTL:
        return _rt_cache['by_concept']
    base = (current_app.config.get('PLAN_BASE_URL') or '').rstrip('/')
    if not base:
        return _rt_cache['by_concept']
    try:
        h = {'Accept': 'application/json'}
        rt = requests.get(f'{base}/api/v1/lookup/response-types',
                          headers=h, timeout=6)
        cc = requests.get(f'{base}/api/v1/concepts',
                          params={'per_page': '1000'}, headers=h, timeout=8)
        rt.raise_for_status()
        cc.raise_for_status()
        rt_items = rt.json()
        rt_items = rt_items.get('items', rt_items) if isinstance(rt_items, dict) else rt_items
        rt_name = {r.get('guid'): (r.get('response_type_name') or '')
                   for r in rt_items}
        cc_items = cc.json()
        cc_items = cc_items.get('items', cc_items) if isinstance(cc_items, dict) else cc_items
        by_concept = {}
        for c in cc_items:
            cg = c.get('guid')
            name = rt_name.get(c.get('response_type'), '')
            mapped = _PLAN_RT_TO_GATEWAY.get(name.strip().lower())
            if cg and mapped:
                by_concept[cg] = mapped
        if by_concept:
            _rt_cache['by_concept'] = by_concept
            _rt_cache['ts'] = now
        return by_concept
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return _rt_cache['by_concept']


def get_sr_context(sr_guid):
    """Extract gateway-relevant context from a stored ServiceRequest.

    Returns a dict with pre-extracted transactions, goals, and metadata,
    or None if the SR doesn't exist.
    """
    sr = ServiceRequest.query.filter_by(guid=sr_guid).first()
    if not sr:
        return None

    snapshot = sr.plan_definition_snapshot or {}
    transactions = _extract_transactions(snapshot)
    goals = _extract_goals(sr.fhir_resource or {})

    return {
        'service_request_guid': sr.guid,
        'status': sr.status,
        'patient_guid': sr.patient_guid,
        'contract_guid': sr.contract_guid,
        'requester_org_guid': sr.requester_org_guid,
        'requester_user_guid': sr.requester_user_guid,
        'requester_user_name': sr.requester_user_name,
        # #294 / #306 phase 6: canonical clinical-context name emitted
        # alongside the legacy `requester_org_guid` during the
        # deprecation window. Consumers should switch to
        # `requesting_org_guid`; legacy key removed after one release.
        'requesting_org_guid': sr.requester_org_guid,
        'plan_definition_guid': sr.plan_definition_guid,
        'period_start': sr.period_start.isoformat() if sr.period_start else None,
        'period_end': sr.period_end.isoformat() if sr.period_end else None,
        'transactions': transactions,
        'goals': goals,
    }


def _infer_response_type(tx):
    """Resolve gateway-compatible response_type for a plan transaction.

    gateway's ObservationValidator requires a response_type, but the SR
    snapshot doesn't carry one. Authoritative path: the concept's real
    response_type from plan.pdhc, mapped to the gateway vocab. Fallback (plan
    unreachable, or concept not resolvable): infer from the transaction shape:
      - numeric range or expected numeric → 'numeric'
      - unit present (typical of numeric measurements) → 'numeric'
      - otherwise → 'text' (safe fallback the validator accepts)

    Prior to this fix the code used ONLY the shape heuristic, which returned
    'text' for numeric concepts whose lossy snapshot dropped range+unit
    (FEV1, spo2, peak-flow …) — the validator then 422'd every numeric
    reading a provider submitted.
    """
    concept_guid = tx.get('concept_guid')
    if concept_guid:
        resolved = _plan_concept_response_types().get(concept_guid)
        if resolved:
            return resolved
    if tx.get('range_min') is not None or tx.get('range_max') is not None:
        return 'numeric'
    ev = tx.get('expected_value')
    if isinstance(ev, (int, float)):
        return 'numeric'
    if isinstance(ev, str):
        try:
            float(ev)
            return 'numeric'
        except (ValueError, TypeError):
            pass
    if tx.get('unit'):
        return 'numeric'
    return 'text'


def _extract_transactions(snapshot):
    """Extract flat transaction list from a PlanDefinition snapshot.

    The snapshot is the JSON that plan.pdhc hands down at SR-creation
    time. Its shape is:
        {goals: [...],
         activities: [{goal_guid, goal_concept_guid,
                       transactions: [{guid, concept_guid, goal_guid,
                                       goal_concept_guid, range_min, ...}]}]}

    Gateway needs a flat list keyed by `transaction_guid`, which in plan
    snapshots lives in the `guid` field. We also synthesise `response_type`
    (see `_infer_response_type`) because plan.pdhc's transaction schema
    has no equivalent field, and we carry the **goal** concept forward
    so downstream enrichment can tag observations with the *measurement*
    concept (e.g. B-glucos) instead of the transaction's *procedure*
    concept (e.g. CGM). This is what contract-scope validation checks.

    Back-compat fallback: if the snapshot predates the plan.pdhc edit
    that writes `goal_guid`/`goal_concept_guid` onto each transaction,
    infer from a single top-level goal.
    """
    top_goals = snapshot.get('goals', []) or []
    fallback_goal_guid = top_goals[0].get('guid') if len(top_goals) == 1 else None
    fallback_goal_concept = top_goals[0].get('concept_guid') if len(top_goals) == 1 else None
    fallback_goal_concept_name = top_goals[0].get('concept_name') if len(top_goals) == 1 else None

    transactions = []
    for activity in snapshot.get('activities', []) or []:
        activity_goal_guid = activity.get('goal_guid') or fallback_goal_guid
        activity_goal_concept = activity.get('goal_concept_guid') or fallback_goal_concept
        activity_goal_concept_name = activity.get('goal_concept_name') or fallback_goal_concept_name
        for tx in activity.get('transactions', []) or []:
            txn_guid = tx.get('guid')
            # Snapshots built from older plan.pdhc versions may lack a
            # `guid` per transaction. Fall back to `concept_guid` so the
            # transaction still appears in the map — gateway's single-txn
            # fallback or concept-based matching can then resolve it.
            if not txn_guid:
                txn_guid = tx.get('concept_guid')
            if not txn_guid:
                continue
            transactions.append({
                'transaction_guid': txn_guid,
                'concept_guid': tx.get('concept_guid'),
                'concept_name': tx.get('concept_name', ''),
                'goal_guid': tx.get('goal_guid') or activity_goal_guid,
                'goal_concept_guid': tx.get('goal_concept_guid') or activity_goal_concept,
                'goal_concept_name': tx.get('goal_concept_name') or activity_goal_concept_name,
                'unit': tx.get('unit'),
                'unit_display': tx.get('unit_display', ''),
                'expected_value': tx.get('expected_value'),
                'range_min': tx.get('range_min'),
                'range_max': tx.get('range_max'),
                'requirement_type': tx.get('requirement_type') or 'required',
                'response_type': _infer_response_type(tx),
            })
    return transactions


def _extract_goals(fhir_resource):
    """Extract goals from contained Goal resources."""
    contained = fhir_resource.get('contained', [])
    goals = []
    for resource in contained:
        if resource.get('resourceType') != 'Goal':
            continue
        target = (resource.get('target') or [{}])[0] if resource.get('target') else {}
        concept_coding = (resource.get('description', {}).get('coding') or [{}])[0]
        goals.append({
            'description': resource.get('description', {}).get('text', ''),
            'concept_guid': concept_coding.get('code', ''),
            'priority': resource.get('priority', {}).get('text', ''),
            'target_value': target.get('detailQuantity', {}).get('value') if target else None,
            'target_comparator': target.get('detailQuantity', {}).get('comparator') if target else None,
        })
    return goals

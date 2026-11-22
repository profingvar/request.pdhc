"""SR context extraction for gateway.pdhc internal API."""
import logging
import time

import requests
from flask import current_app

from app.models.service_request_models import ServiceRequest
from app.services import patient_service

logger = logging.getLogger(__name__)


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

# Cache of concept->response_type and concept->unit_name, from one plan.pdhc
# fetch. The SR snapshot carries neither, so both are resolved live (#559).
# gateway ObservationValidator's accepted vocab — the values _PLAN_RT_TO_GATEWAY
# maps into, plus the two the validator accepts that plan has no name for.
_GATEWAY_RESPONSE_TYPES = frozenset(
    {'numeric', 'categorical', 'text', 'boolean', 'dateTime', 'graph'}
)

_plan_cache = {'ts': 0.0, 'rt': {}, 'rt_name': {}, 'unit': {}, 'scale': {},
               'valueset': {}, 'label': {}}
_PLAN_TTL = 300.0

# #1043: {valueset_guid: (monotonic ts, [options])}. Only SUCCESSFUL fetches
# are stored, so a plan.pdhc blip is retried on the next call rather than
# remembered as "this concept has no alternatives".
_options_cache = {}


def _unlist(payload):
    return payload.get('items', payload) if isinstance(payload, dict) else payload


def _refresh_plan_maps():
    """Populate ``_plan_cache['rt']`` ({concept_guid: gateway_response_type})
    and ``['unit']`` ({concept_guid: unit_name}) from plan.pdhc.

    plan.pdhc is the authority on a concept's response_type + unit; the SR
    snapshot carries neither. concept -> response_type_guid/unit_guid -> name.
    Read with request's plan service key (#931); these endpoints were
    public-read only because no consumer could authenticate. Cached ``_PLAN_TTL`` s; on any
    failure keeps the last good maps (stale-if-error) so a plan.pdhc blip
    doesn't regress every concept to 'text'/no-unit.
    """
    now = time.monotonic()
    if _plan_cache['rt'] and (now - _plan_cache['ts']) < _PLAN_TTL:
        return
    base = (current_app.config.get('PLAN_BASE_URL') or '').rstrip('/')
    if not base:
        return
    try:
        from app.services.plan_auth import plan_read_headers
        h = {'Accept': 'application/json', **plan_read_headers()}  # #931
        rt = requests.get(f'{base}/api/v1/lookup/response-types', headers=h, timeout=6)
        un = requests.get(f'{base}/api/v1/lookup/units', headers=h, timeout=6)
        rt.raise_for_status()
        un.raise_for_status()
        # Concepts are paginated and server-capped at per_page=200; loop until
        # `total` is consumed. A single page silently drops every concept past
        # the cap, which would regress their unit/response-type to none once
        # plan.pdhc grows beyond one page (the value_unit class of bug).
        concepts = []
        page = 1
        while True:
            cc = requests.get(f'{base}/api/v1/concepts',
                              params={'per_page': '200', 'page': str(page)},
                              headers=h, timeout=8)
            cc.raise_for_status()
            body = cc.json()
            batch = _unlist(body)
            concepts.extend(batch)
            total = body.get('total') if isinstance(body, dict) else None
            if (len(batch) < 200
                    or (total is not None and len(concepts) >= total)
                    or page >= 50):  # 10k-concept backstop
                break
            page += 1
        rt_name = {r.get('guid'): (r.get('response_type_name') or '')
                   for r in _unlist(rt.json())}
        unit_name = {u.get('guid'): (u.get('unit_name') or '')
                     for u in _unlist(un.json())}
        rt_map, rt_name_map, unit_map, scale_map = {}, {}, {}, {}
        valueset_map, label_map = {}, {}
        for c in concepts:
            cg = c.get('guid')
            if not cg:
                continue
            # 2026-11-19: the concept's own SCALE (range_low/high) -- what a
            # value can be at all, e.g. stress 1-7. Not the plan's clinical
            # target range, which a value is expected to leave sometimes.
            lo, hi = c.get('range_low'), c.get('range_high')
            if lo is not None or hi is not None:
                scale_map[cg] = (lo, hi)
            # #1043: the concept's valueset (its answer alternatives) and its
            # display text, for a client that must render an input for it.
            if c.get('valueset'):
                valueset_map[cg] = c['valueset']
            if c.get('concept_display_text'):
                label_map[cg] = c['concept_display_text']
            plan_rt = rt_name.get(c.get('response_type'), '').strip()
            mapped = _PLAN_RT_TO_GATEWAY.get(plan_rt.lower())
            if mapped:
                rt_map[cg] = mapped
            # plan.pdhc's own name ("Numerical", "Single choice", ...) is kept
            # verbatim as well: #583 wants the concept's full definition on the
            # request, not only the gateway-vocab reduction of it.
            if plan_rt:
                rt_name_map[cg] = plan_rt
            u = unit_name.get(c.get('unit'))
            if u:
                unit_map[cg] = u
        if rt_map or unit_map or rt_name_map:
            _plan_cache.update(rt=rt_map, rt_name=rt_name_map,
                               unit=unit_map, scale=scale_map,
                               valueset=valueset_map, label=label_map, ts=now)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return  # keep stale maps


def _plan_concept_response_types():
    _refresh_plan_maps()
    return _plan_cache['rt']


def _plan_concept_units():
    _refresh_plan_maps()
    return _plan_cache['unit']


def _plan_concept_scales():
    _refresh_plan_maps()
    return _plan_cache.get('scale') or {}


def _plan_concept_response_type_names():
    _refresh_plan_maps()
    return _plan_cache['rt_name']


def _plan_concept_labels():
    _refresh_plan_maps()
    return _plan_cache.get('label') or {}


def plan_maps():
    """One refresh attempt, then the cached maps as a plain dict (#1043).

    For a caller that describes MANY transactions in one request (the provider
    download): the `_plan_concept_*` accessors each try a refresh, so with
    plan.pdhc down and nothing cached they would wait out a timeout per
    lookup. `options_down` is per-call state: after one failed valueset fetch
    the rest of that request does not try again.
    """
    _refresh_plan_maps()
    return {**_plan_cache, 'options_down': False}


def _plan_concept_options(concept_guid, maps=None):
    """The answer alternatives plan.pdhc binds to a concept (#1043), as
    ``[{'value', 'label', 'code'}]`` in plan's sort order, or ``None``.

    ``value`` is plan's value_name — the string a categorical observation
    carries; ``label`` is its display text; ``code`` is the value's guid.
    ``None`` means "not known" (no valueset bound, or plan.pdhc could not be
    asked) and is distinct from ``[]``, a bound valueset with no members.
    Read with request's own plan read key (#931); a failure is not cached.
    """
    if maps is None:
        _refresh_plan_maps()
    vs_guid = ((maps or _plan_cache).get('valueset') or {}).get(concept_guid)
    if not vs_guid:
        return None
    now = time.monotonic()
    hit = _options_cache.get(vs_guid)
    if hit and (now - hit[0]) < _PLAN_TTL:
        return hit[1]
    if maps is not None and maps.get('options_down'):
        return hit[1] if hit else None
    base = (current_app.config.get('PLAN_BASE_URL') or '').rstrip('/')
    if not base:
        return None
    try:
        from app.services.plan_auth import plan_read_headers
        resp = requests.get(
            f'{base}/api/v1/lookup/valuesets/{vs_guid}/values',
            headers={'Accept': 'application/json', **plan_read_headers()},
            timeout=6)
        resp.raise_for_status()
        values = _unlist(resp.json())
        options = []
        for v in values:
            if not isinstance(v, dict):
                continue
            name = v.get('value_name') or v.get('value_display_text')
            if not name:
                continue
            options.append({'value': str(name),
                            'label': str(v.get('value_display_text') or name),
                            'code': v.get('guid')})
    except (requests.RequestException, ValueError, KeyError, TypeError):
        if maps is not None:
            maps['options_down'] = True
        return hit[1] if hit else None  # stale-if-error, else unknown
    _options_cache[vs_guid] = (now, options)
    return options


def transaction_detail(tx, maps=None):
    """What a client needs to render an input for one snapshot transaction
    (#1043): label, answer type, unit, the allowed interval and the options.

    The snapshot's own values win (a captured request describes itself, #583);
    plan.pdhc is the fallback. ``scale_min``/``scale_max`` are the concept's
    SCALE — the interval gateway enforces with OUT_OF_SCALE — resolved the
    same way ``_extract_transactions`` resolves it for gateway, so what the
    client is told and what gateway refuses are one rule. They are NOT
    ``range_min``/``range_max``, the clinical range a value may well leave.
    """
    if maps is None:
        maps = plan_maps()
    cg = tx.get('concept_guid')
    scale = (maps.get('scale') or {}).get(cg) or (None, None)
    response_type = _infer_response_type(tx, rt_map=maps.get('rt') or {})
    options = tx.get('options')
    if options is None and response_type == 'categorical':
        options = _plan_concept_options(cg, maps)
    return {
        'label': (tx.get('concept_display_text')
                  or (maps.get('label') or {}).get(cg)
                  or tx.get('concept_name') or ''),
        'response_type': response_type,
        'response_type_name': (tx.get('response_type_name')
                               or (maps.get('rt_name') or {}).get(cg)
                               or ''),
        'unit': tx.get('unit') or tx.get('concept_unit_name')
                or (maps.get('unit') or {}).get(cg),
        'scale_min': tx.get('scale_min') if tx.get('scale_min') is not None else scale[0],
        'scale_max': tx.get('scale_max') if tx.get('scale_max') is not None else scale[1],
        'options': options,
        'required': (tx.get('requirement_type') or 'required') == 'required',
    }


def enrich_snapshot_concepts(snapshot):
    """Stamp each transaction in a PlanDefinition snapshot with the full
    concept definition, at capture time (#583).

    plan.pdhc's plandef payload names a concept but not what kind of answer
    it takes: ``response_type`` and ``unit`` live on the *concept*, not on the
    transaction, so a stored snapshot has historically carried neither. Every
    consumer therefore had to call back to plan.pdhc to interpret an
    observation (see ``_infer_response_type`` and #559), which makes the
    request depend on a live service and lets the interpretation of an old
    request drift when a concept is later edited.

    This writes the definition *into* the snapshot instead, so the stored
    ServiceRequest is self-describing:

        response_type        gateway vocab  — numeric | categorical | text |
                                              boolean | dateTime | graph
        response_type_name   plan.pdhc's own name — "Numerical", "Single
                                              choice", ... (what #583 asks for)
        unit                 unit name, e.g. "L", "mmol/mol"

    Values already present in the snapshot are never overwritten — plan.pdhc
    is the fallback, not the authority, once a request has been captured.
    Mutates and returns ``snapshot``. Never raises: if plan.pdhc is
    unreachable the snapshot is stored unenriched and the existing runtime
    resolution still applies, so this can only add information.
    """
    if not isinstance(snapshot, dict):
        return snapshot
    try:
        rt_map = _plan_concept_response_types()
        rt_name_map = _plan_concept_response_type_names()
        unit_map = _plan_concept_units()
    except Exception:  # pragma: no cover - defensive, _refresh already guards
        return snapshot
    if not (rt_map or rt_name_map or unit_map):
        return snapshot

    for activity in snapshot.get('activities') or []:
        if not isinstance(activity, dict):
            continue
        for tx in activity.get('transactions') or []:
            if not isinstance(tx, dict):
                continue
            concept_guid = tx.get('concept_guid')
            if not concept_guid:
                continue
            if not tx.get('response_type'):
                mapped = rt_map.get(concept_guid)
                if mapped:
                    tx['response_type'] = mapped
            if not tx.get('response_type_name'):
                plan_name = rt_name_map.get(concept_guid)
                if plan_name:
                    tx['response_type_name'] = plan_name
            if not tx.get('unit'):
                unit = unit_map.get(concept_guid)
                if unit:
                    tx['unit'] = unit
            # #1043: the display text and, for a choice concept, its answer
            # alternatives — frozen with the order for the same reason as the
            # three above. Absent when plan.pdhc gives none.
            if not tx.get('concept_display_text'):
                label = _plan_concept_labels().get(concept_guid)
                if label:
                    tx['concept_display_text'] = label
            if tx.get('options') is None and tx.get('response_type') == 'categorical':
                options = _plan_concept_options(concept_guid)
                if options is not None:
                    tx['options'] = options
    return snapshot


def _human_name(fhir_patient):
    """Best-effort display name from a FHIR Patient (name[0]: text or given+family)."""
    names = (fhir_patient or {}).get('name') or []
    if not isinstance(names, list) or not names:
        return None
    n0 = names[0] or {}
    if n0.get('text'):
        return str(n0['text']).strip() or None
    given = ' '.join(n0.get('given') or [])
    family = n0.get('family') or ''
    full = f'{given} {family}'.strip()
    return full or None


#: FHIR AdministrativeGender. Anything else from ips is not passed on.
_GENDERS = ('male', 'female', 'other', 'unknown')


def _resolve_patient_demographics(patient_guid):
    """(name, birth_date, gender) for a patient, resolved from ips — the
    registry of record. Fail-soft: any error / not-found returns
    (None, None, None) so the SR context is never blocked and unregistered
    patients (e.g. an external provider's patient that was never registered)
    stay pseudonymous.

    2026-11-20: gender added. gateway rewrote cdr1's Patient from this context
    without it, so every sync dropped the patient's sex and the federated
    analysis reported it missing."""
    if not patient_guid:
        return None, None, None
    try:
        body, status = patient_service.get_patient(patient_guid)
        if status != 200 or not isinstance(body, dict):
            return None, None, None
        gender = str(body.get('gender') or '').strip().lower()
        return (_human_name(body), (body.get('birthDate') or None),
                gender if gender in _GENDERS else None)
    except Exception as exc:  # noqa: BLE001 — demographics are best-effort
        logger.warning('ips demographics lookup failed for %s: %s',
                       str(patient_guid)[:12], exc)
        return None, None, None


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

    # Patient demographics from ips (registry of record). gateway uses these to
    # populate CDR1's patient row so care-delivery dashboards show a name.
    # Fail-soft: absent keys keep the patient pseudonymous downstream.
    patient_name, patient_birth_date, patient_gender = \
        _resolve_patient_demographics(sr.patient_guid)

    context = {
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
        # #774: the PATIENT's organisation, distinct from the requester above.
        # The gateway forwards this to the CDR, which stores it on the datapoint
        # row (#769). Snapshotted at SR creation because ips keeps no
        # assignment history.
        # getattr, not attribute access: this can be handed an SR read before
        # the column existed — during a rolling deploy, or from a test double.
        # Same reason gateway's cdr_forwarder uses it for author_org_guid.
        'patient_org_guid': getattr(sr, 'patient_org_guid', None),
        'plan_definition_guid': sr.plan_definition_guid,
        # 2026-11-20: the CarePlan the request is based on (care_plan_link).
        # gateway forwards it to the CDR's clinical_context; until now 0 of
        # the observations gateway delivered to cdr1 carried one.
        'care_plan_guid': getattr(sr, 'care_plan_guid', None),
        'period_start': sr.period_start.isoformat() if sr.period_start else None,
        'period_end': sr.period_end.isoformat() if sr.period_end else None,
        'transactions': transactions,
        'goals': goals,
    }
    # Emit as a pair keyed off the name: the dashboard identifies the patient
    # by name, so a lone birthDate is never useful — keep it pseudonymous.
    if patient_name:
        context['patient_name'] = patient_name
        if patient_birth_date:
            context['patient_birth_date'] = patient_birth_date
        if patient_gender:
            context['patient_gender'] = patient_gender
    return context


def _infer_response_type(tx, rt_map=None):
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
    # #583: an enriched snapshot carries the concept's response_type at
    # capture time. Prefer it — a captured request describes itself, and a
    # later edit to the concept in plan.pdhc must not retro-change how an
    # old request is interpreted. Live lookup stays as the fallback for
    # snapshots captured before enrichment existed.
    own = (tx.get('response_type') or '').strip()
    if own in _GATEWAY_RESPONSE_TYPES:
        return own
    concept_guid = tx.get('concept_guid')
    if concept_guid:
        if rt_map is None:
            rt_map = _plan_concept_response_types()
        resolved = rt_map.get(concept_guid)
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

    units = _plan_concept_units()
    scales = _plan_concept_scales()
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
            tx_unit = tx.get('unit') or units.get(tx.get('concept_guid'))
            goal_guid = tx.get('goal_guid') or activity_goal_guid
            goal_concept = tx.get('goal_concept_guid') or activity_goal_concept
            goal_concept_name = tx.get('goal_concept_name') or activity_goal_concept_name
            # 2026-11-19 (MMD_plan): a goal linkage is only trusted when the
            # goal concept measures in the SAME unit as the transaction.
            # Gateway labels a value with its goal concept, and MMD_plan
            # linked its one goal (cgm_mean_glucose, mmol/L) to every
            # activity -- so sleep (h), blood pressure (mmHg), anxiety and
            # stress were all stored as glucose. A value is never labelled
            # with a concept of another unit; the transaction's own concept
            # is used instead. CGM (mmol/L) -> glucose (mmol/L) is unchanged.
            if (goal_concept and goal_concept != tx.get('concept_guid')
                    and (tx_unit or '') != (units.get(goal_concept) or '')):
                goal_guid = goal_concept = goal_concept_name = None
            transactions.append({
                'transaction_guid': txn_guid,
                'concept_guid': tx.get('concept_guid'),
                'concept_name': tx.get('concept_name', ''),
                'goal_guid': goal_guid,
                'goal_concept_guid': goal_concept,
                'goal_concept_name': goal_concept_name,
                # unit resolved from plan.pdhc (#559 — snapshot drops it), so the
                # gateway stamps value_unit; snapshot value wins if it has one.
                'unit': tx_unit,
                'unit_display': tx.get('unit_display', ''),
                'expected_value': tx.get('expected_value'),
                'range_min': tx.get('range_min'),
                'range_max': tx.get('range_max'),
                'requirement_type': tx.get('requirement_type') or 'required',
                # The concept's scale, for gateway's OUT_OF_SCALE check.
                'scale_min': (scales.get(tx.get('concept_guid')) or (None, None))[0],
                'scale_max': (scales.get(tx.get('concept_guid')) or (None, None))[1],
                'response_type': _infer_response_type(tx),
                # #583: plan.pdhc's own name for the answer kind, carried
                # through so a consumer sees the full concept definition
                # ("Numerical", "Single choice", ...) and not only the
                # gateway-vocab reduction of it.
                'response_type_name': (
                    tx.get('response_type_name')
                    or _plan_concept_response_type_names().get(
                        tx.get('concept_guid'))
                    or ''
                ),
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

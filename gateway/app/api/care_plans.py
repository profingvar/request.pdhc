"""CarePlan API — patient-specific clinical plan instance.

Built per #310 (#294 RFC decision A1). Distinct from the legacy
`careplans.py` blueprint (which proxies /CarePlan to plan.pdhc and
is being deprecated — pre-#310 the platform used "CarePlan" as a
misnomer for PlanDefinition).

Endpoints
=========
POST  /api/v1/careplans                       create from a PlanDefinition for a patient
GET   /api/v1/careplans/<guid>                read one CarePlan
GET   /api/v1/careplans?patient_guid=<p>      list a patient's CarePlans
PUT   /api/v1/careplans/<guid>                update status / goals / period / care team
GET   /api/v1/careplans/<guid>/context        resolved provenance chain
                                              (CarePlan → PlanDefinition snapshot → transactions)

URL choice: lowercase `/careplans` deliberately distinct from the
legacy `/CarePlan` proxy so the two don't collide during the
transition; the legacy proxy will be removed in a follow-up.
"""
from datetime import datetime
import bleach
from flask import Blueprint, jsonify, request
from app import db
from app.models.care_plan_models import CarePlan
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services.auth_service import get_current_user_guid, get_current_access_blob
from app.services import patient_access
from app.services.audit_service import audit_read, log_event
from app.services import context_service
from app.services import plan_definition_service
from app.services import action_limits

care_plans_bp = Blueprint('care_plans_api', __name__)


def _gate(patient_guid, verb, care_plan_guid=None):
    """None when the caller may reach this patient, else the refusal (#981).

    The rule is app/services/patient_access.py — the SAME decision
    POST /ServiceRequest uses. Every refusal is audited with its reason; a
    write by an SU admin is audited as a bypass. Reads are audited on success
    by @audit_read, as the ServiceRequest reads are.
    """
    decision = patient_access.evaluate(get_current_access_blob(), patient_guid)
    patient_access.note_subject(patient_guid)
    if not decision.allowed:
        log_event(user_guid=get_current_user_guid(),
                  action=f'care_plan.{verb}.denied', resource_type='CarePlan',
                  resource_guid=care_plan_guid, data_subject_guid=patient_guid,
                  ip_address=request.remote_addr,
                  details={'reason': decision.reason, **decision.details})
        messages = {
            'patient_not_found': 'Patient not found',
            'ips_lookup_failed': 'Could not verify patient affiliation; try again shortly.',
            'patient_org_mismatch': ('Patient is not assigned to any clinic in your '
                                     'organisations (PDL Ch 4 §§ 1-2).'),
        }
        return jsonify({'code': decision.code,
                        'message': messages[decision.reason]}), decision.status
    if decision.is_su and verb in ('create', 'update'):
        log_event(user_guid=get_current_user_guid(),
                  action=f'care_plan.{verb}.admin_bypass', resource_type='CarePlan',
                  resource_guid=care_plan_guid, data_subject_guid=patient_guid,
                  ip_address=request.remote_addr,
                  details={'reason': 'caller_is_su_admin'})
    return None


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


@care_plans_bp.route('/careplans', methods=['POST'])
@requires_auth
@requires_role('read_write')
def create_care_plan():
    """Create a CarePlan FROM a PlanDefinition for a specific patient.

    Required body fields: patient_guid, plan_definition_guid.
    Optional: title, description, period_start, period_end, goals (overlay),
    care_team_user_guids, status (default 'draft'), intent (default 'plan').

    A snapshot of the PlanDefinition is captured at create time so
    subsequent edits to the template do not silently alter this
    patient's plan.
    """
    body = request.get_json(silent=True) or {}
    patient_guid = bleach.clean(str(body.get('patient_guid') or '')).strip()
    plandef_guid = bleach.clean(str(body.get('plan_definition_guid') or '')).strip()
    if not patient_guid or not plandef_guid:
        return jsonify({'error': 'patient_guid and plan_definition_guid required'}), 400
    refused = _gate(patient_guid, 'create')
    if refused:
        return refused

    # Pull the PlanDefinition snapshot from plan.pdhc. We accept either
    # a 200 with the JSON body or a transient 5xx (in which case the
    # CarePlan is created without the snapshot — clinician can re-fetch
    # later).
    snapshot = None
    plandef_goals = []
    try:
        pd, status = plan_definition_service.get_plan_definition(plandef_guid)
        if status == 200 and isinstance(pd, dict):
            snapshot = pd
            plandef_goals = pd.get('goals') or []
    except Exception:
        snapshot = None

    # #583: same enrichment as on ServiceRequest creation — the care plan's
    # stored snapshot carries each concept's full definition.
    if snapshot is not None:
        snapshot = context_service.enrich_snapshot_concepts(snapshot)

    try:
        initial_goals = _initial_goals(body.get('goals'), plandef_goals)
    except action_limits.InvalidActionLimit as e:
        return jsonify({'code': 'invalid_action_limit', 'message': str(e)}), 400

    cp = CarePlan(
        patient_guid=patient_guid,
        plan_definition_guid=plandef_guid,
        status=bleach.clean(str(body.get('status') or 'draft')),
        intent=bleach.clean(str(body.get('intent') or 'plan')),
        title=body.get('title'),
        description=body.get('description'),
        period_start=_parse_dt(body.get('period_start')),
        period_end=_parse_dt(body.get('period_end')),
        plan_definition_snapshot=snapshot,
        goals=initial_goals,
        care_team_user_guids=body.get('care_team_user_guids') or [],
        created_by_user_guid=get_current_user_guid(),
    )
    db.session.add(cp)
    db.session.commit()
    return jsonify(cp.to_dict()), 201


@care_plans_bp.route('/careplans/<guid>', methods=['GET'])
@requires_auth
@audit_read('care_plan.read', resource_type='CarePlan', guid_arg='guid')
def get_care_plan(guid):
    cp = CarePlan.query.filter_by(guid=bleach.clean(guid)).first()
    if not cp:
        return jsonify({'error': 'not found'}), 404
    refused = _gate(cp.patient_guid, 'read', cp.guid)
    if refused:
        return refused
    return jsonify(cp.to_dict()), 200


@care_plans_bp.route('/careplans', methods=['GET'])
@requires_auth
@audit_read('care_plan.list', resource_type='CarePlan')
def list_care_plans():
    """List CarePlans for ONE patient (#981).

    `patient_guid` is REQUIRED for every caller but an SU admin: unfiltered,
    this returned up to 500 care plans across all patients to anyone holding a
    credential. With a patient, the caller must reach that patient.
    """
    patient_guid = request.args.get('patient_guid')
    status_filter = request.args.get('status')
    if patient_guid:
        refused = _gate(bleach.clean(patient_guid), 'list')
        if refused:
            return refused
    else:
        blob = get_current_access_blob()
        if not (blob and blob.get('is_su_admin')):
            log_event(user_guid=get_current_user_guid(), action='care_plan.list.denied',
                      resource_type='CarePlan', ip_address=request.remote_addr,
                      details={'reason': 'patient_guid_required'})
            return jsonify({'code': 'bad_request',
                            'message': 'patient_guid is required'}), 400
    limit = min(int(request.args.get('limit', 100)), 500)
    offset = int(request.args.get('offset', 0))

    q = CarePlan.query
    if patient_guid:
        q = q.filter(CarePlan.patient_guid == bleach.clean(patient_guid))
    if status_filter:
        q = q.filter(CarePlan.status == bleach.clean(status_filter))
    q = q.order_by(CarePlan.created_at.desc()).limit(limit).offset(offset)
    rows = q.all()
    return jsonify({
        'total': len(rows),
        'careplans': [r.to_dict() for r in rows],
    }), 200


@care_plans_bp.route('/careplans/<guid>', methods=['PUT'])
@requires_auth
@requires_role('read_write')
def update_care_plan(guid):
    """Update mutable fields. Patient + plan_definition references are
    immutable once created.

    #981: GATED, and it matters more than the reads — `goals` set the LIMITS
    the patient dashboard judges values against (MDR class IIa, 2026-11-12).
    """
    cp = CarePlan.query.filter_by(guid=bleach.clean(guid)).first()
    if not cp:
        return jsonify({'error': 'not found'}), 404
    refused = _gate(cp.patient_guid, 'update', cp.guid)
    if refused:
        return refused
    body = request.get_json(silent=True) or {}
    for field in ('status', 'intent', 'title', 'description'):
        if field in body:
            cp.__setattr__(field, body[field])
    if 'period_start' in body:
        cp.period_start = _parse_dt(body['period_start'])
    if 'period_end' in body:
        cp.period_end = _parse_dt(body['period_end'])
    goal_changes = None
    if 'goals' in body:
        try:
            cp.goals, goal_changes = action_limits.merge_goals(cp.goals, body['goals'])
        except action_limits.InvalidActionLimit as e:
            return jsonify({'code': 'invalid_action_limit', 'message': str(e)}), 400
    if 'care_team_user_guids' in body:
        cp.care_team_user_guids = body['care_team_user_guids']
    db.session.commit()
    if goal_changes is not None:
        # The goals ARE the action limits the dashboard judges against
        # (MDR IIa): every change is audited with before/after.
        log_event(user_guid=get_current_user_guid(), action='care_plan.goals_update',
                  resource_type='CarePlan', resource_guid=cp.guid,
                  data_subject_guid=cp.patient_guid,
                  details={'action_limit_changes': goal_changes},
                  ip_address=request.remote_addr)
    return jsonify(cp.to_dict()), 200


def _initial_goals(requested, plandef_goals):
    """Requester-supplied goals are theirs; otherwise plan's recommendation."""
    if requested:
        return action_limits.stamp_recommended_goals(requested, from_plan=False)
    return action_limits.stamp_recommended_goals(plandef_goals, from_plan=True)


@care_plans_bp.route('/careplans/<guid>/context', methods=['GET'])
@requires_auth
@audit_read('care_plan.context.read', resource_type='CarePlan', guid_arg='guid')
def care_plan_context(guid):
    """Resolved provenance for a CarePlan.

    Returns the CarePlan + its PlanDefinition snapshot + the transactions
    extracted from the snapshot. Mirrors the existing
    /service-request/<sr_guid>/context shape so gateway can call either
    by URL.
    """
    cp = CarePlan.query.filter_by(guid=bleach.clean(guid)).first()
    if not cp:
        return jsonify({'error': 'not found'}), 404
    refused = _gate(cp.patient_guid, 'context', cp.guid)
    if refused:
        return refused

    snapshot = cp.plan_definition_snapshot or {}
    transactions = []
    for activity in (snapshot.get('activities') or []):
        for tx in (activity.get('transactions') or []):
            transactions.append({
                'activity_guid': activity.get('guid'),
                'transaction_guid': tx.get('guid'),
                'concept_guid': tx.get('concept_guid'),
                'concept_name': tx.get('concept_name'),
                'range_min': tx.get('range_min'),
                'range_max': tx.get('range_max'),
                'requirement_type': tx.get('requirement_type'),
            })
    return jsonify({
        'care_plan_guid': cp.guid,
        'patient_guid': cp.patient_guid,
        'plan_definition_guid': cp.plan_definition_guid,
        'status': cp.status,
        'intent': cp.intent,
        'period_start': cp.period_start.isoformat() if cp.period_start else None,
        'period_end': cp.period_end.isoformat() if cp.period_end else None,
        'goals': cp.goals or [],
        'transactions': transactions,
    }), 200

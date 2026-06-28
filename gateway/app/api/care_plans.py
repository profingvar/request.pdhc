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
from app.middleware.auth_middleware import requires_auth
from app.services.auth_service import get_current_user_guid
from app.services import plan_definition_service

care_plans_bp = Blueprint('care_plans_api', __name__)


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
        goals=body.get('goals') or plandef_goals,
        care_team_user_guids=body.get('care_team_user_guids') or [],
        created_by_user_guid=get_current_user_guid(),
    )
    db.session.add(cp)
    db.session.commit()
    return jsonify(cp.to_dict()), 201


@care_plans_bp.route('/careplans/<guid>', methods=['GET'])
@requires_auth
def get_care_plan(guid):
    cp = CarePlan.query.filter_by(guid=bleach.clean(guid)).first()
    if not cp:
        return jsonify({'error': 'not found'}), 404
    return jsonify(cp.to_dict()), 200


@care_plans_bp.route('/careplans', methods=['GET'])
@requires_auth
def list_care_plans():
    """List CarePlans, optionally filtered by patient_guid + status."""
    patient_guid = request.args.get('patient_guid')
    status_filter = request.args.get('status')
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
def update_care_plan(guid):
    """Update mutable fields. Patient + plan_definition references are
    immutable once created."""
    cp = CarePlan.query.filter_by(guid=bleach.clean(guid)).first()
    if not cp:
        return jsonify({'error': 'not found'}), 404
    body = request.get_json(silent=True) or {}
    for field in ('status', 'intent', 'title', 'description'):
        if field in body:
            cp.__setattr__(field, body[field])
    if 'period_start' in body:
        cp.period_start = _parse_dt(body['period_start'])
    if 'period_end' in body:
        cp.period_end = _parse_dt(body['period_end'])
    if 'goals' in body:
        cp.goals = body['goals']
    if 'care_team_user_guids' in body:
        cp.care_team_user_guids = body['care_team_user_guids']
    db.session.commit()
    return jsonify(cp.to_dict()), 200


@care_plans_bp.route('/careplans/<guid>/context', methods=['GET'])
@requires_auth
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

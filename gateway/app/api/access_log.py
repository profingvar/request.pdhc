"""#1045 loggkontroll: ONE patient's access log from request.pdhc, for a PERSON.

    GET /api/v1/patients/<patient guid>/access-log
        ?from=<ISO instant>  ?to=<ISO instant, exclusive>  ?limit=<n>

Patientdatalagen 4 kap. 3 §: dashboard.pdhc merges the access logs of the
services that hold a patient's data. This is request's part: `audit_logs`
rows about the patient — orders (ServiceRequest) and care plans created,
read, changed, refused.

WHICH ROWS. `data_subject_guid` = the patient, PLUS rows about one of the
patient's ServiceRequests or CarePlans by `resource_guid`: before #1045
`@audit_read` wrote no `data_subject_guid` at all, so a read of
`GET /ServiceRequest/<guid>` was tied to the patient only through the order.

THE GATE (PDL 4 kap. 1-2 §§, Rule 24):
  * a PERSON: the operator's SSO token sent as `X-API-Key` (the door
    dashboard and onboard use) or a request session; never a provider PAT
    (`X-Provider-Token`) and never a `service` blob — 403 `person_required`;
  * an SU admin or a professional; anyone else 403 `not_professional`;
  * then `patient_access.evaluate`, the ONE rule every patient route here
    uses: SU, or one of the caller's affiliated care units is the
    organisation of one of the patient's clinics in eps. eps unreachable is
    502 — fail closed, never an empty log.

The read of the log is itself logged (`access_log.read`), and so is every
refusal (`access_log.read.denied`, with its reason).
"""
from __future__ import annotations

from datetime import datetime, timezone

import bleach
from flask import Blueprint, g, jsonify, request
from sqlalchemy import and_, or_

from app.middleware.auth_middleware import requires_auth
from app.models.audit_models import AuditLog
from app.models.care_plan_models import CarePlan
from app.models.service_request_models import ServiceRequest
from app.services import patient_access
from app.services.audit_service import log_event
from app.services.auth_service import get_current_access_blob

access_log_bp = Blueprint('access_log_api', __name__)

DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000

#: `details` keys handed out. Metadata only.
_DETAIL_KEYS = ('reason', 'status', 'outcome', 'access_basis')


def _err(status, code, message):
    return jsonify({'code': code, 'message': message}), status


def caller_blob():
    """The PERSON behind this request, or None. On `X-API-Key` that is the
    operator's own SSO blob, validated with sso by requires_auth in this
    request (get_current_access_blob reads it from `g`, #1045)."""
    blob = get_current_access_blob()
    return blob if isinstance(blob, dict) else None


def _instant(name):
    raw = (request.args.get(name) or '').strip()
    if not raw:
        return None, None
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None, f'{name} is not an ISO-8601 instant: {raw!r}'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt, None


def _iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _naive_utc(dt):
    """audit_logs.created_at is a naive UTC column."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt else None


def access_item(row):
    details = row.details if isinstance(row.details, dict) else {}
    kept = {k: str(details[k])[:200] for k in _DETAIL_KEYS if details.get(k) is not None}
    action = row.action or ''
    if action.endswith('.denied'):
        outcome = 'denied'
    else:
        outcome = 'served'
    basis = 'su_admin' if (action.endswith('.admin_bypass')
                           or kept.get('reason') == 'caller_is_su_admin') else None
    return {
        'id': row.guid,
        'at': _iso(row.created_at),
        'user_guid': row.user_guid,
        'user_label': None,
        'actor_type': 'user' if row.user_guid else 'system',
        'action': action,
        'outcome': outcome,
        'route': None,
        'resource_type': row.resource_type,
        'session_id': None,
        # The caller's care units, when the refusal recorded them.
        'actor_units': (details.get('caller_org_ids')
                        if isinstance(details.get('caller_org_ids'), list) else None),
        'basis': basis,
        'detail': kept,
    }


@access_log_bp.route('/patients/<patient_guid>/access-log', methods=['GET'])
@requires_auth
def patient_access_log(patient_guid):
    patient_guid = bleach.clean(patient_guid)
    if getattr(g, 'provider_pat', None) is not None:
        return _err(403, 'person_required',
                    "a patient's access log is read by a person, not a provider token")
    blob = caller_blob()
    if blob is None or blob.get('user_type') == 'service':
        return _err(403, 'person_required',
                    "a patient's access log is read with a person's own SSO token")
    user_guid = blob.get('user_guid')
    if not blob.get('is_su_admin') and blob.get('user_type') != 'professional':
        log_event(user_guid=user_guid, action='access_log.read.denied',
                  resource_type='AuditLog', data_subject_guid=patient_guid,
                  ip_address=request.remote_addr, details={'reason': 'not_professional'})
        return _err(403, 'not_professional', 'the access log is for care professionals')

    since, err1 = _instant('from')
    until, err2 = _instant('to')
    if err1 or err2:
        return _err(400, 'bad_request', err1 or err2)
    try:
        limit = max(1, min(MAX_LIMIT, int(request.args.get('limit', DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        return _err(400, 'bad_request', 'limit is not a number')

    decision = patient_access.evaluate(blob, patient_guid)
    if not decision.allowed:
        log_event(user_guid=user_guid, action='access_log.read.denied',
                  resource_type='AuditLog', data_subject_guid=patient_guid,
                  ip_address=request.remote_addr,
                  details={'reason': decision.reason, **decision.details})
        messages = {
            'patient_not_found': 'Patient not found',
            'ips_lookup_failed': 'Could not verify patient affiliation; try again shortly.',
            'patient_org_mismatch': ('Patient is not assigned to any clinic in your '
                                     'organisations (PDL Ch 4 §§ 1-2).'),
        }
        return _err(decision.status, decision.code, messages[decision.reason])

    sr_guids = [r[0] for r in ServiceRequest.query.with_entities(ServiceRequest.guid)
                .filter(ServiceRequest.patient_guid == patient_guid).all()]
    cp_guids = [r[0] for r in CarePlan.query.with_entities(CarePlan.guid)
                .filter(CarePlan.patient_guid == patient_guid).all()]
    about = [AuditLog.data_subject_guid == patient_guid]
    if sr_guids:
        about.append(and_(AuditLog.resource_type.in_(('ServiceRequest', 'ServiceRequestReceipt')),
                          AuditLog.resource_guid.in_(sr_guids)))
    if cp_guids:
        about.append(and_(AuditLog.resource_type == 'CarePlan',
                          AuditLog.resource_guid.in_(cp_guids)))
    q = AuditLog.query.filter(or_(*about))
    if since is not None:
        q = q.filter(AuditLog.created_at >= _naive_utc(since))
    if until is not None:
        q = q.filter(AuditLog.created_at < _naive_utc(until))
    total = q.count()
    rows = q.order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).limit(limit).all()
    items = [access_item(r) for r in rows]

    log_event(user_guid=user_guid, action='access_log.read', resource_type='AuditLog',
              data_subject_guid=patient_guid, ip_address=request.remote_addr,
              details={'n_rows': len(items), 'from': _iso(since), 'to': _iso(until),
                       'access_basis': 'su_admin' if decision.is_su else 'same_unit'})
    return jsonify({'service': 'request.pdhc', 'patient_guid': patient_guid,
                    'from': _iso(since), 'to': _iso(until), 'items': items,
                    'total': total, 'limit': limit, 'truncated': total > len(items)})

"""#1059 (record.pdhc stage 6b): everything request.pdhc holds about ONE
patient, for the journal extract (plan section 4.4; contract
plans/record_pdhc_extract_contract.md).

    GET /api/v1/patient-extract/<patient guid>

THE DOOR AND THE GATE are the loggkontroll's (#1045, app/api/access_log.py):

  * a PERSON - the professional's own SSO token on `X-API-Key` or a request
    session; a provider PAT or a `service` blob is 403 `person_required`;
  * an SU admin, or a professional whose affiliation to one of the patient's
    care units carries the role `doctor` or `nurse` (plan D9; the role codes
    are sso.pdhc's, as in cdr's #1044 review) - the unit match is
    `patient_access.evaluate`, the one patient rule of this service, run on
    the caller's doctor/nurse affiliations only;
  * eps unreachable is 502, never an empty extract.

Every call is audited: `patient_extract` when served, `patient_extract.denied`
with its reason when refused, both with `data_subject_guid` = the patient, so
the loggkontroll lists them.

SECTIONS
  service_requests       every order (diagnosis reviews included), EVERY
                         version oldest first, from service_request_history
                         (#1054) + the current row
  care_plans             every care plan, every version (care_plan_history)
  dispatches             every send of an order to a provider (contract
                         match) with its deliveries, as an R5 Task
  data_exchange_grants   grants issued for the patient's orders (type and
                         dates; the grant token itself never)

Never included: receipt tokens, grant tokens, the personnummer (the contained
Patient's `identifier` is removed; the patient is referred to by guid).
"""
from __future__ import annotations

from datetime import datetime, timezone

import bleach
from flask import Blueprint, g, jsonify, request

from app.middleware.auth_middleware import requires_auth
from app.models.care_plan_models import CarePlan
from app.models.security_models import DataExchangeGrant
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch, ServiceRequestReceipt)
from app.services import patient_access, sr_journal, versioning
from app.services.audit_service import log_event
from app.services.auth_service import get_current_access_blob

patient_extract_bp = Blueprint('patient_extract_api', __name__)

SCHEMA = 'pdhc.patient-extract/1'
SERVICE = 'request.pdhc'
#: sso.pdhc role codes that may take out an extract (plan D9).
EXTRACT_ROLES = frozenset({'doctor', 'nurse'})

PRE_HISTORY_NOTE = ('Versioner före införandet av versionshistorik (#1054) '
                    'registrerades inte; version 1 är posten som den såg ut då.')


def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _err(status, code, message):
    return jsonify({'code': code, 'message': message}), status


def extract_blob(blob):
    """The caller with only the affiliations that may take out an extract.
    Pure, so the role rule can be tested alone."""
    if not isinstance(blob, dict):
        return None
    out = dict(blob)
    out['affiliations'] = [a for a in (blob.get('affiliations') or [])
                           if isinstance(a, dict) and a.get('role') in EXTRACT_ROLES]
    return out


def _deny(user_guid, patient_guid, reason, status, code, message, **details):
    log_event(user_guid=user_guid, action='patient_extract.denied',
              resource_type='Patient', resource_guid=patient_guid,
              data_subject_guid=patient_guid, ip_address=request.remote_addr,
              details={'reason': reason, 'outcome': 'denied', **details})
    return _err(status, code, message)


def _strip_identity(resource):
    """No personnummer outside eps (contract): drop identifier from every
    contained Patient."""
    for c in resource.get('contained') or []:
        if isinstance(c, dict) and c.get('resourceType') == 'Patient':
            c.pop('identifier', None)
    return resource


def _author(guid, sr=None):
    if not guid:
        return None
    name = None
    if sr is not None and guid == getattr(sr, 'requester_user_guid', None):
        name = sr.requester_user_name
    return {'guid': guid, 'name': name, 'role': None, 'service': SERVICE}


def _title(ns):
    snap = getattr(ns, 'plan_definition_snapshot', None) or {}
    return snap.get('title') or 'Beställning'


def service_request_items(patient_guid):
    srs = (ServiceRequest.query.filter_by(patient_guid=patient_guid)
           .order_by(ServiceRequest.created_at.asc(), ServiceRequest.id.asc()).all())
    items, pre_history = [], []
    for sr in srs:
        versions = []
        for v in versioning.sr_versions(sr):
            ns = v['ns']
            fhir = _strip_identity(versioning.render_sr(ns, v['fhir'], v['version'],
                                                        v['recorded_at']))
            label = 'Diagnosgenomgång' if getattr(ns, 'kind', None) == 'diagnosis-review' \
                else 'Beställning'
            versions.append({
                'version': v['version'],
                'event_time': _iso(getattr(ns, 'created_at', None)),
                'recorded_at': v['recorded_at'],
                'author': _author(v['author_guid'], sr),
                'status': ns.status,
                'summary_sv': (f"{label}: {_title(ns)} ({sr_journal.STATUS_SV.get(ns.status, ns.status)})"
                               f", version {v['version']}"),
                'change_reason': v['reason'],
                'superseded': v['ended'],
                'fhir': fhir,
            })
        if versions and versions[0]['change_reason'] == versioning.PRE_HISTORY_REASON:
            pre_history.append(sr.guid)
        items.append({'resource_type': 'ServiceRequest', 'id': sr.guid,
                      'current_status': sr.status, 'versions': versions})
    return items, pre_history


def care_plan_items(patient_guid):
    cps = (CarePlan.query.filter_by(patient_guid=patient_guid)
           .order_by(CarePlan.created_at.asc(), CarePlan.id.asc()).all())
    items, pre_history = [], []
    for cp in cps:
        versions = []
        for v in versioning.cp_versions(cp):
            ns = v['ns']
            versions.append({
                'version': v['version'],
                'event_time': _iso(getattr(ns, 'created_at', None)),
                'recorded_at': v['recorded_at'],
                'author': _author(v['author_guid']),
                'status': ns.status,
                'summary_sv': f"Vårdplan: {ns.title or 'utan titel'} ({ns.status}), "
                              f"version {v['version']}",
                'change_reason': v['reason'],
                'superseded': v['ended'],
                'fhir': versioning.render_care_plan(ns, v['version'], v['recorded_at']),
            })
        if versions and versions[0]['change_reason'] == versioning.PRE_HISTORY_REASON:
            pre_history.append(cp.guid)
        items.append({'resource_type': 'CarePlan', 'id': cp.guid,
                      'current_status': cp.status, 'versions': versions})
    return items, pre_history


#: contract-match status -> R5 Task.status
TASK_STATUS = {'pending': 'requested', 'sent': 'received', 'acknowledged': 'received',
               'accepted': 'accepted', 'in_progress': 'in-progress',
               'completed': 'completed', 'rejected': 'rejected',
               'failed': 'failed', 'cancelled': 'cancelled'}


def dispatch_items(patient_guid):
    sr_guids = [r[0] for r in ServiceRequest.query.with_entities(ServiceRequest.guid)
                .filter(ServiceRequest.patient_guid == patient_guid).all()]
    if not sr_guids:
        return []
    matches = (ServiceRequestContractMatch.query
               .filter(ServiceRequestContractMatch.service_request_guid.in_(sr_guids))
               .order_by(ServiceRequestContractMatch.created_at.asc(),
                         ServiceRequestContractMatch.id.asc()).all())
    items = []
    for m in matches:
        receipts = (ServiceRequestReceipt.query.filter_by(contract_match_guid=m.guid)
                    .order_by(ServiceRequestReceipt.created_at.asc()).all())
        task = {
            'resourceType': 'Task',
            'id': m.guid,
            'meta': {'versionId': '1'},
            'status': TASK_STATUS.get(m.status, 'requested'),
            'businessStatus': {'text': m.status},
            'intent': 'order',
            'focus': {'reference': f'ServiceRequest/{m.service_request_guid}'},
            'for': {'reference': f'Patient/{patient_guid}'},
            'owner': {'reference': f'Organization/{m.provider_org_guid}',
                      **({'display': m.provider_name} if m.provider_name else {})},
            'authoredOn': _iso(m.created_at),
        }
        if m.updated_at:
            task['lastModified'] = _iso(m.updated_at)
        if m.contract_guid:
            task['basedOn'] = [{'reference':
                                f'https://contract.pdhc.se/fhir/Contract/{m.contract_guid}'}]
        notes = [f"Leverans {r.delivery_method}: {r.delivery_status} {_iso(r.created_at)}"
                 for r in receipts]
        if notes:
            task['note'] = [{'text': n} for n in notes]
        items.append({
            'resource_type': 'Task', 'id': m.guid, 'current_status': m.status,
            'versions': [{
                'version': 1,
                'event_time': _iso(m.sent_at),
                'recorded_at': _iso(m.created_at),
                'author': None,
                'status': m.status,
                'summary_sv': (f"Skickad till {m.provider_name or m.provider_org_guid} "
                               f"({m.status}); {len(receipts)} leverans(er)"),
                # never the receipt token: it is a bearer credential
                'deliveries': [{'method': r.delivery_method, 'status': r.delivery_status,
                                'response_received': bool(r.response_received),
                                'at': _iso(r.created_at)} for r in receipts],
                'response_at': _iso(m.response_at),
                'fhir': task,
            }],
        })
    return items


def grant_items(patient_guid):
    rows = (DataExchangeGrant.query.filter_by(patient_guid=patient_guid)
            .order_by(DataExchangeGrant.created_at.asc(), DataExchangeGrant.id.asc()).all())
    return [{
        'resource_type': 'DataExchangeGrant', 'id': r.guid,
        'current_status': 'revoked' if r.revoked else 'issued',
        'versions': [{
            'version': 1, 'event_time': _iso(r.created_at), 'recorded_at': _iso(r.created_at),
            'author': None, 'status': 'revoked' if r.revoked else 'issued',
            'summary_sv': (f"Behörighet för datautbyte ({r.grant_type}) till "
                           f"{r.provider_org_guid}, giltig till {_iso(r.expires_at)}, "
                           f"använd {r.used_count} gång(er)"),
            # type and dates only; grant_token is a credential and is never shown
            'grant': {'service_request_guid': r.service_request_guid,
                      'provider_org_guid': r.provider_org_guid,
                      'contract_guid': r.contract_guid, 'grant_type': r.grant_type,
                      'expires_at': _iso(r.expires_at), 'used_count': r.used_count,
                      'max_uses': r.max_uses, 'revoked': bool(r.revoked)},
            'fhir': None,
        }],
    } for r in rows]


def build_extract(patient_guid):
    """The extract body (contract shape). Pure of the gate."""
    sections, notes = [], []
    srs, sr_pre = service_request_items(patient_guid)
    cps, cp_pre = care_plan_items(patient_guid)
    disp = dispatch_items(patient_guid)
    grants = grant_items(patient_guid)
    for key, title, items in (
            ('service_requests', 'Beställningar', srs),
            ('care_plans', 'Vårdplaner', cps),
            ('dispatches', 'Skickat till vårdgivare', disp),
            ('data_exchange_grants', 'Behörigheter för datautbyte', grants)):
        if items:
            sections.append({'key': key, 'title_sv': title, 'count': len(items),
                             'items': items})
    if sr_pre or cp_pre:
        notes.append(f'{PRE_HISTORY_NOTE} Gäller {len(sr_pre)} beställning(ar) och '
                     f'{len(cp_pre)} vårdplan(er).')
    if disp:
        notes.append('Sändningar till vårdgivare har ingen versionshistorik; '
                     'en version per sändning med dess nuvarande status.')
    if not sections:
        notes.append('request.pdhc har inga uppgifter om patienten.')
    return {
        'schema': SCHEMA, 'service': SERVICE, 'patient_guid': patient_guid,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'complete': True, 'sections': sections, 'notes': notes,
    }


@patient_extract_bp.route('/patient-extract/<patient_guid>', methods=['GET'])
@requires_auth
def patient_extract(patient_guid):
    patient_guid = bleach.clean(patient_guid)
    if getattr(g, 'provider_pat', None) is not None:
        return _deny(None, patient_guid, 'provider_token', 403, 'person_required',
                     'an extract is taken out by a person, not a provider token')
    blob = get_current_access_blob()
    blob = blob if isinstance(blob, dict) else None
    if blob is None or blob.get('user_type') == 'service':
        return _deny(blob.get('user_guid') if blob else None, patient_guid, 'not_a_person',
                     403, 'person_required',
                     "an extract is taken out with a person's own SSO token")
    user_guid = blob.get('user_guid')
    is_su = bool(blob.get('is_su_admin'))
    if not is_su and blob.get('user_type') != 'professional':
        return _deny(user_guid, patient_guid, 'not_professional', 403, 'not_professional',
                     'extracts are for care professionals')
    gate_blob = blob if is_su else extract_blob(blob)
    if not is_su and not gate_blob['affiliations']:
        return _deny(user_guid, patient_guid, 'role_not_permitted', 403, 'forbidden',
                     'an extract is taken out by a doctor or nurse at the patient\'s unit',
                     caller_roles=sorted({a.get('role') for a in blob.get('affiliations') or []
                                          if isinstance(a, dict) and a.get('role')}))
    decision = patient_access.evaluate(gate_blob, patient_guid)
    if not decision.allowed:
        messages = {
            'patient_not_found': 'Patient not found',
            'ips_lookup_failed': 'Could not verify patient affiliation; try again shortly.',
            'patient_org_mismatch': ('Patient is not assigned to any care unit where you '
                                     'are a doctor or nurse (PDL Ch 4 §§ 1-2).'),
        }
        return _deny(user_guid, patient_guid, decision.reason, decision.status,
                     decision.code, messages[decision.reason], **decision.details)

    body = build_extract(patient_guid)
    log_event(user_guid=user_guid, action='patient_extract', resource_type='Patient',
              resource_guid=patient_guid, data_subject_guid=patient_guid,
              ip_address=request.remote_addr,
              details={'outcome': 'served',
                       'access_basis': 'su_admin' if decision.is_su else 'same_unit',
                       'counts': {s['key']: s['count'] for s in body['sections']}})
    return jsonify(body), 200

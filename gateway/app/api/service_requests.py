"""API endpoints for ServiceRequest CRUD and workflow."""

import functools

import bleach
from flask import Blueprint, jsonify, request
from app.models.service_request_models import ServiceRequest
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import service_request_service, contract_service, plan_definition_service
from app.services import patient_service
from app.services import patient_access
from app.services.audit_service import audit_read, log_event
from app.services.auth_service import get_current_user_guid, get_current_access_blob
from app.services.reform_scope import (
    caller_org_ids as _caller_org_ids,
    caller_org_names as _caller_org_names,
)

service_requests_bp = Blueprint('service_requests_api', __name__)


def sr_patient_gate(verb):
    """Every route keyed by a ServiceRequest guid reaches its PATIENT only
    through the caller's organisation (#991) — the rule in
    app/services/patient_access.py, shared with POST /ServiceRequest and the
    CarePlan routes (#981).

    Before this, all twelve guid routes — the read, matches, receipts, forms,
    and the finalize / archive / revoke / match / push WRITES — checked only
    that the caller was logged in (spärr aside, on the read).

    Innermost decorator, so @audit_read (which audits 2xx only) never records
    a refused read; the refusal is audited here, with its reason. An unknown
    guid falls through to the route, which answers its own 404.
    """
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            guid = kwargs.get('guid')
            sr = (ServiceRequest.query.filter_by(guid=bleach.clean(guid)).first()
                  if guid else None)
            if sr is not None:
                decision = patient_access.evaluate(get_current_access_blob(),
                                                   sr.patient_guid)
                patient_access.note_subject(sr.patient_guid)
                if not decision.allowed:
                    log_event(user_guid=get_current_user_guid(),
                              action=f'service_request.{verb}.denied',
                              resource_type='ServiceRequest', resource_guid=sr.guid,
                              data_subject_guid=sr.patient_guid,
                              ip_address=request.remote_addr,
                              details={'reason': decision.reason, **decision.details})
                    messages = {
                        'patient_not_found': 'Patient not found',
                        'ips_lookup_failed': ('Could not verify patient affiliation; '
                                              'try again shortly.'),
                        'patient_org_mismatch': ('Patient is not assigned to any clinic '
                                                 'in your organisations (PDL Ch 4 §§ 1-2).'),
                    }
                    return jsonify({'code': decision.code,
                                    'message': messages[decision.reason]}), decision.status
            return fn(*args, **kwargs)
        return inner
    return wrap


@service_requests_bp.route('/ServiceRequest', methods=['POST'])
@requires_auth
@requires_role('read_write')
def create():
    """Create a new draft ServiceRequest.

    PDL Ch 4 §§ 1-2 need-to-know gate (ticket #225): a non-admin
    caller may only create an SR for a patient assigned to at least
    one of their organisations. SU admins bypass the gate; every
    bypass and every denial is audited.
    """
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'code': 'bad_request', 'message': 'Request body required'}), 400

    patient_guid = payload.get('patient_guid')
    plan_definition_guid = payload.get('plan_definition_guid')
    if not patient_guid or not plan_definition_guid:
        return jsonify({'code': 'bad_request',
                        'message': 'patient_guid and plan_definition_guid are required'}), 400
    patient_guid = bleach.clean(patient_guid)

    blob = get_current_access_blob()
    is_su = bool(blob.get('is_su_admin', False)) if blob else False
    # M0 #419: Zone-1 scope from affiliations[] (dual-read fallback), and the
    # guid->name map from the same affiliation entries (fills the legacy
    # organization_names gap).
    caller_org_ids_list = _caller_org_ids(blob) if blob else []
    caller_org_names_map = _caller_org_names(blob) if blob else {}
    caller_org_ids = set(caller_org_ids_list)
    caller_user_guid = get_current_user_guid()

    # ---- explicit requesting-org choice (#226) ---------------------
    # Lag (2022:913) requires the *acting* affiliation to be explicit
    # for the chain-of-custody log: a multi-org user must say which of
    # their orgs is making the request. Single-org users get auto-fill.
    requesting_org_guid_raw = payload.get('requesting_org_guid')
    requesting_org_guid = (bleach.clean(requesting_org_guid_raw)
                           if requesting_org_guid_raw else None)
    org_choice_mode = 'caller_specified'
    if requesting_org_guid:
        # Validate the chosen org is one of the caller's affiliations.
        # SU admins are exempt (organization_ids is typically empty
        # for them but they may legitimately act on behalf of any org).
        if not is_su and requesting_org_guid not in caller_org_ids:
            log_event(
                user_guid=caller_user_guid,
                action='service_request.create.denied',
                resource_type='ServiceRequest',
                data_subject_guid=patient_guid,
                ip_address=request.remote_addr,
                details={
                    'reason': 'requesting_org_not_in_caller_orgs',
                    'requesting_org_guid': requesting_org_guid,
                    'caller_org_ids': sorted(caller_org_ids),
                    'plan_definition_guid': plan_definition_guid,
                },
            )
            return jsonify({
                'code': 'forbidden',
                'message': ('requesting_org_guid is not one of your '
                            'organisations.'),
            }), 403
    elif not is_su:
        # Non-admin: caller must pick when they have multiple
        # affiliations. Single-org callers get auto-fill.
        if len(caller_org_ids_list) > 1:
            log_event(
                user_guid=caller_user_guid,
                action='service_request.create.denied',
                resource_type='ServiceRequest',
                data_subject_guid=patient_guid,
                ip_address=request.remote_addr,
                details={
                    'reason': 'requesting_org_required',
                    'caller_org_ids': sorted(caller_org_ids),
                    'plan_definition_guid': plan_definition_guid,
                },
            )
            return jsonify({
                'code': 'bad_request',
                'message': ('requesting_org_guid is required when you '
                            'belong to more than one organisation '
                            '(Lag 2022:913 chain-of-custody).'),
            }), 400
        if caller_org_ids_list:
            requesting_org_guid = caller_org_ids_list[0]
            org_choice_mode = 'auto_single_org'

    # ---- patient-org authorisation gate ---------------------------
    # #981: the decision is app/services/patient_access.py — ONE rule shared
    # with the CarePlan routes. This route keeps its own audit actions and
    # messages; the details are the same fields it always wrote.
    decision = patient_access.evaluate(blob, patient_guid)
    if not decision.allowed:
        log_event(
            user_guid=caller_user_guid,
            action='service_request.create.denied',
            resource_type='ServiceRequest',
            data_subject_guid=patient_guid,
            ip_address=request.remote_addr,
            details={'reason': decision.reason,
                     'plan_definition_guid': plan_definition_guid,
                     **decision.details},
        )
        messages = {
            'patient_not_found': f'Patient {patient_guid} not found',
            'ips_lookup_failed': ('Could not verify patient affiliation; '
                                  'try again shortly.'),
            'patient_org_mismatch': ('Patient is not assigned to any clinic in '
                                     'your organisations; create denied per '
                                     'PDL Ch 4 §§ 1-2.'),
        }
        return jsonify({'code': decision.code,
                        'message': messages[decision.reason]}), decision.status
    if decision.is_su:
        # SU admin bypass — auditable.
        log_event(
            user_guid=caller_user_guid,
            action='service_request.create.admin_bypass',
            resource_type='ServiceRequest',
            data_subject_guid=patient_guid,
            ip_address=request.remote_addr,
            details={
                'plan_definition_guid': plan_definition_guid,
                'reason': 'caller_is_su_admin',
                'requesting_org_guid': requesting_org_guid,
                'org_choice_mode': ('caller_specified' if requesting_org_guid
                                    else 'su_admin_unspecified'),
            },
        )
    # ---- end of authorisation gate --------------------------------

    org_guid = requesting_org_guid
    org_name = caller_org_names_map.get(org_guid)  # M0 #419: paired guid->name
    user_name = blob.get('display_name', blob.get('email', '')) if blob else None

    log_event(
        user_guid=caller_user_guid,
        action='service_request.create.requested',
        resource_type='ServiceRequest',
        data_subject_guid=patient_guid,
        ip_address=request.remote_addr,
        details={
            'plan_definition_guid': plan_definition_guid,
            'requesting_org_guid': org_guid,
            'org_choice_mode': org_choice_mode,
            'caller_org_ids_count': len(caller_org_ids_list),
        },
    )

    data, status = service_request_service.create_service_request(
        patient_guid=patient_guid,
        plan_definition_guid=bleach.clean(plan_definition_guid),
        user_guid=caller_user_guid,
        org_guid=org_guid,
        user_name=user_name,
        org_name=org_name,
        contract_guid=payload.get('contract_guid'),
        notes=payload.get('notes'),
        ip_address=request.remote_addr,
        # #1054 JournalBestallning fields
        journal={k: payload[k] for k in ('reason', 'encounter_guid', 'encounter', 'replaces',
                                         'supporting_info', 'supportingInfo') if k in payload},
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest', methods=['GET'])
@requires_auth
@audit_read('service_request.list', resource_type='ServiceRequest')
def list_all():
    """List ServiceRequests (org-filtered for non-SU)."""
    blob = get_current_access_blob()
    is_su = blob.get('is_su_admin', False) if blob else False
    # Every unit, not the first (main rule 2026-11-13).
    org_guids = _caller_org_ids(blob) if blob else []  # M0 #419
    if not is_su and not org_guids:
        # #991: the service filters `if not is_su_admin and org_guid`, so a
        # non-SU caller with NO organisation skipped the filter and was shown
        # EVERY ServiceRequest. Absence of an affiliation must narrow, never
        # widen. Refused here, by name, and audited.
        log_event(user_guid=get_current_user_guid(), action='service_request.list.denied',
                  resource_type='ServiceRequest', ip_address=request.remote_addr,
                  details={'reason': 'caller_has_no_organisation'})
        return jsonify({'code': 'forbidden',
                        'message': 'Your account has no organisation; nothing to list.'}), 403

    data, status = service_request_service.list_service_requests(
        user_guid=get_current_user_guid(),
        org_guids=org_guids,
        is_su_admin=is_su,
        status_filter=request.args.get('status'),
        page=int(request.args.get('page', 1)),
        # Cap per_page (mirrors the provider feed) so a caller can't force a
        # full-table load + one IPS /blocks/check per patient.
        per_page=min(int(request.args.get('per_page', 50)), 200),
    )
    return jsonify(data), status


def supporting_info_matches(refs, wanted):
    """#1057: does any supportingInfo reference in `refs` name `wanted`?

    `wanted` is a type (`ClinicalImpression`), a resource
    (`ClinicalImpression/<id>`) or one version of it
    (`ClinicalImpression/<id>/_history/<n>`). A reference matches when it IS
    `wanted` or continues it after a `/`, so `ClinicalImpression/<id>` finds
    every version of that decision and never `ClinicalImpression/<id>9`.
    Pure."""
    wanted = (wanted or '').strip().rstrip('/')
    if not wanted:
        return False
    for ref in refs or []:
        if isinstance(ref, dict):
            ref = (ref.get('reference') or {})
            ref = ref.get('reference') if isinstance(ref, dict) else ref
        if isinstance(ref, str) and (ref == wanted or ref.startswith(wanted + '/')):
            return True
    return False


@service_requests_bp.route('/patients/<patient_guid>/ServiceRequest', methods=['GET'])
@requires_auth
@audit_read('service_request.by_supporting_info', resource_type='ServiceRequest')
def patient_orders_citing(patient_guid):
    """#1057 (record.pdhc stage 5): ONE patient's orders that cite a resource
    in supportingInfo — "which orders were made from this decision".

        GET /api/v1/patients/<patient guid>/ServiceRequest
            ?supporting-info=ClinicalImpression[/<id>[/_history/<n>]]

    record.pdhc reads the decision -> order link FROM the stored orders (the
    order carries supportingInfo -> the decision, #1054) instead of keeping a
    second copy. Every status is returned, drafts and revoked included: a
    revoked order made from a decision is part of its trace.

    Gate: the same patient rule as every ServiceRequest route
    (app/services/patient_access.py, #981/#991) — an SU, or a caller whose
    unit the patient is listed at — then spärr (ips /blocks/check) per order
    like the list. A refusal is audited with its reason; a served read by
    @audit_read. `supporting-info` is REQUIRED: this is not a second
    unscoped list of the patient's orders."""
    patient_guid = bleach.clean(patient_guid)
    wanted = (request.args.get('supporting-info') or '').strip()
    if not wanted:
        return jsonify({'code': 'bad_request',
                        'message': 'supporting-info is required'}), 400
    blob = get_current_access_blob()
    decision = patient_access.evaluate(blob, patient_guid)
    patient_access.note_subject(patient_guid)
    if not decision.allowed:
        log_event(user_guid=get_current_user_guid(),
                  action='service_request.by_supporting_info.denied',
                  resource_type='ServiceRequest', data_subject_guid=patient_guid,
                  ip_address=request.remote_addr,
                  details={'reason': decision.reason, **decision.details})
        return jsonify({'code': decision.code, 'message': decision.reason}), decision.status
    rows = (ServiceRequest.query.filter_by(patient_guid=patient_guid)
            .order_by(ServiceRequest.created_at.asc()).all())
    rows = [sr for sr in rows if supporting_info_matches(sr.supporting_info, wanted)]
    if rows:
        from app.services import ips_client
        rows = ips_client.filter_visible_srs(rows)
    return jsonify({'items': [sr.to_dict() for sr in rows], 'total': len(rows)}), 200


@service_requests_bp.route('/ServiceRequest/<guid>', methods=['GET'])
@requires_auth
@audit_read('service_request.read', resource_type='ServiceRequest', guid_arg='guid')
@sr_patient_gate('read')
def get_one(guid):
    """Get a single ServiceRequest."""
    data, status = service_request_service.get_service_request(bleach.clean(guid))
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/snapshot', methods=['PUT'])
@requires_auth
@requires_role('read_write')
@sr_patient_gate('snapshot')
def update_snapshot(guid):
    """Update the PlanDefinition snapshot (draft only)."""
    payload = request.get_json(silent=True)
    if not payload or 'plan_definition_snapshot' not in payload:
        return jsonify({'code': 'bad_request',
                        'message': 'plan_definition_snapshot is required'}), 400

    data, status = service_request_service.update_plan_definition_snapshot(
        guid=bleach.clean(guid),
        edited_snapshot=payload['plan_definition_snapshot'],
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/finalize', methods=['POST'])
@requires_auth
@requires_role('read_write')
@sr_patient_gate('finalize')
def finalize(guid):
    """Finalize a draft ServiceRequest (build FHIR, set active)."""
    data, status = service_request_service.finalize_service_request(
        guid=bleach.clean(guid),
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/archive', methods=['POST'])
@requires_auth
@requires_role('read_write')
@sr_patient_gate('archive')
def archive(guid):
    """Archive a ServiceRequest."""
    data, status = service_request_service.archive_service_request(
        guid=bleach.clean(guid),
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/revoke', methods=['POST'])
@requires_auth
@requires_role('read_write')
@sr_patient_gate('revoke')
def revoke(guid):
    """Revoke (makulera) a ServiceRequest. Body `{"reason": "..."}` (#1054),
    required for a journal order."""
    payload = request.get_json(silent=True) or {}
    reason = payload.get('reason') if isinstance(payload, dict) else None
    data, status = service_request_service.revoke_service_request(
        guid=bleach.clean(guid),
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
        reason=bleach.clean(str(reason)) if reason else None,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>', methods=['PATCH'])
@requires_auth
@requires_role('read_write')
@sr_patient_gate('patch')
def patch(guid):
    """#1054: edit a draft, or append a note to a sent order. Anything else
    on a sent order is 409 service_request_locked."""
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        for k in ('note', 'notes'):
            if isinstance(payload.get(k), str):
                payload[k] = bleach.clean(payload[k])
    data, status = service_request_service.patch_service_request(
        guid=bleach.clean(guid), payload=payload,
        user_guid=get_current_user_guid(), ip_address=request.remote_addr)
    return jsonify(data), status


def _visible_sr(guid):
    sr = ServiceRequest.query.filter_by(guid=bleach.clean(guid)).first()
    if sr is None:
        return None
    from app.services import ips_client
    if not ips_client.is_sr_visible(sr):  # spärr, as GET /ServiceRequest/<guid>
        return None
    return sr


def _fhir_not_found(msg):
    return jsonify({'resourceType': 'OperationOutcome', 'issue': [{
        'severity': 'error', 'code': 'not-found', 'diagnostics': msg}]}), 404


@service_requests_bp.route('/ServiceRequest/<guid>/_history', methods=['GET'])
@requires_auth
@audit_read('service_request.history.read', resource_type='ServiceRequest', guid_arg='guid')
@sr_patient_gate('history')
def history(guid):
    """#1054 FHIR history-instance: every version, newest first (Bundle
    type history)."""
    from app.services import versioning
    sr = _visible_sr(guid)
    if sr is None:
        return _fhir_not_found('ServiceRequest not found')
    base = request.url_root.rstrip('/') + '/api/v1/ServiceRequest'
    entries = []
    for v in reversed(versioning.sr_versions(sr)):
        res = versioning.render_sr(v['ns'], v['fhir'], v['version'], v['recorded_at'])
        entries.append({
            'fullUrl': f"{base}/{sr.guid}",
            'resource': res,
            'request': {'method': 'POST' if v['version'] == 1 else 'PUT',
                        'url': f"ServiceRequest/{sr.guid}" if v['version'] > 1
                        else 'ServiceRequest'},
            'response': {'status': '201 Created' if v['version'] == 1 else '200 OK',
                         'etag': f'W/"{v["version"]}"',
                         **({'lastModified': v['recorded_at']} if v['recorded_at'] else {})},
        })
    return jsonify({'resourceType': 'Bundle', 'type': 'history',
                    'total': len(entries), 'entry': entries}), 200


@service_requests_bp.route('/ServiceRequest/<guid>/_history/<vid>', methods=['GET'])
@requires_auth
@audit_read('service_request.vread', resource_type='ServiceRequest', guid_arg='guid')
@sr_patient_gate('vread')
def vread(guid, vid):
    """#1054 FHIR vread: ONE version of the order, as it was."""
    from app.services import versioning
    sr = _visible_sr(guid)
    if sr is None:
        return _fhir_not_found('ServiceRequest not found')
    for v in versioning.sr_versions(sr):
        if str(v['version']) == str(vid).strip():
            res = versioning.render_sr(v['ns'], v['fhir'], v['version'], v['recorded_at'])
            resp = jsonify(res)
            resp.headers['ETag'] = f'W/"{v["version"]}"'
            return resp, 200
    return _fhir_not_found(f'ServiceRequest {sr.guid} has no version {vid}')


@service_requests_bp.route('/ServiceRequest/<guid>/matches', methods=['GET'])
@requires_auth
@audit_read('service_request.matches.list', resource_type='ServiceRequest', guid_arg='guid')
@sr_patient_gate('matches')
def list_matches(guid):
    """List contract matches for a ServiceRequest."""
    from app.services.match_service import list_matches_for_request
    data, status = list_matches_for_request(bleach.clean(guid))
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/match', methods=['POST'])
@requires_auth
@requires_role('read_write')
@sr_patient_gate('match')
def find_matches(guid):
    """Find matching contracts for a ServiceRequest."""
    from app.services.match_service import find_and_create_matches
    data, status = find_and_create_matches(
        service_request_guid=bleach.clean(guid),
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/push', methods=['POST'])
@requires_auth
@requires_role('read_write')
@sr_patient_gate('push')
def push_all(guid):
    """Push ServiceRequest to all pending matched providers."""
    from app.services.push_service import push_all_matches
    data, status = push_all_matches(
        service_request_guid=bleach.clean(guid),
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/push/<match_guid>', methods=['POST'])
@requires_auth
@requires_role('read_write')
@sr_patient_gate('push')
def push_one(guid, match_guid):
    """Push ServiceRequest to a single matched provider."""
    from app.services.push_service import push_to_provider
    data, status = push_to_provider(
        match_guid=bleach.clean(match_guid),
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/receipts', methods=['GET'])
@requires_auth
@audit_read('service_request.receipts.list', resource_type='ServiceRequest', guid_arg='guid')
@sr_patient_gate('receipts')
def list_receipts(guid):
    """List delivery receipts for a ServiceRequest."""
    from app.services.push_service import list_receipts_for_request
    data, status = list_receipts_for_request(bleach.clean(guid))
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/receipt/<receipt_token>', methods=['GET'])
@requires_auth
@audit_read('service_request.receipt.read', resource_type='ServiceRequestReceipt', guid_arg='receipt_token')
def get_receipt(receipt_token):
    """Look up a delivery receipt by token."""
    from app.services.push_service import get_receipt as get_receipt_fn
    data, status = get_receipt_fn(bleach.clean(receipt_token))
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/receipt/<receipt_token>/respond', methods=['POST'])
def provider_respond(receipt_token):
    """Provider webhook: respond to a pushed ServiceRequest.

    No auth required — the receipt_token acts as a bearer token.
    Providers call this with their acceptance/rejection.
    """
    from app.services.push_service import handle_provider_response
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'code': 'bad_request', 'message': 'Request body required'}), 400

    data, status = handle_provider_response(
        receipt_token=bleach.clean(receipt_token),
        response_payload=payload,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/auto-archive', methods=['POST'])
@requires_auth
@requires_role('admin')
def trigger_auto_archive():
    """Manually trigger auto-archive of expired ServiceRequests."""
    count = service_request_service.check_auto_archive()
    return jsonify({'archived': count}), 200


# ---------------------------------------------------------------------------
# Form attachment endpoints
# ---------------------------------------------------------------------------

@service_requests_bp.route('/ServiceRequest/<guid>/forms', methods=['GET'])
@requires_auth
@audit_read('service_request.forms.list', resource_type='ServiceRequest', guid_arg='guid')
@sr_patient_gate('forms')
def list_forms(guid):
    """List attached forms for a ServiceRequest."""
    data, status = service_request_service.list_forms_for_request(bleach.clean(guid))
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/forms', methods=['POST'])
@requires_auth
@requires_role('read_write')
@sr_patient_gate('forms.add')
def add_form(guid):
    """Attach a form to a draft ServiceRequest."""
    payload = request.get_json(silent=True)
    # #1043: a Questionnaire may be named by canonical url (+ version) instead
    # of a plan.pdhc form guid.
    if payload and payload.get('questionnaire_url') and not payload.get('form_guid'):
        from app.services import questionnaire_service
        data, status = questionnaire_service.attach_by_canonical(
            sr_guid=bleach.clean(guid),
            url=str(payload['questionnaire_url']),
            version=(str(payload['questionnaire_version'])
                     if payload.get('questionnaire_version') else None),
            sort_order=int(payload.get('sort_order', 0)),
            user_guid=get_current_user_guid(),
            ip_address=request.remote_addr,
        )
        return jsonify(data), status
    if not payload or not payload.get('form_guid'):
        return jsonify({'code': 'bad_request',
                        'message': 'form_guid or questionnaire_url is required'}), 400

    data, status = service_request_service.add_form_to_request(
        sr_guid=bleach.clean(guid),
        form_guid=bleach.clean(payload['form_guid']),
        form_version=payload.get('form_version'),
        sort_order=int(payload.get('sort_order', 0)),
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/forms/<form_sr_guid>', methods=['DELETE'])
@requires_auth
@requires_role('read_write')
def remove_form(guid, form_sr_guid):
    """Remove a form from a draft ServiceRequest."""
    data, status = service_request_service.remove_form_from_request(
        sr_guid=bleach.clean(guid),
        form_sr_guid=bleach.clean(form_sr_guid),
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/forms/reorder', methods=['POST'])
@requires_auth
@requires_role('read_write')
def reorder_forms(guid):
    """Bulk reorder attached forms."""
    payload = request.get_json(silent=True)
    if not payload or not isinstance(payload.get('ordered_guids'), list):
        return jsonify({'code': 'bad_request', 'message': 'ordered_guids list is required'}), 400

    data, status = service_request_service.reorder_forms(
        sr_guid=bleach.clean(guid),
        ordered_guids=[bleach.clean(g) for g in payload['ordered_guids']],
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


# ---------------------------------------------------------------------------
# Form catalogue proxy
# ---------------------------------------------------------------------------

@service_requests_bp.route('/Form', methods=['GET'])
@requires_auth
def proxy_forms():
    """Proxy form catalogue from plan.pdhc."""
    from app.services import form_service
    data, status = form_service.list_forms(params=dict(request.args))
    return jsonify(data), status


@service_requests_bp.route('/Form/<guid>', methods=['GET'])
@requires_auth
def proxy_form_detail(guid):
    """Proxy single form detail from plan.pdhc."""
    from app.services import form_service
    data, status = form_service.get_form(bleach.clean(guid))
    return jsonify(data), status


@service_requests_bp.route('/PlanDefinition', methods=['GET'])
@requires_auth
def proxy_plan_definitions():
    """Proxy PlanDefinition list from plan.pdhc."""
    data, status = plan_definition_service.list_plan_definitions(
        params=dict(request.args)
    )
    return jsonify(data), status


@service_requests_bp.route('/Contract', methods=['GET'])
@requires_auth
def proxy_contracts():
    """Proxy Contract list from contract.pdhc."""
    data, status = contract_service.list_contracts()
    return jsonify(data), status


# ---------------------------------------------------------------------------
# #1043: Questionnaire registry (canonical url + version)
# ---------------------------------------------------------------------------

@service_requests_bp.route('/Questionnaire', methods=['GET'])
@requires_auth
def list_questionnaires():
    """Questionnaires a ServiceRequest can reference by canonical url.
    `?url=<canonical>[|version]` returns that one with its JSON."""
    from app.services import questionnaire_service
    url = request.args.get('url')
    if url:
        row = questionnaire_service.resolve(url, request.args.get('version'))
        if row is None:
            return jsonify({'code': 'questionnaire_not_found',
                            'message': 'No such Questionnaire is stored'}), 404
        return jsonify(row.to_dict(with_resource=True)), 200
    items = questionnaire_service.list_questionnaires()
    return jsonify({'items': items, 'total': len(items)}), 200


@service_requests_bp.route('/Questionnaire', methods=['POST'])
@requires_auth
@requires_role('admin')
def import_questionnaire():
    """Store a FHIR Questionnaire (admin). Same as `flask questionnaire import`."""
    from app.services import questionnaire_service
    try:
        row, created = questionnaire_service.import_questionnaire(
            request.get_json(silent=True), created_by=get_current_user_guid())
    except questionnaire_service.QuestionnaireInvalid as e:
        status = 409 if e.code == 'questionnaire_version_conflict' else 422
        return jsonify({'code': e.code, 'message': str(e)}), status
    return jsonify(row.to_dict()), (201 if created else 200)

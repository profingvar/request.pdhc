"""API endpoints for ServiceRequest CRUD and workflow."""

import bleach
from flask import Blueprint, jsonify, request
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import service_request_service, contract_service, plan_definition_service
from app.services import patient_service
from app.services.audit_service import audit_read, log_event
from app.services.auth_service import get_current_user_guid, get_current_access_blob
from app.services.reform_scope import (
    caller_org_ids as _caller_org_ids,
    caller_org_names as _caller_org_names,
)

service_requests_bp = Blueprint('service_requests_api', __name__)


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
    if not is_su:
        patient_clinic_guids, ips_status = \
            patient_service.get_patient_clinic_guids(patient_guid)
        if ips_status == 404:
            log_event(
                user_guid=caller_user_guid,
                action='service_request.create.denied',
                resource_type='ServiceRequest',
                data_subject_guid=patient_guid,
                ip_address=request.remote_addr,
                details={
                    'reason': 'patient_not_found',
                    'plan_definition_guid': plan_definition_guid,
                    'caller_org_ids': sorted(caller_org_ids),
                },
            )
            return jsonify({'code': 'not_found',
                            'message': f'Patient {patient_guid} not found'}), 404
        if ips_status >= 500:
            # Upstream IPS failure — fail closed (do NOT create the SR
            # without a valid affiliation check). Audit + 502.
            log_event(
                user_guid=caller_user_guid,
                action='service_request.create.denied',
                resource_type='ServiceRequest',
                data_subject_guid=patient_guid,
                ip_address=request.remote_addr,
                details={
                    'reason': 'ips_lookup_failed',
                    'ips_status': ips_status,
                    'plan_definition_guid': plan_definition_guid,
                },
            )
            return jsonify({'code': 'upstream_error',
                            'message': 'Could not verify patient affiliation; '
                                       'try again shortly.'}), 502
        if not (caller_org_ids & set(patient_clinic_guids)):
            log_event(
                user_guid=caller_user_guid,
                action='service_request.create.denied',
                resource_type='ServiceRequest',
                data_subject_guid=patient_guid,
                ip_address=request.remote_addr,
                details={
                    'reason': 'patient_org_mismatch',
                    'plan_definition_guid': plan_definition_guid,
                    'caller_org_ids': sorted(caller_org_ids),
                    'patient_clinic_guids': sorted(patient_clinic_guids),
                },
            )
            return jsonify({
                'code': 'forbidden',
                'message': ('Patient is not assigned to any clinic in your '
                            'organisations; create denied per PDL Ch 4 §§ 1-2.'),
            }), 403
    else:
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
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest', methods=['GET'])
@requires_auth
@audit_read('service_request.list', resource_type='ServiceRequest')
def list_all():
    """List ServiceRequests (org-filtered for non-SU)."""
    blob = get_current_access_blob()
    is_su = blob.get('is_su_admin', False) if blob else False
    org_guid = (_caller_org_ids(blob) or [None])[0] if blob else None  # M0 #419

    data, status = service_request_service.list_service_requests(
        user_guid=get_current_user_guid(),
        org_guid=org_guid,
        is_su_admin=is_su,
        status_filter=request.args.get('status'),
        page=int(request.args.get('page', 1)),
        per_page=int(request.args.get('per_page', 50)),
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>', methods=['GET'])
@requires_auth
@audit_read('service_request.read', resource_type='ServiceRequest', guid_arg='guid')
def get_one(guid):
    """Get a single ServiceRequest."""
    data, status = service_request_service.get_service_request(bleach.clean(guid))
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/snapshot', methods=['PUT'])
@requires_auth
@requires_role('read_write')
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
def revoke(guid):
    """Revoke a ServiceRequest."""
    data, status = service_request_service.revoke_service_request(
        guid=bleach.clean(guid),
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/matches', methods=['GET'])
@requires_auth
@audit_read('service_request.matches.list', resource_type='ServiceRequest', guid_arg='guid')
def list_matches(guid):
    """List contract matches for a ServiceRequest."""
    from app.services.match_service import list_matches_for_request
    data, status = list_matches_for_request(bleach.clean(guid))
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/match', methods=['POST'])
@requires_auth
@requires_role('read_write')
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
def list_forms(guid):
    """List attached forms for a ServiceRequest."""
    data, status = service_request_service.list_forms_for_request(bleach.clean(guid))
    return jsonify(data), status


@service_requests_bp.route('/ServiceRequest/<guid>/forms', methods=['POST'])
@requires_auth
@requires_role('read_write')
def add_form(guid):
    """Attach a form to a draft ServiceRequest."""
    payload = request.get_json(silent=True)
    if not payload or not payload.get('form_guid'):
        return jsonify({'code': 'bad_request', 'message': 'form_guid is required'}), 400

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

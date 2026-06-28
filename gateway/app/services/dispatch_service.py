import requests
from flask import current_app
from app import db
from app.models.dispatch_models import DispatchRequest, DispatchReceipt
from app.services.auth_service import get_upstream_token
from app.services.audit_service import log_event
from app.services.ips_consent_client import (
    consent_covers_dispatch,
    get_active_consents,
)


def _headers():
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    token = get_upstream_token()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def create_dispatch(plan_definition_guid=None, provider_guid=None,
                    assigned_user_guid=None,
                    notes=None, idempotency_key=None, user_guid=None, ip_address=None,
                    patient_guid=None, destination_caregiver_guid=None,
                    payload_concept_guids=None,
                    # #318 (2026-06-28): back-compat alias kwarg.
                    # `careplan_guid` was the pre-#310 name for what
                    # was always a PlanDefinition guid. Accept the
                    # alias for one release; drop after no caller
                    # passes it.
                    careplan_guid=None):
    if plan_definition_guid is None:
        plan_definition_guid = careplan_guid
    """Create and submit a dispatch request.

    Ticket #229 (Request PDL #5): when the caller identifies the
    patient + destination caregiver, validate cohesive-care consent
    (Lag 2022:913 § 5) against ips.pdhc before forwarding upstream.
    If the destination caregiver does not hold a valid consent from
    the patient — or the consent is concept-narrowed and a payload
    concept falls outside — refuse with 403 and audit the refusal.

    ``payload_concept_guids`` (optional) is the list of concept guids
    the dispatch is requesting data on; when ``None`` the concept
    check is skipped and caregiver-level consent alone suffices.

    Returns:
        tuple: (result_dict, status_code)
    """
    # PDL gate before idempotency: a consent-failing dispatch must not
    # be able to "succeed" by replaying a prior idempotency key.
    if patient_guid and destination_caregiver_guid:
        consents = get_active_consents(patient_guid)
        ok, reason = consent_covers_dispatch(
            consents,
            destination_caregiver_guid=destination_caregiver_guid,
            payload_concept_guids=payload_concept_guids,
        )
        if not ok:
            log_event(
                user_guid=user_guid,
                action='careplan.dispatch.refused',
                resource_type='CarePlan',
                resource_guid=plan_definition_guid,
                details={
                    'reason': reason,
                    'provider_guid': provider_guid,
                    'patient_guid': patient_guid,
                    'destination_caregiver_guid': destination_caregiver_guid,
                    'payload_concept_guids': list(payload_concept_guids or []),
                    'pdl_basis': 'Lag (2022:913) §5',
                },
                ip_address=ip_address,
                data_subject_guid=patient_guid,
            )
            return {
                'code': 'consent_missing',
                'message': (
                    'Dispatch refused: destination caregiver has no '
                    'valid consent (Lag 2022:913 §5).'
                ),
                'reason': reason,
                'destination_caregiver_guid': destination_caregiver_guid,
            }, 403
    elif patient_guid or destination_caregiver_guid:
        # Half a check is no check. Log a warning so deployments adopt
        # the new fields together; don't refuse — soft-rollout posture.
        current_app.logger.warning(
            'dispatch consent check skipped: supply both patient_guid '
            'and destination_caregiver_guid (got patient=%s caregiver=%s)',
            bool(patient_guid), bool(destination_caregiver_guid),
        )

    # Check idempotency — return existing if duplicate
    existing = DispatchRequest.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        receipt = DispatchReceipt.query.filter_by(dispatch_request_guid=existing.guid).first()
        return {
            'message': 'Duplicate dispatch — returning existing receipt',
            'dispatch_request': existing.to_dict(),
            'receipt': receipt.to_dict() if receipt else None,
        }, 200

    # Create local dispatch request record
    dispatch_req = DispatchRequest(
        plan_definition_guid=plan_definition_guid,
        provider_guid=provider_guid,
        assigned_user_guid=assigned_user_guid,
        dispatch_notes=notes,
        status='pending',
        idempotency_key=idempotency_key,
    )
    db.session.add(dispatch_req)
    db.session.flush()

    # Submit to upstream. #318: canonical URL is
    # /api/v1/PlanDefinition/<guid>/dispatch; the legacy
    # /api/v1/CarePlan/<guid>/dispatch still works on plan.pdhc as a
    # back-compat alias for one release cycle.
    plan_base = current_app.config['PLAN_BASE_URL'].rstrip('/')
    upstream_url = f"{plan_base}/api/v1/PlanDefinition/{plan_definition_guid}/dispatch"

    upstream_payload = {
        'provider_guid': provider_guid,
        'assigned_user_guid': assigned_user_guid,
        'notes': notes,
    }

    try:
        resp = requests.post(upstream_url, headers=_headers(), json=upstream_payload, timeout=15)

        if resp.status_code in (200, 201):
            dispatch_req.status = 'submitted'
            response_data = resp.json()
            receipt = DispatchReceipt(
                dispatch_request_guid=dispatch_req.guid,
                status='accepted',
                response_payload=response_data,
            )
        elif resp.status_code == 404:
            dispatch_req.status = 'failed'
            receipt = DispatchReceipt(
                dispatch_request_guid=dispatch_req.guid,
                status='error',
                response_payload={'error': 'CarePlan or provider not found upstream'},
            )
        else:
            dispatch_req.status = 'failed'
            receipt = DispatchReceipt(
                dispatch_request_guid=dispatch_req.guid,
                status='error',
                response_payload={'error': f'Upstream returned {resp.status_code}', 'body': resp.text[:500]},
            )
    except requests.RequestException as e:
        dispatch_req.status = 'failed'
        receipt = DispatchReceipt(
            dispatch_request_guid=dispatch_req.guid,
            status='error',
            response_payload={'error': f'Upstream connection failed: {str(e)}'},
        )

    db.session.add(receipt)
    db.session.commit()

    # Audit
    log_event(
        user_guid=user_guid,
        action='careplan.dispatch',
        resource_type='CarePlan',
        resource_guid=plan_definition_guid,
        details={
            'provider_guid': provider_guid,
            'dispatch_guid': dispatch_req.guid,
            'receipt_token': receipt.receipt_token,
            'status': receipt.status,
        },
        ip_address=ip_address,
    )

    status_code = 201 if receipt.status == 'accepted' else 502
    return {
        'dispatch_request': dispatch_req.to_dict(),
        'receipt': receipt.to_dict(),
    }, status_code


def get_dispatch_status(receipt_token):
    """Look up a dispatch receipt by token.

    Returns:
        tuple: (result_dict, status_code)
    """
    receipt = DispatchReceipt.query.filter_by(receipt_token=receipt_token).first()
    if not receipt:
        return {'code': 'not_found', 'message': 'Dispatch receipt not found'}, 404

    dispatch_req = DispatchRequest.query.filter_by(guid=receipt.dispatch_request_guid).first()
    return {
        'dispatch_request': dispatch_req.to_dict() if dispatch_req else None,
        'receipt': receipt.to_dict(),
    }, 200

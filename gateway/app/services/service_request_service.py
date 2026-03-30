"""Core ServiceRequest CRUD and workflow orchestration."""

from datetime import datetime, timezone
from app import db
from app.models.service_request_models import ServiceRequest, ServiceRequestContractMatch, ServiceRequestForm
from app.services import patient_service, plan_definition_service, form_service
from app.services.fhir_builder_service import build_service_request_resource, build_patient_excerpt
from app.services.audit_service import log_event


def create_service_request(patient_guid, plan_definition_guid, user_guid, org_guid=None,
                           user_name=None, org_name=None,
                           contract_guid=None, notes=None, ip_address=None):
    """Create a draft ServiceRequest by fetching patient + PlanDefinition data.

    Returns:
        tuple: (result_dict, status_code)
    """
    # Fetch patient from IPS
    patient_data, patient_status = patient_service.get_patient(patient_guid)
    if patient_status != 200:
        return {'code': 'patient_error', 'message': f'Could not fetch patient: {patient_data}'}, patient_status

    # Fetch PlanDefinition from Plan
    plandef_data, plandef_status = plan_definition_service.get_plan_definition(plan_definition_guid)
    if plandef_status != 200:
        return {'code': 'plandef_error', 'message': f'Could not fetch PlanDefinition: {plandef_data}'}, plandef_status

    patient_excerpt = build_patient_excerpt(patient_data)

    sr = ServiceRequest(
        status='draft',
        patient_guid=patient_guid,
        patient_excerpt=patient_excerpt,
        plan_definition_guid=plan_definition_guid,
        plan_definition_snapshot=plandef_data,
        contract_guid=contract_guid,
        requester_user_guid=user_guid,
        requester_user_name=user_name,
        requester_org_guid=org_guid,
        requester_org_name=org_name,
        notes=notes,
    )
    db.session.add(sr)
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.create',
        resource_type='ServiceRequest',
        resource_guid=sr.guid,
        details={'patient_guid': patient_guid, 'plan_definition_guid': plan_definition_guid},
        ip_address=ip_address,
    )

    return sr.to_dict(), 201


def get_service_request(guid):
    """Get a single ServiceRequest by GUID."""
    sr = ServiceRequest.query.filter_by(guid=guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    return sr.to_dict(), 200


def list_service_requests(user_guid=None, org_guid=None, is_su_admin=False,
                          status_filter=None, include_archived=False, page=1, per_page=50):
    """List ServiceRequests, filtered by organisation for non-SU users."""
    query = ServiceRequest.query

    if not is_su_admin and org_guid:
        query = query.filter_by(requester_org_guid=org_guid)

    if status_filter:
        query = query.filter_by(status=status_filter)
    elif not include_archived:
        query = query.filter(ServiceRequest.status.notin_(['archived', 'revoked']))

    query = query.order_by(ServiceRequest.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        'items': [sr.to_dict() for sr in items],
        'total': total,
        'page': page,
        'per_page': per_page,
    }, 200


def update_plan_definition_snapshot(guid, edited_snapshot, user_guid=None, ip_address=None):
    """Update the editable PlanDefinition snapshot. Only allowed in draft status."""
    sr = ServiceRequest.query.filter_by(guid=guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status != 'draft':
        return {'code': 'invalid_status', 'message': 'Can only edit PlanDefinition in draft status'}, 400

    sr.plan_definition_snapshot = edited_snapshot
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.edit_plandef',
        resource_type='ServiceRequest',
        resource_guid=sr.guid,
        ip_address=ip_address,
    )

    return sr.to_dict(), 200


def finalize_service_request(guid, user_guid=None, ip_address=None):
    """Finalize a draft ServiceRequest: build FHIR resource, set status to active."""
    sr = ServiceRequest.query.filter_by(guid=guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status != 'draft':
        return {'code': 'invalid_status', 'message': 'Can only finalize a draft ServiceRequest'}, 400

    # Snapshot attached forms (freeze Questionnaire + render-ready at point-of-issue)
    for srf in sr.forms:
        q_data, q_status = form_service.get_questionnaire(srf.form_guid)
        if q_status == 200:
            srf.form_snapshot = q_data
        rr_data, rr_status = form_service.get_render_ready(srf.form_guid)
        if rr_status == 200:
            srf.render_ready_snapshot = rr_data

    # Build the FHIR R5 ServiceRequest with contained CarePlan + Questionnaires
    sr.fhir_resource = build_service_request_resource(sr)
    sr.status = 'active'
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.finalize',
        resource_type='ServiceRequest',
        resource_guid=sr.guid,
        ip_address=ip_address,
    )

    return sr.to_dict(), 200


def archive_service_request(guid, user_guid=None, ip_address=None):
    """Archive a ServiceRequest."""
    sr = ServiceRequest.query.filter_by(guid=guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status == 'archived':
        return {'code': 'already_archived', 'message': 'Already archived'}, 400

    sr.status = 'archived'
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.archive',
        resource_type='ServiceRequest',
        resource_guid=sr.guid,
        ip_address=ip_address,
    )

    return sr.to_dict(), 200


def revoke_service_request(guid, user_guid=None, ip_address=None):
    """Revoke/cancel a ServiceRequest. Only if no matches are accepted."""
    sr = ServiceRequest.query.filter_by(guid=guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404

    accepted = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=guid, status='accepted'
    ).count()
    if accepted > 0:
        return {'code': 'has_accepted', 'message': 'Cannot revoke — has accepted matches'}, 400

    sr.status = 'revoked'
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.revoke',
        resource_type='ServiceRequest',
        resource_guid=sr.guid,
        ip_address=ip_address,
    )

    return sr.to_dict(), 200


def check_auto_archive():
    """Archive ServiceRequests past their period_end."""
    now = datetime.now(timezone.utc)
    expired = ServiceRequest.query.filter(
        ServiceRequest.status == 'active',
        ServiceRequest.period_end.isnot(None),
        ServiceRequest.period_end < now,
    ).all()

    count = 0
    for sr in expired:
        sr.status = 'archived'
        count += 1

    if count:
        db.session.commit()

    return count


# ---------------------------------------------------------------------------
# Form attachment CRUD
# ---------------------------------------------------------------------------

def add_form_to_request(sr_guid, form_guid, form_version=None, sort_order=0,
                        user_guid=None, ip_address=None):
    """Attach a form from the Plan catalogue to a draft ServiceRequest."""
    sr = ServiceRequest.query.filter_by(guid=sr_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status != 'draft':
        return {'code': 'invalid_status', 'message': 'Can only add forms in draft status'}, 400

    existing = ServiceRequestForm.query.filter_by(
        service_request_guid=sr_guid, form_guid=form_guid
    ).first()
    if existing:
        return {'code': 'duplicate', 'message': 'Form already attached to this request'}, 409

    # Fetch display title from Plan catalogue
    form_data, form_status = form_service.get_form(form_guid)
    display_title = ''
    if form_status == 200 and isinstance(form_data, dict):
        display_title = form_data.get('title', form_data.get('name', ''))

    srf = ServiceRequestForm(
        service_request_guid=sr_guid,
        form_guid=form_guid,
        form_version=form_version,
        display_title=display_title,
        sort_order=sort_order,
    )
    db.session.add(srf)
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.add_form',
        resource_type='ServiceRequest',
        resource_guid=sr_guid,
        details={'form_guid': form_guid},
        ip_address=ip_address,
    )

    return srf.to_dict(), 201


def remove_form_from_request(sr_guid, form_sr_guid, user_guid=None, ip_address=None):
    """Remove an attached form from a draft ServiceRequest."""
    sr = ServiceRequest.query.filter_by(guid=sr_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status != 'draft':
        return {'code': 'invalid_status', 'message': 'Can only remove forms in draft status'}, 400

    srf = ServiceRequestForm.query.filter_by(guid=form_sr_guid, service_request_guid=sr_guid).first()
    if not srf:
        return {'code': 'not_found', 'message': 'Form attachment not found'}, 404

    form_guid = srf.form_guid
    db.session.delete(srf)
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.remove_form',
        resource_type='ServiceRequest',
        resource_guid=sr_guid,
        details={'form_guid': form_guid},
        ip_address=ip_address,
    )

    return {'status': 'removed'}, 200


def reorder_forms(sr_guid, ordered_guids, user_guid=None, ip_address=None):
    """Bulk-update sort_order for attached forms."""
    sr = ServiceRequest.query.filter_by(guid=sr_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status != 'draft':
        return {'code': 'invalid_status', 'message': 'Can only reorder forms in draft status'}, 400

    for idx, fg in enumerate(ordered_guids):
        srf = ServiceRequestForm.query.filter_by(guid=fg, service_request_guid=sr_guid).first()
        if srf:
            srf.sort_order = idx

    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.reorder_forms',
        resource_type='ServiceRequest',
        resource_guid=sr_guid,
        ip_address=ip_address,
    )

    return {'status': 'reordered'}, 200


def list_forms_for_request(sr_guid):
    """Return ordered list of attached forms for a ServiceRequest."""
    forms = ServiceRequestForm.query.filter_by(
        service_request_guid=sr_guid
    ).order_by(ServiceRequestForm.sort_order).all()
    return {'forms': [f.to_dict() for f in forms]}, 200

import uuid
import bleach
from flask import Blueprint, jsonify, request
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import dispatch_service
from app.services.auth_service import get_current_user_guid

dispatch_bp = Blueprint('dispatch_api', __name__)


@dispatch_bp.route('/CarePlan/<guid>/dispatch', methods=['POST'])
@requires_auth
@requires_role('read_write')
def submit_dispatch(guid):
    """Submit a CarePlan dispatch request."""
    guid = bleach.clean(guid)
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'code': 'bad_request', 'message': 'Request body required'}), 400

    provider_guid = payload.get('provider_guid')
    if not provider_guid:
        return jsonify({'code': 'bad_request', 'message': 'provider_guid is required'}), 400

    assigned_user_guid = payload.get('assigned_user_guid')
    notes = payload.get('notes', '')
    idempotency_key = payload.get('idempotency_key', str(uuid.uuid4()))

    # Ticket #229: optional PDL-consent gate. When both fields are
    # present, dispatch_service refuses 403 if the destination caregiver
    # has no valid consent from the patient (Lag 2022:913 §5).
    patient_guid = payload.get('patient_guid')
    destination_caregiver_guid = payload.get('destination_caregiver_guid')
    payload_concept_guids = payload.get('payload_concept_guids') or None
    if (
        payload_concept_guids is not None
        and not isinstance(payload_concept_guids, list)
    ):
        return jsonify({
            'code': 'bad_request',
            'message': 'payload_concept_guids must be a list when provided',
        }), 400

    data, status = dispatch_service.create_dispatch(
        careplan_guid=guid,
        provider_guid=provider_guid,
        assigned_user_guid=assigned_user_guid,
        notes=notes,
        idempotency_key=idempotency_key,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
        patient_guid=patient_guid,
        destination_caregiver_guid=destination_caregiver_guid,
        payload_concept_guids=payload_concept_guids,
    )
    return jsonify(data), status


@dispatch_bp.route('/CarePlan/<guid>/dispatch/<receipt_token>', methods=['GET'])
@requires_auth
def get_dispatch_status(guid, receipt_token):
    """Check dispatch status by receipt token."""
    receipt_token = bleach.clean(receipt_token)
    data, status = dispatch_service.get_dispatch_status(receipt_token)
    return jsonify(data), status

import bleach
from flask import Blueprint, jsonify, request
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import patient_service
from app.services.audit_service import log_event
from app.services.auth_service import get_current_user_guid

patients_bp = Blueprint('patients_api', __name__)


@patients_bp.route('/Patient', methods=['GET'])
@requires_auth
def list_patients():
    """List/search patients (proxy to IPS)."""
    params = dict(request.args)
    data, status = patient_service.list_patients(params)
    return jsonify(data), status


@patients_bp.route('/Patient/<guid>', methods=['GET'])
@requires_auth
def get_patient(guid):
    """Read a single patient by GUID."""
    guid = bleach.clean(guid)
    data, status = patient_service.get_patient(guid)
    return jsonify(data), status


@patients_bp.route('/Patient', methods=['POST'])
@requires_auth
@requires_role('read_write')
def create_patient():
    """Create a new patient."""
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'code': 'bad_request', 'message': 'Request body required'}), 400

    data, status = patient_service.create_patient(payload)

    if status in (200, 201):
        log_event(
            user_guid=get_current_user_guid(),
            action='patient.create',
            resource_type='Patient',
            resource_guid=data.get('id', ''),
            ip_address=request.remote_addr,
        )

    return jsonify(data), status


@patients_bp.route('/Patient/<guid>', methods=['PUT'])
@requires_auth
@requires_role('read_write')
def update_patient(guid):
    """Update an existing patient."""
    guid = bleach.clean(guid)
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'code': 'bad_request', 'message': 'Request body required'}), 400

    data, status = patient_service.update_patient(guid, payload)

    if status in (200, 201):
        log_event(
            user_guid=get_current_user_guid(),
            action='patient.update',
            resource_type='Patient',
            resource_guid=guid,
            ip_address=request.remote_addr,
        )

    return jsonify(data), status


@patients_bp.route('/Patient/<guid>', methods=['DELETE'])
@requires_auth
@requires_role('read_write')
def delete_patient(guid):
    """Delete a patient."""
    guid = bleach.clean(guid)
    data, status = patient_service.delete_patient(guid)

    if status == 200:
        log_event(
            user_guid=get_current_user_guid(),
            action='patient.delete',
            resource_type='Patient',
            resource_guid=guid,
            ip_address=request.remote_addr,
        )

    return jsonify(data), status

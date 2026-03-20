from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import patient_service
from app.services.audit_service import log_event
from app.services.auth_service import get_current_user_guid

patients_web_bp = Blueprint('patients_web', __name__)


@patients_web_bp.route('/patients')
@requires_auth
def list_patients():
    params = dict(request.args)
    data, status = patient_service.list_patients(params)
    patients = []
    if status == 200:
        if isinstance(data, dict) and data.get('resourceType') == 'Bundle':
            patients = [e.get('resource', e) for e in data.get('entry', [])]
        elif isinstance(data, list):
            patients = data
    return render_template('patients/list.html', patients=patients, params=params)


@patients_web_bp.route('/patients/<guid>')
@requires_auth
def view_patient(guid):
    data, status = patient_service.get_patient(guid)
    if status != 200:
        flash(f"Error loading patient: {data.get('message', 'Unknown error')}", 'danger')
        return redirect(url_for('patients_web.list_patients'))
    return render_template('patients/view.html', patient=data)


@patients_web_bp.route('/patients/create', methods=['GET', 'POST'])
@requires_auth
@requires_role('read_write')
def create_patient():
    if request.method == 'POST':
        payload = {
            'resourceType': 'Patient',
            'name': [{'family': request.form.get('family', ''), 'given': [request.form.get('given', '')]}],
            'gender': request.form.get('gender', ''),
            'birthDate': request.form.get('birthDate', ''),
            'active': request.form.get('active', 'true') == 'true',
        }
        telecom_value = request.form.get('telecom', '')
        if telecom_value:
            payload['telecom'] = [{'system': 'phone', 'value': telecom_value}]

        data, status = patient_service.create_patient(payload)
        if status in (200, 201):
            log_event(
                user_guid=get_current_user_guid(),
                action='patient.create',
                resource_type='Patient',
                resource_guid=data.get('id', ''),
                ip_address=request.remote_addr,
            )
            flash('Patient created successfully', 'success')
            return redirect(url_for('patients_web.list_patients'))
        flash(f"Error: {data.get('message', 'Creation failed')}", 'danger')

    return render_template('patients/create.html')


@patients_web_bp.route('/patients/<guid>/edit', methods=['GET', 'POST'])
@requires_auth
@requires_role('read_write')
def edit_patient(guid):
    if request.method == 'POST':
        payload = {
            'resourceType': 'Patient',
            'id': guid,
            'name': [{'family': request.form.get('family', ''), 'given': [request.form.get('given', '')]}],
            'gender': request.form.get('gender', ''),
            'birthDate': request.form.get('birthDate', ''),
            'active': request.form.get('active', 'true') == 'true',
        }
        telecom_value = request.form.get('telecom', '')
        if telecom_value:
            payload['telecom'] = [{'system': 'phone', 'value': telecom_value}]

        data, status = patient_service.update_patient(guid, payload)
        if status in (200, 201):
            log_event(
                user_guid=get_current_user_guid(),
                action='patient.update',
                resource_type='Patient',
                resource_guid=guid,
                ip_address=request.remote_addr,
            )
            flash('Patient updated', 'success')
            return redirect(url_for('patients_web.view_patient', guid=guid))
        flash(f"Error: {data.get('message', 'Update failed')}", 'danger')

    data, status = patient_service.get_patient(guid)
    if status != 200:
        flash('Patient not found', 'danger')
        return redirect(url_for('patients_web.list_patients'))
    return render_template('patients/edit.html', patient=data)


@patients_web_bp.route('/patients/<guid>/delete', methods=['POST'])
@requires_auth
@requires_role('read_write')
def delete_patient(guid):
    data, status = patient_service.delete_patient(guid)
    if status == 200:
        log_event(
            user_guid=get_current_user_guid(),
            action='patient.delete',
            resource_type='Patient',
            resource_guid=guid,
            ip_address=request.remote_addr,
        )
        flash('Patient deleted', 'success')
    else:
        flash(f"Error: {data.get('message', 'Delete failed')}", 'danger')
    return redirect(url_for('patients_web.list_patients'))

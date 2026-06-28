import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import dispatch_service, provider_service
from app.services.auth_service import get_current_user_guid

dispatch_web_bp = Blueprint('dispatch_web', __name__)


@dispatch_web_bp.route('/careplans/<guid>/dispatch', methods=['GET', 'POST'])
@requires_auth
@requires_role('read_write')
def dispatch_form(guid):
    if request.method == 'POST':
        provider_guid = request.form.get('provider_guid', '')
        assigned_user_guid = request.form.get('assigned_user_guid', '')
        notes = request.form.get('notes', '')
        idempotency_key = request.form.get('idempotency_key', str(uuid.uuid4()))

        if not provider_guid:
            flash('Provider is required', 'danger')
        else:
            data, status = dispatch_service.create_dispatch(
                plan_definition_guid=guid,
                provider_guid=provider_guid,
                assigned_user_guid=assigned_user_guid or None,
                notes=notes,
                idempotency_key=idempotency_key,
                user_guid=get_current_user_guid(),
                ip_address=request.remote_addr,
            )
            if status in (200, 201):
                receipt = data.get('receipt', {})
                flash('Dispatch submitted successfully', 'success')
                return redirect(url_for('dispatch_web.view_receipt', receipt_token=receipt.get('receipt_token', '')))
            flash(f"Dispatch failed: {data.get('message', 'Unknown error')}", 'danger')

    providers_data, _ = provider_service.list_providers()
    providers = providers_data if isinstance(providers_data, list) else providers_data.get('entry', [])
    return render_template('dispatch/form.html', careplan_guid=guid, providers=providers)


@dispatch_web_bp.route('/dispatch/<receipt_token>')
@requires_auth
def view_receipt(receipt_token):
    data, status = dispatch_service.get_dispatch_status(receipt_token)
    if status != 200:
        flash('Dispatch receipt not found', 'danger')
        return redirect(url_for('main.dashboard'))
    return render_template('dispatch/receipt.html', data=data)

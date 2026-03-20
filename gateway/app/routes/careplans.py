from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.middleware.auth_middleware import requires_auth
from app.services import careplan_service
from app.services.parse_service import parse_careplan
from app.services.audit_service import log_event
from app.services.auth_service import get_current_user_guid

careplans_web_bp = Blueprint('careplans_web', __name__)


@careplans_web_bp.route('/careplans')
@requires_auth
def list_careplans():
    params = dict(request.args)
    data, status = careplan_service.list_careplans(params)
    careplans = []
    if status == 200:
        if isinstance(data, dict) and data.get('resourceType') == 'Bundle':
            careplans = [e.get('resource', e) for e in data.get('entry', [])]
        elif isinstance(data, list):
            careplans = data
    return render_template('careplans/list.html', careplans=careplans, params=params)


@careplans_web_bp.route('/careplans/<guid>')
@requires_auth
def view_careplan(guid):
    data, status = careplan_service.get_careplan(guid)
    if status != 200:
        flash(f"Error loading careplan: {data.get('message', 'Unknown error')}", 'danger')
        return redirect(url_for('careplans_web.list_careplans'))

    log_event(
        user_guid=get_current_user_guid(),
        action='careplan.view',
        resource_type='CarePlan',
        resource_guid=guid,
        ip_address=request.remote_addr,
    )

    return render_template('careplans/view.html', careplan=data)


@careplans_web_bp.route('/careplans/<guid>/readout')
@requires_auth
def readout_careplan(guid):
    data, status = careplan_service.get_careplan(guid)
    if status != 200:
        flash(f"Error loading careplan: {data.get('message', 'Unknown error')}", 'danger')
        return redirect(url_for('careplans_web.list_careplans'))

    rows, errors = parse_careplan(data)

    log_event(
        user_guid=get_current_user_guid(),
        action='careplan.readout',
        resource_type='CarePlan',
        resource_guid=guid,
        details={'row_count': len(rows), 'parse_errors': errors},
        ip_address=request.remote_addr,
    )

    return render_template('careplans/readout.html', careplan=data, rows=rows, errors=errors)

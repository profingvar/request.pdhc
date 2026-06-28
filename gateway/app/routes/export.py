from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import careplan_service, csv_service
from app.services.parse_service import parse_careplan
from app.services.audit_service import log_event
from app.services.auth_service import get_current_user_guid
from app import db
from app.models.export_models import ExportRecord

export_web_bp = Blueprint('export_web', __name__)


@export_web_bp.route('/careplans/<guid>/export/preview')
@requires_auth
def preview_export(guid):
    data, status = careplan_service.get_careplan(guid)
    if status != 200:
        flash(f"Error loading careplan: {data.get('message', 'Unknown error')}", 'danger')
        return redirect(url_for('careplans_web.list_careplans'))

    rows, errors = parse_careplan(data)
    preview = csv_service.preview_csv(rows)
    return render_template('export/preview.html', careplan=data, preview=preview, errors=errors, guid=guid)


@export_web_bp.route('/careplans/<guid>/export/download', methods=['POST'])
@requires_auth
@requires_role('read_write')
def download_export(guid):
    data, status = careplan_service.get_careplan(guid)
    if status != 200:
        flash('Error loading careplan', 'danger')
        return redirect(url_for('careplans_web.list_careplans'))

    rows, errors = parse_careplan(data)
    if not rows:
        flash('No data to export', 'warning')
        return redirect(url_for('export_web.preview_export', guid=guid))

    csv_content = csv_service.generate_csv(rows)
    filename = csv_service.generate_filename(guid)

    user_guid = get_current_user_guid()
    export_record = ExportRecord(
        plan_definition_guid=guid,
        user_guid=user_guid,
        export_type='csv',
        row_count=len(rows),
        file_name=filename,
        schema_version='1.0.0',
    )
    db.session.add(export_record)
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='export.csv',
        resource_type='CarePlan',
        resource_guid=guid,
        details={'row_count': len(rows), 'file_name': filename},
        ip_address=request.remote_addr,
    )

    return Response(
        csv_content,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )

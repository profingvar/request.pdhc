import bleach
from flask import Blueprint, jsonify, request, Response
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import careplan_service, csv_service
from app.services.parse_service import parse_careplan
from app.services.audit_service import log_event
from app.services.auth_service import get_current_user_guid
from app import db
from app.models.export_models import ExportRecord

export_bp = Blueprint('export_api', __name__)


@export_bp.route('/CarePlan/<guid>/export/preview', methods=['GET'])
@requires_auth
def preview_export(guid):
    """Preview parsed CarePlan data before CSV export."""
    guid = bleach.clean(guid)
    careplan_data, status = careplan_service.get_careplan(guid)
    if status != 200:
        return jsonify(careplan_data), status

    rows, errors = parse_careplan(careplan_data)
    preview = csv_service.preview_csv(rows)
    preview['parse_errors'] = errors
    return jsonify(preview), 200


@export_bp.route('/CarePlan/<guid>/export/csv', methods=['POST'])
@requires_auth
@requires_role('read_write')
def export_csv(guid):
    """Generate and download CSV for a CarePlan."""
    guid = bleach.clean(guid)
    careplan_data, status = careplan_service.get_careplan(guid)
    if status != 200:
        return jsonify(careplan_data), status

    rows, errors = parse_careplan(careplan_data)
    if not rows:
        return jsonify({
            'code': 'no_data',
            'message': 'No transaction rows to export',
            'parse_errors': errors,
        }), 422

    csv_content = csv_service.generate_csv(rows)
    filename = csv_service.generate_filename(guid)

    # Record the export
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
        details={'row_count': len(rows), 'file_name': filename, 'parse_errors': errors},
        ip_address=request.remote_addr,
    )

    return Response(
        csv_content,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )

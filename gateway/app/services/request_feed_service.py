"""Service to provide the request feed that provider portals poll.

Queries local dispatch records, enriches with careplan data from
the Plan backend, and returns in the format expected by the
subscription design (Section 6)."""

from datetime import datetime, timezone
from flask import current_app
from app import db
from app.models.dispatch_models import DispatchRequest, DispatchReceipt
from app.services import careplan_service


def list_requests_for_provider(provider_guid, since=None, cursor=None,
                               status=None, limit=100):
    """Return dispatched requests for a provider, with optional filters.

    Args:
        provider_guid: The provider GUID to filter on.
        since: ISO-8601 datetime — only return requests updated after this.
        cursor: Opaque cursor (currently the last-seen dispatch request id).
        status: Filter by dispatch status (e.g. 'submitted', 'active').
        limit: Max results per page.

    Returns:
        dict: { requests: [...], cursor: str|None, has_more: bool }
    """
    query = DispatchRequest.query.filter_by(provider_guid=provider_guid)

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            query = query.filter(DispatchRequest.updated_at >= since_dt)
        except (ValueError, TypeError):
            pass

    if status:
        query = query.filter(DispatchRequest.status == status)

    if cursor:
        try:
            cursor_id = int(cursor)
            query = query.filter(DispatchRequest.id > cursor_id)
        except (ValueError, TypeError):
            pass

    query = query.order_by(DispatchRequest.id.asc())
    results = query.limit(limit + 1).all()

    has_more = len(results) > limit
    page = results[:limit]

    next_cursor = str(page[-1].id) if page else None

    requests_list = []
    for dispatch_req in page:
        receipt = DispatchReceipt.query.filter_by(
            dispatch_request_guid=dispatch_req.guid
        ).first()

        entry = _build_request_entry(dispatch_req, receipt)
        requests_list.append(entry)

    return {
        'requests': requests_list,
        'cursor': next_cursor if has_more else None,
        'has_more': has_more,
    }


def get_single_request(request_guid):
    """Get a single dispatched request by its GUID.

    Returns:
        tuple: (result_dict, status_code)
    """
    dispatch_req = DispatchRequest.query.filter_by(guid=request_guid).first()
    if not dispatch_req:
        return {'code': 'not_found', 'message': f'Request {request_guid} not found'}, 404

    receipt = DispatchReceipt.query.filter_by(
        dispatch_request_guid=dispatch_req.guid
    ).first()

    entry = _build_request_entry(dispatch_req, receipt)
    return entry, 200


def update_provider_status(request_guid, provider_guid, new_status):
    """Update the provider-side status on a dispatch request.

    Providers call this to report acknowledged/completed/etc.

    Returns:
        tuple: (result_dict, status_code)
    """
    valid_statuses = ('acknowledged', 'in_progress', 'completed', 'rejected')
    if new_status not in valid_statuses:
        return {
            'code': 'bad_request',
            'message': f'Invalid status. Must be one of: {", ".join(valid_statuses)}',
        }, 400

    dispatch_req = DispatchRequest.query.filter_by(guid=request_guid).first()
    if not dispatch_req:
        return {'code': 'not_found', 'message': f'Request {request_guid} not found'}, 404

    if dispatch_req.provider_guid != provider_guid:
        return {'code': 'unauthorized', 'message': 'Provider GUID mismatch'}, 403

    dispatch_req.provider_status = new_status
    dispatch_req.provider_status_updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return {
        'request_guid': dispatch_req.guid,
        'provider_guid': dispatch_req.provider_guid,
        'provider_status': dispatch_req.provider_status,
        'provider_status_updated_at': dispatch_req.provider_status_updated_at.isoformat(),
        'message': f'Status updated to {new_status}',
    }, 200


def _build_request_entry(dispatch_req, receipt):
    """Build the response entry for one dispatch request.

    Matches the assumed format in subscription_design Section 6."""
    careplan_data = None
    try:
        cp_data, cp_status = careplan_service.get_careplan(dispatch_req.careplan_guid)
        if cp_status == 200:
            careplan_data = cp_data
    except Exception:
        pass

    # Build patient stub from careplan if available
    patient = {}
    if careplan_data:
        subject = careplan_data.get('subject', {})
        patient = {
            'patient_guid': subject.get('reference', '').split('/')[-1] if subject.get('reference') else '',
            'name': subject.get('display', ''),
        }

    # Build activities from careplan
    activities = []
    if careplan_data:
        for act in careplan_data.get('activity', []):
            detail = act.get('detail', act.get('plannedActivityDetail', {}))
            code_data = detail.get('code', {}) if isinstance(detail, dict) else {}
            codings = code_data.get('coding', []) if isinstance(code_data, dict) else []

            transactions = []
            if codings:
                transactions.append({
                    'transaction_guid': act.get('id', ''),
                    'concept_guid': codings[0].get('code', '') if codings else '',
                    'concept_name': codings[0].get('display', '') if codings else '',
                    'response_type': 'text',
                    'valueset_values': [],
                    'unit': None,
                    'required': True,
                })

            activities.append({
                'activity_guid': act.get('id', ''),
                'title': detail.get('description', '') if isinstance(detail, dict) else '',
                'transactions': transactions,
            })

    entry = {
        'request_guid': dispatch_req.guid,
        'receipt_token': receipt.receipt_token if receipt else None,
        'provider_guid': dispatch_req.provider_guid,
        'provider_name': '',
        'status': dispatch_req.status,
        'provider_status': dispatch_req.provider_status,
        'created_at': dispatch_req.created_at.isoformat(),
        'updated_at': dispatch_req.updated_at.isoformat(),
        'careplan': {
            'careplan_guid': dispatch_req.careplan_guid,
            'title': careplan_data.get('title', '') if careplan_data else '',
            'patient': patient,
            'activities': activities,
            'dispatch_metadata': {
                'dispatched_at': dispatch_req.created_at.isoformat(),
                'due_at': None,
                'priority': 'routine',
                'notes': dispatch_req.dispatch_notes,
            },
        },
    }

    return entry

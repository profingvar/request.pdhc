"""Service to provide the request feed that provider portals poll.

Queries local dispatch records, enriches with careplan data from
the Plan backend, and returns in the format expected by the
subscription design (Section 6)."""

from datetime import datetime, timezone
from flask import current_app
from app import db
from app.models.dispatch_models import DispatchRequest, DispatchReceipt
# #320 (2026-06-28): careplan_service deleted (dead proxy). The
# dispatch feed previously joined CarePlan title + patient + activities
# from a plan.pdhc upstream call, but that upstream never existed and
# the join silently degraded to empty patient + activities anyway. The
# feed now returns the dispatch row without those joined fields. Future
# real enrichment can read from the local #310 CarePlan model + its
# plan_definition_snapshot.


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

    #320 (2026-06-28): the historical implementation tried to enrich
    each entry with patient + activities pulled from a plan.pdhc
    CarePlan upstream that never existed; the call always failed and
    the entry shipped empty `patient` + `activities`. The dead path
    has been removed. Future enrichment can read the local #310
    CarePlan model's `plan_definition_snapshot` instead.
    """
    return {
        'request_guid': dispatch_req.guid,
        'receipt_token': receipt.receipt_token if receipt else None,
        'provider_guid': dispatch_req.provider_guid,
        'provider_name': '',
        'status': dispatch_req.status,
        'provider_status': dispatch_req.provider_status,
        'created_at': dispatch_req.created_at.isoformat(),
        'updated_at': dispatch_req.updated_at.isoformat(),
        'careplan': {
            # #318 deprecation window: emit canonical + legacy alias.
            'plan_definition_guid': dispatch_req.plan_definition_guid,
            'careplan_guid': dispatch_req.plan_definition_guid,
            'title': '',
            'patient': {},
            'activities': [],
            'dispatch_metadata': {
                'dispatched_at': dispatch_req.created_at.isoformat(),
                'due_at': None,
                'priority': 'routine',
                'notes': dispatch_req.dispatch_notes,
            },
        },
    }

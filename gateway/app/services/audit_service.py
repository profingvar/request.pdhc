import uuid
from functools import wraps

from flask import current_app, request
from werkzeug.wrappers import Response as WzResponse

from app import db
from app.models.audit_models import AuditLog


def log_event(user_guid=None, action='', resource_type=None, resource_guid=None,
              details=None, correlation_id=None, ip_address=None,
              data_subject_guid=None):
    """Log an audit event to the database."""
    try:
        # Extract data_subject_guid from details if not provided directly
        if not data_subject_guid and details:
            data_subject_guid = details.get('data_subject_guid')
        entry = AuditLog(
            correlation_id=correlation_id or str(uuid.uuid4()),
            user_guid=user_guid,
            action=action,
            resource_type=resource_type,
            resource_guid=resource_guid,
            details=details,
            ip_address=ip_address,
            data_subject_guid=data_subject_guid,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Audit log failed: {e}")
        db.session.rollback()


def audit_read(action, *, resource_type=None, guid_arg=None):
    """Decorator: write one AuditLog row for every successful read.

    Ticket #227 — request.pdhc PDL #3. Wrap GET endpoints that return
    patient-identified data so every read leaves a row in the
    ``audit_log`` table (PDL Ch 4 §3 kontroller requirement).

    Arguments
    ---------
    action : str
        The audit ``action`` field, e.g. ``'service_request.read'``.
    resource_type : str | None
        The FHIR/PDHC resource type. Defaults to ``None`` for
        catalogue-style reads.
    guid_arg : str | None
        The view-args key that names the resource's guid (e.g.
        ``'guid'`` for ``/ServiceRequest/<guid>``). When omitted the
        decorator scans common conventions (``guid``, ``patient_guid``,
        ``request_guid``, ``receipt_token``); if none match, the
        ``resource_guid`` field is left null and the row still records
        the read (useful for LIST endpoints).

    Behaviour
    ---------
    - Audits only successful reads (HTTP 2xx). 4xx / 5xx skip the
      audit row — the underlying access didn't happen, so PDL Ch 4 §3
      has nothing to record.
    - Failures inside ``log_event`` are swallowed (the response is
      primary). Same posture as the existing inline ``log_event``
      sites elsewhere in this repo.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            response = fn(*args, **kwargs)
            try:
                status = _resolve_status(response)
                if not 200 <= status < 300:
                    return response
                # Import here so tests can monkeypatch
                # ``get_current_user_guid`` without the decorator
                # closing over a stale reference.
                from app.services.auth_service import (
                    get_current_user_guid,
                )
                resource_guid = _resolve_guid(
                    guid_arg, kwargs,
                )
                log_event(
                    user_guid=get_current_user_guid(),
                    action=action,
                    resource_type=resource_type,
                    resource_guid=resource_guid,
                    ip_address=getattr(request, "remote_addr", None),
                )
            except Exception as exc:  # noqa: BLE001
                try:
                    current_app.logger.warning(
                        "audit_read decorator failed for %s: %s",
                        action, exc,
                    )
                except Exception:
                    pass
            return response
        return wrapper
    return decorator


def _resolve_status(response):
    """Pull the HTTP status code out of a Flask view return value."""
    if isinstance(response, WzResponse):
        return response.status_code
    if isinstance(response, tuple):
        for elem in response:
            if isinstance(elem, int):
                return elem
        # body-only tuple — Flask defaults to 200
    return 200


_GUID_VIEW_ARGS = (
    "guid", "patient_guid", "request_guid", "receipt_token",
    "form_sr_guid", "form_guid", "sr_guid",
)


def _resolve_guid(explicit_key, view_kwargs):
    """First non-empty match in either the explicit key or the
    convention list. Returns None when no view-arg is a guid."""
    if explicit_key and view_kwargs.get(explicit_key):
        return str(view_kwargs[explicit_key])
    for key in _GUID_VIEW_ARGS:
        v = view_kwargs.get(key)
        if v:
            return str(v)
    return None

"""#1054: every change to a ServiceRequest or CarePlan leaves a version, and a
ServiceRequest that has left draft is LOCKED except for status and note.

HOW. A SQLAlchemy `before_flush` hook, not a call in each service function: an
order is changed from a dozen places (finalize, archive, revoke, dispatch,
match, completion, auto-archive, the CarePlan backfill, ...) and a rule that
lives in each of them is the rule the next path forgets. For each dirty
ServiceRequest / CarePlan the hook

  1. reads the row AS IT IS IN THE DATABASE (a Core SELECT on the flushing
     connection) - the previous state, whatever the ORM did or did not load;
  2. compares it with the object; no real change -> nothing happens;
  3. for a ServiceRequest whose stored status is not `draft`: refuses any
     change outside ALLOWED_AFTER_DRAFT by raising ServiceRequestLocked (the
     API turns it into 409, naming the fields and how to replace the order);
  4. writes the previous state to the history table, bumps `version`, records
     who/why on the new version, and audits a status change.

WHO AND WHY. A service function says so with `note_change(obj, user_guid,
reason, action)` just before it mutates. Without that, the hook falls back to
the request's caller and `action = 'unattributed:<endpoint>'`, so a path that
forgot is visible in the history rather than silently anonymous.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import DateTime, event, select
from sqlalchemy.orm import Session

from app.services import sr_journal

_CTX_KEY = 'pdhc_change_context'

#: may change after draft. `fhir_resource` is derived by the server (rebuilt at
#: dispatch); `completion_record` is set with the `completed` status (#984).
ALLOWED_AFTER_DRAFT = frozenset({'status', 'notes', 'annotations',
                                 'fhir_resource', 'completion_record'})
#: may be FILLED after draft, never changed once set: the contract a dispatch
#: assigns, and the CarePlan link the 2026-11-19 backfill writes.
SET_ONCE_AFTER_DRAFT = frozenset({'contract_guid', 'care_plan_guid'})
#: maintained by this module / the ORM, never compared.
BOOKKEEPING = frozenset({'id', 'updated_at', 'version', 'version_author_guid',
                         'version_reason'})
#: no status change out of these.
TERMINAL = frozenset({'revoked', 'entered-in-error'})

#: version_reason the migration stamps on rows that existed before #1054.
PRE_HISTORY_REASON = 'pre-1054: versioning began here; earlier changes were not recorded'

LOCKED_CODE = 'service_request_locked'


class ServiceRequestLocked(Exception):
    """A change the journal rule forbids. `as_response()` is the 409 body."""

    def __init__(self, guid, fields=(), message=None, code=LOCKED_CODE):
        self.guid = guid
        self.fields = sorted(fields)
        self.code = code
        super().__init__(message or (
            f'ServiceRequest {guid} has left draft; only status and note may '
            f'change (refused: {", ".join(self.fields)}). Create a new '
            f'ServiceRequest with "replaces": ["{guid}"] instead.'))

    def as_response(self):
        body = {'code': self.code, 'message': str(self),
                'service_request_guid': self.guid}
        if self.fields:
            body['locked_fields'] = self.fields
        if self.code == LOCKED_CODE:
            body['replace_with'] = {'method': 'POST', 'path': '/api/v1/ServiceRequest',
                                    'body': {'replaces': [self.guid]}}
        return body


@dataclass(frozen=True)
class _Spec:
    history_cls: type
    fk: str             # history column naming the main row
    audit_type: str     # AuditLog.resource_type
    audit_prefix: str
    lock: bool
    has_fhir: bool


_SPECS: dict = {}


def _specs():
    if not _SPECS:
        from app.models.care_plan_models import CarePlan
        from app.models.history_models import CarePlanHistory, ServiceRequestHistory
        from app.models.service_request_models import ServiceRequest
        _SPECS[ServiceRequest] = _Spec(ServiceRequestHistory, 'service_request_guid',
                                       'ServiceRequest', 'service_request', True, True)
        _SPECS[CarePlan] = _Spec(CarePlanHistory, 'care_plan_guid',
                                 'CarePlan', 'care_plan', False, False)
    return _SPECS


# ---------------------------------------------------------------------------
# change context
# ---------------------------------------------------------------------------

def note_change(obj, user_guid=None, reason=None, action=None):
    """Who is about to change `obj`, and why. Lives until the next commit or
    rollback of the session."""
    from app import db
    db.session.info.setdefault(_CTX_KEY, {})[(type(obj).__name__, obj.guid)] = {
        'user_guid': user_guid, 'reason': reason, 'action': action}


def _ctx(session, obj):
    return (session.info.get(_CTX_KEY) or {}).get((type(obj).__name__, obj.guid))


def _fallback_ctx():
    """The caller of this request, when the path did not say."""
    try:
        from flask import current_app, g, has_request_context, request, session as fsession
    except Exception:  # pragma: no cover
        return {'user_guid': None, 'reason': None, 'action': 'unattributed:system'}
    if not has_request_context():
        return {'user_guid': None, 'reason': None, 'action': 'unattributed:system'}
    user = None
    if current_app.config.get('AUTH_DISABLED'):
        user = 'dev-admin-guid'
    blob = g.get('api_key_access_blob') or fsession.get('access_blob')
    if isinstance(blob, dict) and blob.get('user_guid'):
        user = blob['user_guid']
    return {'user_guid': user, 'reason': None,
            'action': f'unattributed:{request.endpoint or request.path}'}


def _clear_ctx(session, *a, **kw):
    session.info.pop(_CTX_KEY, None)


# ---------------------------------------------------------------------------
# value handling
# ---------------------------------------------------------------------------

def _naive_utc(v):
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


def _same(a, b):
    a, b = _naive_utc(a), _naive_utc(b)
    return a == b


def json_safe(v):
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return copy.deepcopy(v)


def _columns(obj):
    return [(attr.key, attr.columns[0]) for attr in obj.__mapper__.column_attrs]


def _db_row(session, obj):
    table = obj.__table__
    res = session.connection().execute(
        select(table).where(table.c.id == obj.id)).mappings().first()
    return dict(res) if res is not None else None


def row_to_namespace(model_cls, row: dict, fhir_resource=None):
    """A history `row` (JSON) back into attribute form, datetimes parsed."""
    out = {}
    for attr in model_cls.__mapper__.column_attrs:
        v = row.get(attr.key)
        if isinstance(attr.columns[0].type, DateTime) and isinstance(v, str):
            try:
                v = datetime.fromisoformat(v)
            except ValueError:
                pass
        out[attr.key] = v
    if fhir_resource is not None or 'fhir_resource' in out:
        out['fhir_resource'] = fhir_resource
    out.setdefault('forms', [])
    out['forms'] = []
    out['contract_matches'] = []
    return SimpleNamespace(**out)


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------

def locked_fields(old_status, changed: dict):
    """The fields of `changed` ({name: (old, new)}) that the journal rule
    refuses on an order whose STORED status is `old_status`. Pure."""
    if old_status == 'draft':
        return set()
    bad = set()
    for name, (old, new) in changed.items():
        if name in ALLOWED_AFTER_DRAFT:
            continue
        if name in SET_ONCE_AFTER_DRAFT and old in (None, ''):
            continue
        bad.add(name)
    return bad


def status_refusal(old_status, new_status):
    """A refused status transition, as a message, or None. Pure."""
    if old_status == new_status:
        return None
    if new_status == 'draft':
        return f'a ServiceRequest cannot return to draft from {old_status}'
    if old_status in TERMINAL:
        return f'a {old_status} ServiceRequest cannot change status (to {new_status})'
    return None


def check_change(obj, old_row, changed):
    """Raise ServiceRequestLocked if `changed` breaks the rule."""
    old_status = old_row.get('status')
    bad = locked_fields(old_status, changed)
    if bad:
        raise ServiceRequestLocked(obj.guid, bad)
    if 'status' in changed:
        msg = status_refusal(old_status, changed['status'][1])
        if msg:
            raise ServiceRequestLocked(obj.guid, (), msg, code='status_transition_refused')


# ---------------------------------------------------------------------------
# the hook
# ---------------------------------------------------------------------------

def _before_flush(session, flush_context, instances):
    specs = _specs()
    from app.models.audit_models import AuditLog
    now = datetime.now(timezone.utc)

    for obj in list(session.new):
        if type(obj) not in specs:
            continue
        ctx = _ctx(session, obj) or {}
        if obj.version is None:
            obj.version = 1
        if not obj.version_author_guid:
            obj.version_author_guid = (ctx.get('user_guid')
                                       or getattr(obj, 'requester_user_guid', None)
                                       or getattr(obj, 'created_by_user_guid', None))
        if not obj.version_reason:
            obj.version_reason = ctx.get('reason') or 'created'

    for obj in list(session.deleted):
        spec = specs.get(type(obj))
        if spec and spec.lock:
            old = _db_row(session, obj)
            if old and old.get('status') != 'draft':
                raise ServiceRequestLocked(obj.guid, (), (
                    f'ServiceRequest {obj.guid} has left draft and is part of the '
                    'record; it cannot be deleted. Revoke it instead.'),
                    code='service_request_delete_refused')

    for obj in list(session.dirty):
        spec = specs.get(type(obj))
        if spec is None or obj in session.deleted or obj.id is None:
            continue
        if not session.is_modified(obj, include_collections=False):
            continue
        old = _db_row(session, obj)
        if old is None:
            continue
        changed = {}
        for key, _col in _columns(obj):
            if key in BOOKKEEPING:
                continue
            new = getattr(obj, key)
            if not _same(old.get(key), new):
                changed[key] = (old.get(key), new)
        if not changed:
            continue
        if spec.lock:
            check_change(obj, old, changed)
        ctx = _ctx(session, obj) or _fallback_ctx()

        row = {k: json_safe(v) for k, v in old.items() if k != 'fhir_resource'}
        hist = dict(
            guid=None,
            patient_guid=old.get('patient_guid'),
            version=old.get('version') or 1,
            status=old.get('status') or 'unknown',
            row=row,
            version_recorded_at=_naive_utc(old.get('updated_at') or old.get('created_at')),
            version_author_guid=old.get('version_author_guid'),
            changed_at=_naive_utc(now),
            changed_by_user_guid=ctx.get('user_guid'),
            change_reason=ctx.get('reason'),
            change_action=ctx.get('action'),
        )
        hist[spec.fk] = obj.guid
        hist.pop('guid')
        if spec.has_fhir:
            hist['fhir_resource'] = copy.deepcopy(old.get('fhir_resource'))
        session.add(spec.history_cls(**hist))

        obj.version = (old.get('version') or 1) + 1
        obj.version_author_guid = ctx.get('user_guid')
        obj.version_reason = ctx.get('reason') or ctx.get('action')
        obj.updated_at = now

        if 'status' in changed:
            session.add(AuditLog(
                user_guid=ctx.get('user_guid'),
                action=f'{spec.audit_prefix}.status_changed',
                resource_type=spec.audit_type, resource_guid=obj.guid,
                data_subject_guid=old.get('patient_guid'),
                details={'from': changed['status'][0], 'to': changed['status'][1],
                         'version': obj.version, 'reason': ctx.get('reason'),
                         'change_action': ctx.get('action')}))


_installed = False


def install():
    global _installed
    if _installed:
        return
    event.listen(Session, 'before_flush', _before_flush)
    event.listen(Session, 'after_commit', _clear_ctx)
    event.listen(Session, 'after_soft_rollback', lambda s, prev: _clear_ctx(s))
    _installed = True


# ---------------------------------------------------------------------------
# reading versions back
# ---------------------------------------------------------------------------

def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def sr_versions(sr):
    """Every version of `sr`, OLDEST first: dicts with version, status,
    recorded_at, author_guid, reason, ended (the change that superseded it,
    or None for the current one), and `ns` (attribute namespace) + `fhir`."""
    from app.models.history_models import ServiceRequestHistory
    from app.models.service_request_models import ServiceRequest
    rows = (ServiceRequestHistory.query.filter_by(service_request_guid=sr.guid)
            .order_by(ServiceRequestHistory.version.asc()).all())
    out = []
    for h in rows:
        out.append({
            'version': h.version, 'status': h.status,
            'recorded_at': _iso(h.version_recorded_at),
            'author_guid': h.version_author_guid,
            'reason': (h.row or {}).get('version_reason'),
            'ended': {'at': _iso(h.changed_at), 'by': h.changed_by_user_guid,
                      'reason': h.change_reason, 'action': h.change_action},
            'ns': row_to_namespace(ServiceRequest, h.row or {}, h.fhir_resource),
            'fhir': h.fhir_resource,
        })
    out.append({
        'version': sr.version or 1, 'status': sr.status,
        'recorded_at': _iso(sr.updated_at if (sr.version or 1) > 1 else
                            (sr.updated_at if sr.version_reason == PRE_HISTORY_REASON
                             else sr.created_at)),
        'author_guid': sr.version_author_guid,
        'reason': sr.version_reason,
        'ended': None,
        'ns': sr, 'fhir': sr.fhir_resource,
    })
    return out


def render_sr(ns, fhir, version, last_updated):
    """The R5 ServiceRequest of ONE version: the stored resource of that
    version (or one built from the row, for a draft that never had one), with
    status, journal elements and meta of THAT version."""
    if fhir:
        res = copy.deepcopy(fhir)
    elif getattr(ns, 'kind', None) == 'diagnosis-review':
        from app.services.diagnosis_review import build_fhir_resource
        res = build_fhir_resource(ns)
    else:
        from app.services.fhir_builder_service import build_service_request_resource
        res = build_service_request_resource(ns)
    res['resourceType'] = 'ServiceRequest'
    res['id'] = ns.guid
    res['status'] = sr_journal.fhir_status(ns.status)
    sr_journal.apply_journal_elements(res, ns)
    meta = {'versionId': str(version)}
    if last_updated:
        meta['lastUpdated'] = _iso(last_updated)
    if sr_journal.fhir_status(ns.status) != ns.status:
        meta['tag'] = [{'system': sr_journal.LOCAL_STATUS_SYSTEM, 'code': ns.status}]
    res['meta'] = meta
    return res


def cp_versions(cp):
    from app.models.care_plan_models import CarePlan
    from app.models.history_models import CarePlanHistory
    rows = (CarePlanHistory.query.filter_by(care_plan_guid=cp.guid)
            .order_by(CarePlanHistory.version.asc()).all())
    out = []
    for h in rows:
        out.append({
            'version': h.version, 'status': h.status,
            'recorded_at': _iso(h.version_recorded_at),
            'author_guid': h.version_author_guid,
            'reason': (h.row or {}).get('version_reason'),
            'ended': {'at': _iso(h.changed_at), 'by': h.changed_by_user_guid,
                      'reason': h.change_reason, 'action': h.change_action},
            'ns': row_to_namespace(CarePlan, h.row or {}),
        })
    out.append({
        'version': cp.version or 1, 'status': cp.status,
        'recorded_at': _iso(cp.updated_at if (cp.version or 1) > 1 or
                            cp.version_reason == PRE_HISTORY_REASON else cp.created_at),
        'author_guid': cp.version_author_guid, 'reason': cp.version_reason,
        'ended': None, 'ns': cp,
    })
    return out


CP_FHIR_STATUS = {'draft': 'draft', 'active': 'active', 'on-hold': 'on-hold',
                  'revoked': 'revoked', 'completed': 'completed',
                  'entered-in-error': 'entered-in-error', 'unknown': 'unknown'}


def render_care_plan(ns, version, last_updated):
    """R5 CarePlan of one version; goals as contained Goal resources."""
    res = {
        'resourceType': 'CarePlan',
        'id': ns.guid,
        'meta': {'versionId': str(version), **({'lastUpdated': _iso(last_updated)}
                                               if last_updated else {})},
        'identifier': [{'system': 'https://request.pdhc.se/fhir/CarePlan', 'value': ns.guid}],
        'status': CP_FHIR_STATUS.get(ns.status, 'unknown'),
        'intent': ns.intent if ns.intent in ('proposal', 'plan', 'order', 'option',
                                             'directive') else 'plan',
        'subject': {'reference': f'Patient/{ns.patient_guid}'},
    }
    if ns.plan_definition_guid:
        res['instantiatesCanonical'] = [
            f'https://plan.pdhc.se/api/v1/plandefinitions/{ns.plan_definition_guid}']
    if ns.title:
        res['title'] = ns.title
    if ns.description:
        res['description'] = ns.description
    if ns.period_start or ns.period_end:
        res['period'] = {k: _iso(v) for k, v in (('start', ns.period_start),
                                                  ('end', ns.period_end)) if v}
    if ns.created_at:
        res['created'] = _iso(ns.created_at)
    if ns.created_by_user_guid:
        res['custodian'] = {'reference': f'Practitioner/{ns.created_by_user_guid}'}
    contained, refs = [], []
    for i, g in enumerate(ns.goals or []):
        if not isinstance(g, dict):
            continue
        gid = f'goal-{i}'
        text = g.get('concept_name') or g.get('description') or 'Mål'
        goal = {'resourceType': 'Goal', 'id': gid, 'lifecycleStatus': 'active',
                'description': {'text': str(text)},
                'subject': {'reference': f'Patient/{ns.patient_guid}'}}
        contained.append(goal)
        refs.append({'reference': f'#{gid}'})
    if contained:
        res['contained'] = contained
        res['goal'] = refs
    return res

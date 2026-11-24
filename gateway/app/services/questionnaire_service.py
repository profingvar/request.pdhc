"""#1043: Questionnaires referenced by canonical url + version.

request.pdhc could already attach a FORM to a ServiceRequest, but only one
from plan.pdhc's form catalogue (built in plan's form builder, addressed by a
plan form guid). The PROMs in plans/PROMs/ and the patient EPS form are
standalone FHIR Questionnaire JSON files with a canonical url and are in no
catalogue, so care could not order them.

This is the minimal registry that closes that: import a Questionnaire
(`flask questionnaire import FILE`), then attach it to a draft ServiceRequest
by url (+ version). The JSON is frozen onto the order at attach time and
travels inline in the provider download. It is NOT a form designer: nothing
here edits a Questionnaire.
"""
from __future__ import annotations

import hashlib
import json

from app import db
from app.models.service_request_models import (
    QuestionnaireResource, ServiceRequest, ServiceRequestForm,
)
from app.services.audit_service import log_event


class QuestionnaireInvalid(ValueError):
    """The JSON is not a usable FHIR Questionnaire. `code` names why."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _content_hash(resource):
    return hashlib.sha256(
        json.dumps(resource, sort_keys=True, separators=(',', ':'),
                   ensure_ascii=False).encode('utf-8')).hexdigest()


def split_canonical(url, version=None):
    """('https://…/Questionnaire/x', '1') from 'https://…/Questionnaire/x|1'.
    An explicit `version` argument wins over a `|version` suffix."""
    url = (url or '').strip()
    if '|' in url:
        url, _, suffix = url.partition('|')
        version = version or suffix
    return url, ((version or '').strip() or None)


def import_questionnaire(resource, created_by=None):
    """Store a Questionnaire. Returns (row, created).

    Idempotent on identical content. Different content under an existing
    url + version raises QuestionnaireInvalid('questionnaire_version_conflict'):
    a version is immutable once orders may carry a frozen copy of it.
    """
    if not isinstance(resource, dict) or resource.get('resourceType') != 'Questionnaire':
        raise QuestionnaireInvalid('not_a_questionnaire',
                                   'resourceType must be "Questionnaire"')
    url = (resource.get('url') or '').strip()
    version = str(resource.get('version') or '').strip()
    if not url:
        raise QuestionnaireInvalid('questionnaire_url_missing',
                                   'the Questionnaire has no canonical url')
    if not version:
        raise QuestionnaireInvalid('questionnaire_version_missing',
                                   'the Questionnaire has no version')
    if len(url) > 255 or len(version) > 50:
        raise QuestionnaireInvalid('questionnaire_reference_too_long',
                                   'url is limited to 255 and version to 50 characters')
    if not isinstance(resource.get('item'), list) or not resource['item']:
        raise QuestionnaireInvalid('questionnaire_has_no_items',
                                   'the Questionnaire has no item list')
    digest = _content_hash(resource)
    row = QuestionnaireResource.query.filter_by(url=url, version=version).first()
    if row is not None:
        if row.content_hash != digest:
            raise QuestionnaireInvalid(
                'questionnaire_version_conflict',
                f'{url}|{version} is already stored with different content; '
                'publish the change under a new version')
        return row, False
    row = QuestionnaireResource(
        url=url, version=version,
        title=(resource.get('title') or resource.get('name') or '')[:255] or None,
        resource=resource, content_hash=digest, created_by=created_by)
    db.session.add(row)
    db.session.commit()
    log_event(user_guid=created_by, action='questionnaire.import',
              resource_type='Questionnaire', resource_guid=row.guid,
              details={'url': url, 'version': version, 'content_hash': digest})
    return row, True


def resolve(url, version=None):
    """The stored Questionnaire for a canonical, or None.

    Without a version the most recently imported one is used; the version
    actually attached is then recorded on the order, so the reference never
    stays open-ended.
    """
    url, version = split_canonical(url, version)
    if not url:
        return None
    q = QuestionnaireResource.query.filter_by(url=url)
    if version:
        return q.filter_by(version=version).first()
    return q.order_by(QuestionnaireResource.created_at.desc(),
                      QuestionnaireResource.id.desc()).first()


def list_questionnaires():
    rows = QuestionnaireResource.query.order_by(
        QuestionnaireResource.url, QuestionnaireResource.created_at.desc()).all()
    return [r.to_dict() for r in rows]


def catalogue_entries():
    """Registry rows shaped like plan.pdhc's form catalogue entries, so the
    existing form pickers can list them next to plan's forms."""
    return [{'guid': r['guid'],
             'title': f"{r['title'] or r['url']} (v{r['version']})",
             'questionnaire_url': r['url'], 'version': r['version']}
            for r in list_questionnaires()]


def attach_row(sr, row, sort_order=0, user_guid=None, ip_address=None):
    """Attach a registry Questionnaire to a draft ServiceRequest, frozen now."""
    if sr.status != 'draft':
        # #1054: a sent order is locked; 409 with how to replace it
        from app.services.versioning import ServiceRequestLocked
        return ServiceRequestLocked(sr.guid, ['forms']).as_response(), 409
    dup = ServiceRequestForm.query.filter_by(
        service_request_guid=sr.guid, form_guid=row.guid).first()
    if dup:
        return {'code': 'duplicate',
                'message': 'Form already attached to this request'}, 409
    srf = ServiceRequestForm(
        service_request_guid=sr.guid,
        form_guid=row.guid,
        form_version=row.version,
        form_snapshot=row.resource,
        questionnaire_url=row.url,
        questionnaire_version=row.version,
        display_title=row.title or row.url,
        sort_order=sort_order,
    )
    db.session.add(srf)
    db.session.commit()
    log_event(user_guid=user_guid, action='service_request.add_form',
              resource_type='ServiceRequest', resource_guid=sr.guid,
              data_subject_guid=sr.patient_guid,
              details={'form_guid': row.guid, 'questionnaire_url': row.url,
                       'questionnaire_version': row.version},
              ip_address=ip_address)
    return srf.to_dict(), 201


def attach_by_canonical(sr_guid, url, version=None, sort_order=0,
                        user_guid=None, ip_address=None):
    sr = ServiceRequest.query.filter_by(guid=sr_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    row = resolve(url, version)
    if row is None:
        u, v = split_canonical(url, version)
        return {'code': 'questionnaire_not_found',
                'message': (f'No Questionnaire {u}' + (f'|{v}' if v else '')
                            + ' is stored in request.pdhc; import it first '
                              '(flask questionnaire import FILE)')}, 404
    return attach_row(sr, row, sort_order=sort_order,
                      user_guid=user_guid, ip_address=ip_address)


def for_download(sr):
    """The order's Questionnaires for the provider download, inline (#1043).

    Every attached form with a frozen snapshot, whether it came from plan's
    catalogue or from the registry. `url` and `version` fall back to the
    snapshot's own canonical for plan-catalogue forms. The JSON is the
    Questionnaire exactly as frozen — the copy inside
    fhir_resource.contained is rewritten for R5 (`choice` -> `coding`) and
    given a local id, so it is not the same document.
    """
    out = []
    for srf in sr.forms:
        snap = srf.form_snapshot
        if not isinstance(snap, dict):
            continue
        out.append({
            'form_guid': srf.form_guid,
            'url': srf.questionnaire_url or snap.get('url'),
            'version': srf.questionnaire_version or snap.get('version') or srf.form_version,
            'title': srf.display_title or snap.get('title'),
            'questionnaire': snap,
        })
    return out

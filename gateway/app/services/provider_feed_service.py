"""Provider feed service — list and download ServiceRequests for a provider org.

The feed returns metadata only (no patient data). The provider must
call download_bundle() to get the full FHIR resource + exchange grant.
"""
from datetime import datetime, timezone

from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch,
)
from app.services.grant_service import issue_grant, use_grant
from app.services import context_service, questionnaire_service
from app.services.audit_service import log_event


def list_for_provider(provider_org_guid, since=None, limit=50,
                      include_archived=False, patient_guid=None,
                      expose_patient_guid=False):
    """List ServiceRequests matched to this provider org.

    Returns metadata only — no patient data (GDPR data minimization).

    Archived ServiceRequests are NOT listed by default (#582): an archived
    request must not stay actively exposed to providers as if it were open
    work. They remain *downloadable* by guid — see ``download_bundle`` — so
    #90's late-submission path is intact for a provider that already holds
    the request, and a provider reconciling its own backlog can still
    enumerate them with ``include_archived``.

    Args:
        provider_org_guid: from validated PAT (never from request params)
        since: ISO datetime string, return only items updated after this
        limit: max items to return
        include_archived: opt in to listing archived SRs as well
        patient_guid: #1043 — only this patient's ServiceRequests. A
            NARROWING filter inside the provider's own matches: it can never
            return an item the unfiltered feed would not. The ROUTE refuses
            it for a PAT without scope `patient_generated`.
        expose_patient_guid: #1043 — put `patient_guid` on each item. Off by
            default, so a caller that does not decide gets the pre-#1043
            shape; the route turns it on only for a `patient_generated` PAT.

    Returns:
        tuple: (result_dict, status_code)
    """
    query = db.session.query(
        ServiceRequestContractMatch, ServiceRequest
    ).join(
        ServiceRequest,
        ServiceRequest.guid == ServiceRequestContractMatch.service_request_guid,
    ).filter(
        ServiceRequestContractMatch.provider_org_guid == provider_org_guid,
        ServiceRequestContractMatch.status.in_(['pending', 'sent', 'accepted']),
        # #582 supersedes #90 on this point: archived SRs are excluded from
        # the feed unless explicitly asked for. #90's concern — a provider
        # submitting late, past period_end — is served by download_bundle,
        # which still accepts 'archived'.
        ServiceRequest.status.in_(
            ['active', 'archived'] if include_archived else ['active']
        ),
    )

    if patient_guid:
        query = query.filter(ServiceRequest.patient_guid == patient_guid)

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            query = query.filter(ServiceRequestContractMatch.updated_at > since_dt)
        except (ValueError, TypeError):
            pass

    query = query.order_by(ServiceRequestContractMatch.created_at.desc())
    results = query.limit(limit).all()

    items = []
    for match, sr in results:
        snapshot = sr.plan_definition_snapshot or {}
        item = {
            'service_request_guid': sr.guid,
            'match_guid': match.guid,
            'status': match.status,
            'sr_status': sr.status,
            'title': snapshot.get('title', ''),
            'intent': sr.intent,
            'priority': sr.priority,
            'contract_guid': match.contract_guid,
            'created_at': sr.created_at.isoformat(),
            'updated_at': match.updated_at.isoformat(),
            'period_start': sr.period_start.isoformat() if sr.period_start else None,
            'period_end': sr.period_end.isoformat() if sr.period_end else None,
            'download_url': f'/api/v1/provider/download/{sr.guid}',
        }
        if expose_patient_guid:
            # #1043, operator decision 2026-11-22: the eps patient guid
            # (pseudonymous, Rule 18) is in the feed ONLY for the patient
            # app's credential, which must tell whose order an item is. For
            # every other provider the feed is unchanged: metadata only, and
            # the guid stays behind the per-order, audited download.
            item['patient_guid'] = sr.patient_guid
        items.append(item)

    return {'items': items, 'total': len(items)}, 200


def download_bundle(service_request_guid, provider_org_guid, contract_guid,
                    ip_address=None):
    """Download the full FHIR Bundle for a ServiceRequest.

    Verifies the provider has a matching contract, issues a DataExchangeGrant
    if none exists, and returns the FHIR resource with the grant token.

    Returns:
        tuple: (result_dict, status_code)
    """
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    # #984: a diagnosis review is a clinician's task in icd11.pdhc, never sent.
    from app.services.diagnosis_review import dispatch_refusal
    refusal = dispatch_refusal(sr)
    if refusal:
        return refusal

    # Archived SRs remain downloadable so providers can still fetch the
    # bundle and submit late reports (ticket #90). Drafts and revoked
    # SRs are still blocked — they were never valid for this provider.
    if sr.status not in ('active', 'archived'):
        return {'code': 'invalid_status',
                'message': f'ServiceRequest status {sr.status} is not downloadable'}, 400

    # Verify match exists for this provider
    match = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=service_request_guid,
        provider_org_guid=provider_org_guid,
    ).first()

    if not match:
        return {'code': 'unauthorized',
                'message': 'No contract match for this provider'}, 403

    if not sr.fhir_resource:
        return {'code': 'not_ready',
                'message': 'FHIR resource not yet assembled'}, 400

    # Issue or retrieve grant
    grant_data, _ = issue_grant(
        service_request_guid=sr.guid,
        patient_guid=sr.patient_guid,
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
    )

    # Record download in audit
    log_event(
        action='bundle.downloaded',
        resource_type='ServiceRequest',
        resource_guid=sr.guid,
        details={
            'patient_guid': sr.patient_guid,
            'provider_org_guid': provider_org_guid,
            'contract_guid': contract_guid,
            'data_subject_guid': sr.patient_guid,
        },
        ip_address=ip_address,
    )

    return {
        'fhir_resource': sr.fhir_resource,
        'grant_token': grant_data['grant_token'],
        'service_request_guid': sr.guid,
        'patient_guid': sr.patient_guid,
        'contract_guid': contract_guid,
        'provider_org_guid': provider_org_guid,
        # sr_status is the LIVE status and the one to act on. The embedded
        # fhir_resource is the resource as dispatched, so its `status` is
        # frozen at dispatch time (an archived request still reads "active"
        # there). is_open says in one field whether the order still applies.
        'sr_status': sr.status,
        'is_open': sr.status == 'active',
        'period_start': sr.period_start.isoformat() if sr.period_start else None,
        'period_end': sr.period_end.isoformat() if sr.period_end else None,
        'care_plan_guid': sr.care_plan_guid,
        'care_plan': instantiated_care_plan(sr),
        # #1043 — additive, for a client that renders the order to a person
        # (the patient app). Existing keys above are unchanged.
        'title': (sr.plan_definition_snapshot or {}).get('title'),
        'requesting_org_guid': sr.requester_org_guid,
        'requesting_org_name': sr.requester_org_name,
        # The order's Questionnaires INLINE, as frozen. The copies in
        # fhir_resource.contained are rewritten for R5 and re-identified.
        'questionnaires': questionnaire_service.for_download(sr),
    }, 200


_UCUM_PERIOD = {'h': 'h', 'd': 'd', 'wk': 'wk', 'mo': 'mo', 'min': 'min'}


def _fhir_timing(a):
    """FHIR Timing from the activity's frozen timing fields, or None."""
    if a.get('timing_type') == 'continuous':
        # 2026-11-20: ordered ONCE, lasting the active period (plan.pdhc's
        # export uses the same Timing). The stream's interval is sent as
        # `expected_sampling_interval`, never as a frequency, so a provider
        # does not read 3,840 orders into a CGM.
        v, u = a.get('timing_bounds_duration_value'), a.get('timing_bounds_duration_unit')
        if not v or u not in _UCUM_PERIOD:
            return None
        return {'repeat': {'count': 1, 'duration': v, 'durationUnit': _UCUM_PERIOD[u]}}
    if a.get('timing_type') != 'repeat':
        return None
    rep = {}
    if a.get('timing_frequency'):
        rep['frequency'] = int(a['timing_frequency'])
    if a.get('timing_period'):
        rep['period'] = a['timing_period']
    if a.get('timing_period_unit') in _UCUM_PERIOD:
        rep['periodUnit'] = _UCUM_PERIOD[a['timing_period_unit']]
    if a.get('timing_bounds_mode') == 'count' and a.get('timing_bounds_count'):
        rep['count'] = int(a['timing_bounds_count'])
    elif (a.get('timing_bounds_mode') == 'duration'
          and a.get('timing_bounds_duration_value')):
        rep['boundsDuration'] = {
            'value': a['timing_bounds_duration_value'],
            'unit': a.get('timing_bounds_duration_unit') or 'mo',
            'system': 'http://unitsofmeasure.org',
            'code': a.get('timing_bounds_duration_unit') or 'mo'}
    if a.get('duration_value') and a.get('duration_unit'):
        rep['duration'] = a['duration_value']
        rep['durationUnit'] = a['duration_unit']
    return {'repeat': rep} if rep else None


def _download_transaction(t, maps=None):
    """One measurement of the order, as the provider download carries it.

    The first eleven keys are the pre-#1043 shape, values unchanged. #1043
    ADDS what a client needs to render an input: `label`, `response_type_name`,
    `scale_min`/`scale_max` (the allowed interval gateway enforces with
    OUT_OF_SCALE — not `range_min`/`range_max`, the clinical range), `options`
    and `required`. `response_type` and `unit` are filled from plan.pdhc only
    where the frozen snapshot has none (they used to be null there).
    """
    detail = context_service.transaction_detail(t, maps)
    return {
        'transaction_guid': t.get('transaction_guid') or t.get('guid'),
        'concept_guid': t.get('concept_guid'),
        'concept_name': t.get('concept_name'),
        'unit': t.get('unit') or t.get('concept_unit_name') or detail['unit'],
        'response_type': t.get('response_type') or detail['response_type'],
        'requirement_type': t.get('requirement_type'),
        'range_min': t.get('range_min'),
        'range_max': t.get('range_max'),
        'recommended_range_min': t.get('recommended_range_min'),
        'recommended_range_max': t.get('recommended_range_max'),
        'action_limit_source': t.get('action_limit_source'),
        # ── #1043 ──
        'label': detail['label'],
        'response_type_name': detail['response_type_name'],
        'scale_min': detail['scale_min'],
        'scale_max': detail['scale_max'],
        'options': detail['options'],
        'required': detail['required'],
    }


def instantiated_care_plan(sr):
    """The plan THIS order instantiates, from the snapshot frozen when the
    order was created (2026-11-19, asked for by a provider: reading the live
    template via instantiatesCanonical gives a schedule that may have changed
    since, while its version string did not).

    The activities, schedules and transaction_guids are the order's own
    frozen copy. care_plan_guid names the patient's shared CarePlan for this
    PlanDefinition (one per patient + PlanDefinition); two orders under the
    same plan may carry different frozen schedules if the template changed
    between them, and each order's own schedule is the one that applies to it.
    """
    snap = sr.plan_definition_snapshot or {}
    acts = []
    # ONE look at plan.pdhc's concept maps for the whole order (#1043).
    maps = context_service.plan_maps()
    for a in sorted(snap.get('activities') or [], key=lambda x: x.get('sort_order') or 0):
        acts.append({
            'activity_guid': a.get('activity_guid') or a.get('guid'),
            'title': a.get('title'),
            'description': a.get('description'),
            'performer_type': a.get('performer_type'),
            'timing_type': a.get('timing_type'),
            'timing': _fhir_timing(a),
            'expected_sampling_interval': (
                {'value': a['sample_interval_value'], 'unit': a.get('sample_interval_unit'),
                 'system': 'http://unitsofmeasure.org', 'code': a.get('sample_interval_unit')}
                if a.get('timing_type') == 'continuous' and a.get('sample_interval_value')
                else None),
            'transactions': [
                _download_transaction(t, maps)
                for t in sorted(a.get('transactions') or [],
                                key=lambda x: x.get('sort_order') or 0)],
        })
    return {
        'care_plan_guid': sr.care_plan_guid,
        'plan_definition_guid': sr.plan_definition_guid,
        'plan_definition_title': snap.get('title'),
        'plan_definition_version': snap.get('version'),
        'frozen_at': sr.created_at.isoformat() if sr.created_at else None,
        'activities': acts,
    }

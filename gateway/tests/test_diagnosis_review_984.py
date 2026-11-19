"""#984 — diagnosis review as a PlanDefinition step (contract section 2).

plans/984_diagnosis_review_contract.md. A PlanDefinition action whose
definitionCanonical is the icd11 diagnosis-review ActivityDefinition becomes
its own ServiceRequest at finalize: instantiatesCanonical = that canonical,
the diagnosis-code-scope extensions copied verbatim, performerType clinician,
work link <ICD11_BASE_URL>/session/<guid>. It is never dispatched. icd11.pdhc
reads it and completes it with its own named service key.
"""
import copy
import uuid
from unittest.mock import patch

import pytest

from app import db
from app.models.security_models import WebhookDelivery
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch, ServiceRequestForm,
)
from app.services import diagnosis_review as dr
from app.services import service_request_service

ICD11_KEY = 'test-icd11-key-984'
INTERNAL_KEY = 'test-internal-service-key-12345'   # conftest's gateway key
CANON = 'https://icd11.pdhc.se/fhir/ActivityDefinition/diagnosis-review'
SCOPE_URL = 'https://plan.pdhc.se/fhir/StructureDefinition/diagnosis-code-scope'
PATIENT = 'patient-984'
UNIT = 'unit-984'

SCOPE_EXTS = [
    {'url': SCOPE_URL, 'valueString': '5A1'},
    {'url': SCOPE_URL, 'valueString': 'BA0'},
]
DR_ACTION = {
    'title': 'Diagnosgenomgång diabetes',
    'description': 'Årlig genomgång',
    'type': {'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/action-type',
                         'code': 'update', 'display': 'Update'}]},
    'definitionCanonical': CANON,
    'participant': [{'type': 'practitioner'}],
    'extension': SCOPE_EXTS + [{'url': 'https://example.org/other', 'valueString': 'x'}],
    'timingTiming': {'repeat': {'frequency': 1, 'period': 1, 'periodUnit': 'a'}},
}
FORM_ACTION = {
    'title': 'Formulär',
    'type': {'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/action-type',
                         'code': 'collect-information'}]},
    'definitionCanonical': 'https://plan.pdhc.se/api/v1/forms/form-984',
}


def _plandef(actions):
    return {'id': 'pd-984', 'guid': 'pd-984', 'title': 'Diabetes uppföljning',
            'activities': [], 'goals': [],
            'fhir_data': {'resourceType': 'PlanDefinition', 'action': copy.deepcopy(actions)}}


@pytest.fixture(autouse=True)
def _env(app, monkeypatch):
    prev = (app.config.get('ICD11_PDHC_SERVICE_KEY'), app.config.get('ICD11_BASE_URL'))
    app.config['ICD11_PDHC_SERVICE_KEY'] = ICD11_KEY
    app.config['ICD11_BASE_URL'] = 'https://icd11.pdhc.se'
    monkeypatch.setattr('app.services.ips_client.is_sr_visible', lambda sr, **k: True)
    monkeypatch.setattr('app.services.ips_client.filter_visible_srs', lambda srs, **k: srs)
    monkeypatch.setattr('app.services.service_request_service.context_service.'
                        'enrich_snapshot_concepts', lambda s: s)
    yield
    app.config['ICD11_PDHC_SERVICE_KEY'], app.config['ICD11_BASE_URL'] = prev


@pytest.fixture
def stubs(monkeypatch):
    holder = {'plandef': _plandef([FORM_ACTION, DR_ACTION])}
    monkeypatch.setattr('app.services.service_request_service.patient_service.get_patient',
                        lambda g: ({'id': g}, 200))
    monkeypatch.setattr('app.services.service_request_service.build_patient_excerpt',
                        lambda d: {'resourceType': 'Patient', 'id': PATIENT})
    monkeypatch.setattr('app.services.service_request_service.patient_service.'
                        'get_patient_clinic_orgs', lambda g: ([('clinic-984', UNIT)], 200))
    monkeypatch.setattr('app.services.service_request_service.plan_definition_service.'
                        'get_plan_definition', lambda g: (copy.deepcopy(holder['plandef']), 200))
    return holder


def _order(stubs, actions=None):
    """Create + finalize an order from a PlanDefinition. Returns (parent, children)."""
    if actions is not None:
        stubs['plandef'] = _plandef(actions)
    data, st = service_request_service.create_service_request(
        patient_guid=PATIENT, plan_definition_guid='pd-984', user_guid='clin-984',
        org_guid=UNIT, user_name='Dr Test', org_name='Enhet')
    assert st == 201, data
    fin, st = service_request_service.finalize_service_request(data['guid'], user_guid='clin-984')
    assert st == 200, fin
    parent = ServiceRequest.query.filter_by(guid=data['guid']).first()
    children = ServiceRequest.query.filter_by(based_on_guid=parent.guid).all()
    return parent, children


def _icd11(key=ICD11_KEY, source='icd11.pdhc'):
    return {'X-Source-Service': source, 'X-Service-Key': key,
            'Content-Type': 'application/json'}


def _complete(client, guid, conditions, headers=None):
    return client.post(f'/api/v1/internal/diagnosis-review/{guid}/complete',
                       json={'conditions': conditions}, headers=headers or _icd11())


CONDS = [{'id': 'cond-1', 'version_id': '2'}, {'id': 'cond-2', 'version_id': '1'}]


# ── creation ────────────────────────────────────────────────────────────


class TestCreation:

    def test_the_step_becomes_its_own_service_request(self, stubs):
        parent, children = _order(stubs)
        assert len(children) == 1
        c = children[0]
        assert c.kind == 'diagnosis-review'
        assert c.status == 'active'
        assert c.instantiates_canonical == CANON
        assert c.performer_type == 'clinician'
        assert c.patient_guid == PATIENT and c.requester_org_guid == UNIT
        assert c.contract_guid is None          # never a provider relationship
        assert c.forms == []

    def test_scope_extensions_are_copied_VERBATIM_and_only_those(self, stubs):
        _, (c,) = _order(stubs)
        assert c.code_scope == SCOPE_EXTS
        fhir = c.fhir_resource
        assert fhir['extension'] == SCOPE_EXTS
        assert fhir['instantiatesCanonical'] == [CANON]
        assert fhir['performerType'] == {'text': 'clinician'}
        assert fhir['subject'] == {'reference': f'Patient/{PATIENT}'}
        # the order it came from, and (2026-11-19) the shared CarePlan it inherits
        assert fhir['basedOn'] == [{'reference': f'ServiceRequest/{c.based_on_guid}'},
                                   {'reference': f'CarePlan/{c.care_plan_guid}', 'type': 'CarePlan'}]
        assert c.care_plan_guid
        assert fhir['occurrenceTiming'] == DR_ACTION['timingTiming']

    def test_work_link_default_and_configurable(self, app, stubs):
        _, (c,) = _order(stubs)
        assert c.to_dict()['work_link'] == f'https://icd11.pdhc.se/session/{c.guid}'
        app.config['ICD11_BASE_URL'] = 'https://icd11.test.example/'
        assert dr.work_link(c.guid) == f'https://icd11.test.example/session/{c.guid}'

    def test_the_order_itself_is_unchanged(self, stubs):
        parent, _ = _order(stubs)
        assert parent.kind is None and parent.status == 'active'
        assert parent.fhir_resource['instantiatesCanonical'] == [
            'https://plan.pdhc.se/api/v1/plandefinitions/pd-984']
        assert 'performerType' not in parent.fhir_resource

    def test_creation_is_idempotent(self, stubs):
        parent, children = _order(stubs)
        assert dr.create_for_order(parent) == []
        assert ServiceRequest.query.filter_by(based_on_guid=parent.guid).count() == 1

    def test_one_service_request_per_step_including_nested(self, stubs):
        second = copy.deepcopy(DR_ACTION)
        second['extension'] = [{'url': SCOPE_URL, 'valueString': '8A0'}]
        group = {'title': 'Grupp', 'action': [second]}
        _, children = _order(stubs, [DR_ACTION, group])
        scopes = sorted(dr.scope_prefixes(c.code_scope)[0] for c in children)
        assert scopes == ['5A1', '8A0']

    def test_a_step_without_scope_refuses_the_finalize_by_name(self, stubs):
        bad = copy.deepcopy(DR_ACTION)
        bad['extension'] = []
        stubs['plandef'] = _plandef([bad])
        data, _ = service_request_service.create_service_request(
            patient_guid=PATIENT, plan_definition_guid='pd-984', user_guid='u', org_guid=UNIT)
        body, st = service_request_service.finalize_service_request(data['guid'])
        assert st == 409 and body['code'] == 'diagnosis_review_scope_missing'
        assert ServiceRequest.query.filter_by(guid=data['guid']).first().status == 'draft'
        assert ServiceRequest.query.filter_by(kind='diagnosis-review').count() == 0


class TestFormActionsUnchanged:

    def test_a_plan_with_only_form_actions_creates_no_review(self, stubs):
        parent, children = _order(stubs, [FORM_ACTION])
        assert children == []
        assert parent.status == 'active' and parent.kind is None
        assert parent.to_dict()['kind'] is None
        assert 'work_link' not in parent.to_dict()

    def test_order_with_a_form_still_goes_to_1177(self, app, stubs):
        parent, (child,) = _order(stubs)
        db.session.add(ServiceRequestForm(service_request_guid=parent.guid, form_guid='form-984',
                                          form_snapshot={'resourceType': 'Questionnaire',
                                                         'item': []}))
        db.session.commit()
        app.config['FORMS_1177_API_KEY'] = 'k'
        from app.services import push_service
        with patch.object(push_service.http_requests, 'post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {}
            push_service.push_all_matches(parent.guid)
        assert post.called    # the form path is untouched by #984
        app.config['FORMS_1177_API_KEY'] = ''


# ── never dispatched ────────────────────────────────────────────────────


class TestNeverDispatched:

    @pytest.fixture
    def child(self, stubs):
        return _order(stubs)[1][0]

    @pytest.fixture
    def net(self, monkeypatch):
        """Every outbound transport a dispatch could use, recorded."""
        from app.services import push_service, webhook_dispatcher, contract_service
        calls = []
        monkeypatch.setattr(push_service.http_requests, 'post',
                            lambda *a, **k: calls.append(('push', a)) or (_ for _ in ()).throw(AssertionError('push')))
        monkeypatch.setattr(webhook_dispatcher.http_requests, 'post',
                            lambda *a, **k: calls.append(('webhook', a)))
        monkeypatch.setattr(contract_service, 'find_matching_contracts',
                            lambda **k: calls.append(('contract', k)) or (
                                [{'id': 'c-984', 'title': 'C', 'provider_org_guid': 'p-984'}], 200))
        return calls

    def test_push_all_refuses(self, app, child, net):
        app.config['FORMS_1177_API_KEY'] = 'k'
        from app.services.push_service import push_all_matches
        body, st = push_all_matches(child.guid)
        app.config['FORMS_1177_API_KEY'] = ''
        assert st == 409 and body['code'] == 'diagnosis_review_not_dispatchable'
        assert net == []

    def test_push_to_a_provider_refuses_even_with_a_match(self, child, net):
        m = ServiceRequestContractMatch(service_request_guid=child.guid, contract_guid='c',
                                        provider_org_guid='p', status='pending')
        db.session.add(m); db.session.commit()
        from app.services.push_service import push_to_provider
        body, st = push_to_provider(m.guid)
        assert st == 409 and net == []
        assert ServiceRequestContractMatch.query.filter_by(guid=m.guid).first().status == 'pending'

    def test_patient_app_1177_refuses(self, app, child, net):
        app.config['FORMS_1177_API_KEY'] = 'k'
        from app.services.push_service import _push_forms_to_1177
        out = _push_forms_to_1177(child)
        app.config['FORMS_1177_API_KEY'] = ''
        assert out['status'] == 'refused' and net == []

    def test_provider_match_dispatch_and_download_refuse(self, child, net):
        from app.services import match_service, provider_feed_service
        assert match_service.find_eligible_providers(child.guid) == ({'eligible': []}, 200)
        assert match_service.find_and_create_matches(child.guid)[1] == 409
        assert match_service.dispatch_to_provider(child.guid, 'c', 'p')[1] == 409
        assert provider_feed_service.download_bundle(child.guid, 'p', 'c')[1] == 409
        assert ServiceRequestContractMatch.query.filter_by(
            service_request_guid=child.guid).count() == 0
        assert net == []

    def test_no_webhook_is_enqueued(self, child, net):
        from app.services import webhook_dispatcher
        assert webhook_dispatcher.enqueue_service_request_dispatched(
            child, 'p', 'https://p.example/hook') is None
        service_request_service._enqueue_dispatch_webhooks(child, 'c')
        assert WebhookDelivery.query.filter_by(service_request_guid=child.guid).count() == 0
        assert net == []

    def test_api_push_route_refuses(self, client, child, net):
        r = client.post(f'/api/v1/ServiceRequest/{child.guid}/push')
        assert r.status_code == 409
        assert r.get_json()['code'] == 'diagnosis_review_not_dispatchable'
        assert net == []


# ── icd11.pdhc reads it ─────────────────────────────────────────────────


class TestServiceRead:

    def test_icd11_reads_patient_status_canonical_scope(self, client, stubs):
        _, (c,) = _order(stubs)
        r = client.get(f'/api/v1/internal/diagnosis-review/{c.guid}', headers=_icd11())
        assert r.status_code == 200
        b = r.get_json()
        assert b['patient_guid'] == PATIENT and b['status'] == 'active'
        assert b['instantiates_canonical'] == CANON
        assert b['code_scope'] == ['5A1', 'BA0']
        assert b['fhir_resource']['extension'] == SCOPE_EXTS
        assert b['work_link'].endswith(f'/session/{c.guid}')

    @pytest.mark.parametrize('headers', [
        {},
        {'X-Service-Key': INTERNAL_KEY},                         # gateway's shared key
        {'X-Source-Service': 'icd11.pdhc', 'X-Service-Key': 'wrong'},
        {'X-Source-Service': 'gateway.pdhc', 'X-Service-Key': ICD11_KEY},
        {'X-Source-Service': 'icd11.pdhc'},
    ])
    def test_anything_but_icd11s_key_is_refused(self, client, stubs, headers):
        _, (c,) = _order(stubs)
        r = client.get(f'/api/v1/internal/diagnosis-review/{c.guid}', headers=headers)
        assert r.status_code == 401
        assert 'patient_guid' not in (r.get_json() or {})

    def test_unset_key_admits_nobody(self, app, client, stubs):
        _, (c,) = _order(stubs)
        app.config['ICD11_PDHC_SERVICE_KEY'] = ''
        r = client.get(f'/api/v1/internal/diagnosis-review/{c.guid}',
                       headers=_icd11(key=''))
        assert r.status_code == 401

    def test_an_order_sr_is_refused_by_name_without_its_data(self, client, stubs):
        parent, _ = _order(stubs)
        r = client.get(f'/api/v1/internal/diagnosis-review/{parent.guid}', headers=_icd11())
        assert r.status_code == 409
        assert r.get_json() == {'code': 'not_diagnosis_review',
                                'message': 'ServiceRequest is not a diagnosis-review '
                                           'ServiceRequest'}

    def test_unknown_guid_404(self, client):
        r = client.get(f'/api/v1/internal/diagnosis-review/{uuid.uuid4()}', headers=_icd11())
        assert r.status_code == 404

    def test_icd11_key_opens_no_other_internal_endpoint(self, client, stubs):
        _, (c,) = _order(stubs)
        for path in (f'/api/v1/internal/service-request/{c.guid}/context',):
            assert client.get(path, headers=_icd11()).status_code == 401
        assert client.post(f'/api/v1/internal/service-request/{c.guid}/complete',
                           headers=_icd11()).status_code == 401

    def test_icd11_is_read_only_unless_the_route_grants_the_write(self, app):
        from app.middleware.auth_middleware import named_service_outcome
        allowed = frozenset({'icd11.pdhc'})
        with app.test_request_context():
            for m in ('POST', 'PUT', 'PATCH', 'DELETE'):
                body, st = named_service_outcome('icd11.pdhc', ICD11_KEY, m, allowed)
                assert (st, body['code']) == (403, 'service_read_only'), m
            assert named_service_outcome('icd11.pdhc', ICD11_KEY, 'GET', allowed) == (
                None, 'icd11.pdhc')
            assert named_service_outcome('icd11.pdhc', ICD11_KEY, 'POST', allowed,
                                         write_grant=allowed) == (None, 'icd11.pdhc')


# ── icd11.pdhc completes it ─────────────────────────────────────────────


class TestCompletion:

    def test_happy_path(self, client, stubs):
        _, (c,) = _order(stubs)
        r = _complete(client, c.guid, CONDS)
        assert r.status_code == 200, r.get_json()
        b = r.get_json()
        assert b['status'] == 'completed' and b['already_completed'] is False
        row = ServiceRequest.query.filter_by(guid=c.guid).first()
        assert row.status == 'completed'
        assert row.completion_record['conditions'] == CONDS
        assert row.completion_record['source'] == 'icd11.pdhc'
        assert row.fhir_resource['status'] == 'completed'
        assert {'reference': {'reference': 'Condition/cond-1/_history/2'}} in \
            row.fhir_resource['supportingInfo']

    def test_goes_through_mark_service_request_completed(self, client, stubs):
        _, (c,) = _order(stubs)
        from app.services import completion_service
        real = completion_service.mark_service_request_completed
        with patch.object(completion_service, 'mark_service_request_completed',
                          side_effect=real) as spy:
            assert _complete(client, c.guid, CONDS).status_code == 200
        assert spy.call_args.kwargs['source'] == 'icd11.pdhc'
        assert spy.call_args.kwargs['cdr_conditions'] == CONDS

    def test_repeat_is_idempotent(self, client, stubs):
        _, (c,) = _order(stubs)
        first = _complete(client, c.guid, CONDS).get_json()
        r = _complete(client, c.guid, list(reversed(CONDS)))
        assert r.status_code == 200 and r.get_json()['already_completed'] is True
        row = ServiceRequest.query.filter_by(guid=c.guid).first()
        assert row.completion_record == first['completion_record']

    def test_repeat_with_other_conditions_is_refused_by_name(self, client, stubs):
        _, (c,) = _order(stubs)
        _complete(client, c.guid, CONDS)
        r = _complete(client, c.guid, [{'id': 'cond-9', 'version_id': '1'}])
        assert r.status_code == 409
        assert r.get_json()['code'] == 'already_completed_with_other_conditions'

    def test_wrong_kind(self, client, stubs):
        parent, _ = _order(stubs)
        r = _complete(client, parent.guid, CONDS)
        assert r.status_code == 409 and r.get_json()['code'] == 'not_diagnosis_review'
        assert ServiceRequest.query.filter_by(guid=parent.guid).first().status == 'active'
        # and the service function refuses it too, whoever calls it
        from app.services.completion_service import mark_service_request_completed
        body, st = mark_service_request_completed(parent.guid, source='icd11.pdhc',
                                                  cdr_conditions=CONDS)
        assert (st, body['code']) == (409, 'not_diagnosis_review')

    @pytest.mark.parametrize('status', ['draft', 'revoked', 'archived'])
    def test_inactive(self, client, stubs, status):
        _, (c,) = _order(stubs)
        c.status = status; db.session.commit()
        r = _complete(client, c.guid, CONDS)
        assert r.status_code == 409 and r.get_json()['code'] == 'service_request_not_active'
        assert ServiceRequest.query.filter_by(guid=c.guid).first().status == status

    def test_wrong_caller_gateways_shared_key(self, client, stubs):
        _, (c,) = _order(stubs)
        r = client.post(f'/api/v1/internal/diagnosis-review/{c.guid}/complete',
                        json={'conditions': CONDS}, headers={'X-Service-Key': INTERNAL_KEY})
        assert r.status_code == 401

    def test_wrong_caller_through_gateways_own_complete_door(self, client, stubs):
        _, (c,) = _order(stubs)
        r = client.post(f'/api/v1/internal/service-request/{c.guid}/complete',
                        headers={'X-Service-Key': INTERNAL_KEY})
        assert r.status_code == 403 and r.get_json()['code'] == 'caller_not_icd11'
        assert ServiceRequest.query.filter_by(guid=c.guid).first().status == 'active'

    def test_wrong_caller_another_named_service(self, app, client, stubs, monkeypatch):
        from app.middleware import auth_middleware
        monkeypatch.setitem(auth_middleware.KNOWN_SERVICE_KEYS, 'other.pdhc', 'OTHER_KEY_984')
        app.config['OTHER_KEY_984'] = 'other-key'
        _, (c,) = _order(stubs)
        r = _complete(client, c.guid, CONDS, headers=_icd11(key='other-key',
                                                            source='other.pdhc'))
        assert r.status_code == 403 and r.get_json()['code'] == 'service_not_permitted'
        assert ServiceRequest.query.filter_by(guid=c.guid).first().status == 'active'

    def test_wrong_caller_at_the_service_function(self, stubs):
        _, (c,) = _order(stubs)
        from app.services.completion_service import mark_service_request_completed
        body, st = mark_service_request_completed(c.guid, source='gateway.pdhc',
                                                  cdr_conditions=CONDS)
        assert (st, body['code']) == (403, 'caller_not_icd11')

    @pytest.mark.parametrize('body', [
        {}, {'conditions': 'x'}, {'conditions': [{'id': 'c'}]},
        {'conditions': [{'version_id': '1'}]},
    ])
    def test_invalid_body(self, client, stubs, body):
        _, (c,) = _order(stubs)
        r = client.post(f'/api/v1/internal/diagnosis-review/{c.guid}/complete',
                        json=body, headers=_icd11())
        assert r.status_code == 400 and r.get_json()['code'] == 'invalid_conditions'
        assert ServiceRequest.query.filter_by(guid=c.guid).first().status == 'active'

    def test_empty_list_is_a_review_with_no_change(self, client, stubs):
        _, (c,) = _order(stubs)
        assert _complete(client, c.guid, []).status_code == 200

    def test_revoking_the_order_revokes_its_open_review(self, stubs):
        parent, (c,) = _order(stubs)
        service_request_service.revoke_service_request(parent.guid)
        assert ServiceRequest.query.filter_by(guid=c.guid).first().status == 'revoked'


# ── what clinicians see ─────────────────────────────────────────────────


def _web(client, url):
    import app.routes.service_requests as mod
    blob = {'user_guid': 'u', 'email': 'e', 'user_type': 'professional', 'is_su_admin': True,
            'display_name': 'T', 'session_phases': ['request'], 'affiliations': []}
    with patch.object(mod, 'get_current_access_blob', return_value=blob), \
         patch.object(mod, 'get_current_user_guid', return_value='u'), \
         patch('app.services.contract_service.find_matching_contracts',
               return_value=([], 200)):
        return client.get(url)


class TestClinicianViews:

    def test_timeline_lines_in_swedish_with_code_area(self, stubs):
        parent, (c,) = _order(stubs)
        lines = dr.timeline_activities(parent.plan_definition_snapshot)
        assert [l['title'] for l in lines] == ['Diagnosgenomgång (ICD-11) — 5A1, BA0']
        assert dr.timeline_activities(c.plan_definition_snapshot)[0]['title'] == \
            'Diagnosgenomgång (ICD-11) — 5A1, BA0'

    def test_list_view(self, client, stubs):
        _, (c,) = _order(stubs)
        html = _web(client, '/service-requests').get_data(as_text=True)
        assert 'Diagnosgenomgång (ICD-11)' in html and '5A1, BA0' in html
        assert f'https://icd11.pdhc.se/session/{c.guid}' in html

    def test_detail_views(self, client, stubs):
        parent, (c,) = _order(stubs)
        html = _web(client, f'/service-requests/{c.guid}').get_data(as_text=True)
        assert 'Diagnosgenomgång (ICD-11)' in html and '5A1, BA0' in html
        assert 'Provider Delivery Blob' not in html
        html = _web(client, f'/service-requests/{parent.guid}').get_data(as_text=True)
        assert 'Diagnosgenomgång (ICD-11)' in html and f'/session/{c.guid}' in html

    def test_timeline_view(self, client, stubs):
        parent, (c,) = _order(stubs)
        for g in (parent.guid, c.guid):
            r = _web(client, f'/service-requests/{g}/timeline')
            assert r.status_code == 200
            assert 'Diagnosgenomgång (ICD-11) — 5A1, BA0' in r.get_data(as_text=True)

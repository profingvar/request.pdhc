"""#1043 — what the patient app needs from request.pdhc.

A. care can order a Questionnaire by canonical url + version;
B. the provider download exposes everything the patient backend must render
   (contract plans/patient_app_contract.md §3.1), additively, and the feed
   carries the patient guid and can be narrowed to one patient.

The provider routes are exercised with auth ON and a real PAT. Only the
outbound HTTP boundary is patched: `requests.get` as context_service calls
plan.pdhc.
"""
import copy
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch, ServiceRequestForm,
)
from app.services import context_service as cs
from app.services import questionnaire_service as qs
from app.services.pat_service import issue_pat

C_SYS, C_DIA, C_MOOD, C_NOTE = (str(uuid.uuid4()) for _ in range(4))
RT_NUM, RT_CHOICE, RT_TEXT = 'rt-num', 'rt-choice', 'rt-text'
UNIT_MMHG, VS_MOOD = 'unit-mmhg', str(uuid.uuid4())

EPS_URL = 'https://plan.pdhc.se/fhir/Questionnaire/eps-patient'
EPS_Q = {
    'resourceType': 'Questionnaire', 'url': EPS_URL, 'version': '1',
    'title': 'EPS: patientens uppgifter', 'status': 'active',
    'item': [
        {'linkId': 'allergy', 'type': 'group', 'text': 'Allergier', 'item': [
            {'linkId': 'allergy.substance', 'type': 'string', 'text': 'Ämne'}]},
        {'linkId': 'medication.name', 'type': 'string', 'text': 'Läkemedel'},
        {'linkId': 'contact.phone', 'type': 'choice', 'text': 'Kontaktväg',
         'answerOption': [{'valueCoding': {'code': 'sms', 'display': 'SMS'}}]},
    ],
}

SNAP = {'title': 'Blodtryck hemma', 'version': '2.0.0', 'activities': [
    {'activity_guid': 'a-bp', 'sort_order': 0, 'title': 'Ta blodtrycket',
     'description': 'Sitt ned i fem minuter först.', 'performer_type': 'Patient',
     'timing_type': 'repeat', 'timing_frequency': 1, 'timing_period': 1,
     'timing_period_unit': 'd', 'timing_bounds_mode': 'count', 'timing_bounds_count': 14,
     'transactions': [
         {'guid': 't-sys', 'transaction_guid': 't-sys', 'sort_order': 0,
          'concept_guid': C_SYS, 'concept_name': 'bp_systolic',
          'response_type': 'numeric', 'unit': 'mmHg', 'requirement_type': 'required',
          'range_min': 100, 'range_max': 140},
         # an UNENRICHED transaction: everything must come from plan.pdhc
         {'guid': 't-dia', 'transaction_guid': 't-dia', 'sort_order': 1,
          'concept_guid': C_DIA, 'concept_name': 'bp_diastolic',
          'requirement_type': 'optional'},
     ]},
    {'activity_guid': 'a-mood', 'sort_order': 1, 'title': 'Hur mår du?',
     'timing_type': 'once',
     'transactions': [
         {'guid': 't-mood', 'transaction_guid': 't-mood', 'concept_guid': C_MOOD,
          'concept_name': 'mood', 'requirement_type': 'required'}]},
]}


def _plan(url, **kw):
    """plan.pdhc as request reads it."""
    r = MagicMock(status_code=200)
    r.raise_for_status.return_value = None
    if url.endswith('/lookup/response-types'):
        body = [{'guid': RT_NUM, 'response_type_name': 'Numerical'},
                {'guid': RT_CHOICE, 'response_type_name': 'Single choice'},
                {'guid': RT_TEXT, 'response_type_name': 'Free text'}]
    elif url.endswith('/lookup/units'):
        body = [{'guid': UNIT_MMHG, 'unit_name': 'mmHg'}]
    elif url.endswith('/concepts'):
        body = {'total': 4, 'items': [
            {'guid': C_SYS, 'concept_name': 'bp_systolic',
             'concept_display_text': 'Systoliskt blodtryck', 'response_type': RT_NUM,
             'unit': UNIT_MMHG, 'range_low': 40, 'range_high': 300},
            {'guid': C_DIA, 'concept_name': 'bp_diastolic',
             'concept_display_text': 'Diastoliskt blodtryck', 'response_type': RT_NUM,
             'unit': UNIT_MMHG, 'range_low': 20, 'range_high': 200},
            {'guid': C_MOOD, 'concept_name': 'mood', 'concept_display_text': 'Humör',
             'response_type': RT_CHOICE, 'valueset': VS_MOOD},
            {'guid': C_NOTE, 'concept_name': 'note', 'response_type': RT_TEXT},
        ]}
    elif url.endswith(f'/lookup/valuesets/{VS_MOOD}/values'):
        body = [{'guid': 'v-good', 'value_name': 'good', 'value_display_text': 'Bra', 'sort_order': 1},
                {'guid': 'v-bad', 'value_name': 'bad', 'value_display_text': 'Dåligt', 'sort_order': 2}]
    else:
        raise AssertionError(f'unexpected plan call: {url}')
    r.json.return_value = body
    return r


@pytest.fixture
def plan(app):
    cs._plan_cache.update(ts=0.0, rt={}, rt_name={}, unit={}, scale={},
                          valueset={}, label={})
    cs._options_cache.clear()
    with patch.object(cs.requests, 'get', side_effect=_plan) as g:
        yield g
    cs._plan_cache.update(ts=0.0, rt={}, rt_name={}, unit={}, scale={},
                          valueset={}, label={})
    cs._options_cache.clear()


@pytest.fixture
def auth_on(app):
    app.config['AUTH_DISABLED'] = False
    yield
    app.config['AUTH_DISABLED'] = True


def _order(provider, patient=None, snapshot=None, status='active', contract=None):
    sr = ServiceRequest(
        guid=str(uuid.uuid4()), status=status,
        patient_guid=patient or str(uuid.uuid4()),
        plan_definition_guid=str(uuid.uuid4()),
        plan_definition_snapshot=copy.deepcopy(snapshot if snapshot is not None else SNAP),
        contract_guid=contract or str(uuid.uuid4()),
        requester_user_guid=str(uuid.uuid4()),
        requester_org_guid=str(uuid.uuid4()), requester_org_name='Vårdcentralen Norr',
        care_plan_guid='cp-1',
        fhir_resource={'resourceType': 'ServiceRequest', 'status': 'active'})
    db.session.add(sr)
    db.session.flush()
    db.session.add(ServiceRequestContractMatch(
        service_request_guid=sr.guid, contract_guid=sr.contract_guid,
        provider_org_guid=provider, status='sent'))
    db.session.commit()
    return sr


def _pat(provider, contract=None, scopes='read,write,patient_generated'):
    data, status = issue_pat(provider_org_guid=provider,
                             contract_guid=contract or str(uuid.uuid4()),
                             scopes=scopes, created_by_user_guid='test')
    assert status == 201
    return {'X-Provider-Token': data['raw_token']}


# ── B. the feed ──────────────────────────────────────────────────────────

def test_feed_needs_a_pat(client, auth_on):
    assert client.get('/api/v1/provider/feed').status_code == 401


def test_feed_items_carry_the_patient_guid(client, app, auth_on):
    prov = str(uuid.uuid4())
    with app.app_context():
        sr = _order(prov)
        guid, patient, h = sr.guid, sr.patient_guid, _pat(prov)
    r = client.get('/api/v1/provider/feed', headers=h)
    assert r.status_code == 200
    [item] = r.get_json()['items']
    assert (item['service_request_guid'], item.get('patient_guid')) == (guid, patient)


def test_feed_can_be_narrowed_to_one_patient(client, app, auth_on):
    prov, anna, bo = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with app.app_context():
        a1, a2, b1 = (_order(prov, anna).guid, _order(prov, anna).guid,
                      _order(prov, bo).guid)
        h = _pat(prov)
    everything = client.get('/api/v1/provider/feed', headers=h).get_json()['items']
    assert {i['service_request_guid'] for i in everything} == {a1, a2, b1}
    only = client.get(f'/api/v1/provider/feed?patient_guid={anna}', headers=h).get_json()['items']
    assert {i['service_request_guid'] for i in only} == {a1, a2}
    assert {i.get('patient_guid') for i in only} == {anna}


def test_the_patient_filter_never_widens(client, app, auth_on):
    """Another provider's PAT, asking for a patient it has no order for,
    gets nothing — the filter narrows the PAT's own matches only."""
    prov, other, anna = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with app.app_context():
        _order(prov, anna)
        h_other = _pat(other)
    r = client.get(f'/api/v1/provider/feed?patient_guid={anna}', headers=h_other)
    assert r.status_code == 200 and r.get_json()['items'] == []
    assert client.get('/api/v1/provider/feed', headers=h_other).get_json()['items'] == []


# ── B. the download ──────────────────────────────────────────────────────

LEGACY_TX_KEYS = ['transaction_guid', 'concept_guid', 'concept_name', 'unit',
                  'response_type', 'requirement_type', 'range_min', 'range_max',
                  'recommended_range_min', 'recommended_range_max',
                  'action_limit_source']
LEGACY_TOP_KEYS = ['fhir_resource', 'grant_token', 'service_request_guid',
                   'patient_guid', 'contract_guid', 'provider_org_guid',
                   'sr_status', 'is_open', 'period_start', 'period_end',
                   'care_plan_guid', 'care_plan']


def _download(client, app, snapshot=None):
    prov = str(uuid.uuid4())
    with app.app_context():
        sr = _order(prov, snapshot=snapshot)
        guid, patient, contract = sr.guid, sr.patient_guid, sr.contract_guid
        h = _pat(prov, contract)
    r = client.get(f'/api/v1/provider/download/{guid}', headers=h)
    assert r.status_code == 200, r.get_json()
    return r.get_json(), patient


def test_download_needs_a_pat_and_a_match(client, app, auth_on, plan):
    with app.app_context():
        guid = _order(str(uuid.uuid4())).guid
        stranger = _pat(str(uuid.uuid4()))
    assert client.get(f'/api/v1/provider/download/{guid}').status_code == 401
    assert client.get(f'/api/v1/provider/download/{guid}', headers=stranger).status_code == 403


def test_download_exposes_what_the_patient_backend_renders(client, app, auth_on, plan):
    d, patient = _download(client, app)
    assert d['patient_guid'] == patient
    assert d.get('title') == 'Blodtryck hemma'
    assert d.get('requesting_org_name') == 'Vårdcentralen Norr'
    bp, mood = d['care_plan']['activities']
    assert (bp['title'], bp['description']) == ('Ta blodtrycket', 'Sitt ned i fem minuter först.')
    assert bp['timing'] == {'repeat': {'frequency': 1, 'period': 1, 'periodUnit': 'd', 'count': 14}}
    sys_, dia = bp['transactions']
    # frozen values win; label and scale come from the concept
    assert {k: sys_.get(k) for k in ('transaction_guid', 'label', 'response_type',
            'response_type_name', 'unit', 'scale_min', 'scale_max', 'options',
            'required', 'range_min', 'range_max')} == {
        'transaction_guid': 't-sys', 'label': 'Systoliskt blodtryck',
        'response_type': 'numeric', 'response_type_name': 'Numerical',
        'unit': 'mmHg', 'scale_min': 40, 'scale_max': 300, 'options': None,
        'required': True, 'range_min': 100, 'range_max': 140}
    # the unenriched transaction is described from plan.pdhc
    assert {k: dia.get(k) for k in ('label', 'response_type', 'unit', 'scale_min',
            'scale_max', 'required')} == {
        'label': 'Diastoliskt blodtryck', 'response_type': 'numeric',
        'unit': 'mmHg', 'scale_min': 20, 'scale_max': 200, 'required': False}
    [m] = mood['transactions']
    assert m.get('response_type') == 'categorical'
    assert m.get('options') == [{'value': 'good', 'label': 'Bra', 'code': 'v-good'},
                                {'value': 'bad', 'label': 'Dåligt', 'code': 'v-bad'}]
    assert d.get('questionnaires') == []


def test_download_is_additive_for_existing_consumers(client, app, auth_on):
    """provider1 and cgm read the pre-#1043 keys. With plan.pdhc unreachable
    (the suite default) every one of them is present with the value the old
    code produced; #1043 only adds keys."""
    snap = {'title': 'MMD_plan', 'version': '1.0.0', 'activities': [
        {'activity_guid': 'a-1', 'sort_order': 0, 'title': 'CGM', 'timing_type': 'once',
         'transactions': [{'transaction_guid': 't-1', 'concept_guid': 'c-1',
                           'concept_name': 'CGM', 'unit': 'mmol/L', 'response_type': 'numeric',
                           'requirement_type': 'required', 'range_min': 4.0, 'range_max': 8.0,
                           'recommended_range_min': 3.9, 'recommended_range_max': 10.0,
                           'action_limit_source': 'plan'}]}]}
    d, _ = _download(client, app, snapshot=snap)
    assert [k for k in LEGACY_TOP_KEYS if k not in d] == []
    [tx] = d['care_plan']['activities'][0]['transactions']
    assert {k: tx.get(k, '<missing>') for k in LEGACY_TX_KEYS} == {
        'transaction_guid': 't-1', 'concept_guid': 'c-1', 'concept_name': 'CGM',
        'unit': 'mmol/L', 'response_type': 'numeric', 'requirement_type': 'required',
        'range_min': 4.0, 'range_max': 8.0, 'recommended_range_min': 3.9,
        'recommended_range_max': 10.0, 'action_limit_source': 'plan'}
    assert set(d) - set(LEGACY_TOP_KEYS) == {
        'title', 'requesting_org_guid', 'requesting_org_name', 'questionnaires'}
    assert set(tx) - set(LEGACY_TX_KEYS) == {
        'label', 'response_type_name', 'scale_min', 'scale_max', 'options', 'required'}


def test_options_are_not_cached_when_plan_fails(app, plan):
    """A plan.pdhc blip must not be remembered as "no alternatives"."""
    import requests as rq
    with app.app_context():
        cs._refresh_plan_maps()

        def down(url, **kw):
            raise rq.ConnectionError('down')
        with patch.object(cs.requests, 'get', side_effect=down):
            assert cs._plan_concept_options(C_MOOD) is None
        assert [o['value'] for o in cs._plan_concept_options(C_MOOD) or []] == ['good', 'bad']


def test_a_new_order_freezes_label_and_options(app, plan):
    with app.app_context():
        snap = cs.enrich_snapshot_concepts(copy.deepcopy(SNAP))
    mood = snap['activities'][1]['transactions'][0]
    assert mood.get('concept_display_text') == 'Humör'
    assert [o['value'] for o in mood.get('options') or []] == ['good', 'bad']


# ── A(c). a Questionnaire by canonical url + version ─────────────────────

def _draft(app):
    sr = ServiceRequest(
        guid=str(uuid.uuid4()), status='draft', patient_guid=str(uuid.uuid4()),
        plan_definition_guid=str(uuid.uuid4()),
        plan_definition_snapshot={'title': 'EPS-formulär', 'activities': []},
        contract_guid=str(uuid.uuid4()), requester_user_guid=str(uuid.uuid4()))
    db.session.add(sr)
    db.session.commit()
    return sr.guid


def test_import_is_idempotent_and_a_version_is_immutable(app):
    with app.app_context():
        row, created = qs.import_questionnaire(copy.deepcopy(EPS_Q), created_by='t')
        again, created_again = qs.import_questionnaire(copy.deepcopy(EPS_Q), created_by='t')
        assert (created, created_again, again.guid) == (True, False, row.guid)
        changed = copy.deepcopy(EPS_Q)
        changed['item'][1]['text'] = 'Mediciner'
        with pytest.raises(qs.QuestionnaireInvalid) as e:
            qs.import_questionnaire(changed)
        assert e.value.code == 'questionnaire_version_conflict'
        changed['version'] = '2'
        v2, _ = qs.import_questionnaire(changed)
        assert qs.resolve(EPS_URL).guid == v2.guid            # latest
        assert qs.resolve(f'{EPS_URL}|1').guid == row.guid    # pinned


@pytest.mark.parametrize('broken,code', [
    ({'resourceType': 'Patient'}, 'not_a_questionnaire'),
    ({'resourceType': 'Questionnaire', 'version': '1', 'item': [{}]}, 'questionnaire_url_missing'),
    ({'resourceType': 'Questionnaire', 'url': 'https://x/Questionnaire/y', 'item': [{}]}, 'questionnaire_version_missing'),
    ({'resourceType': 'Questionnaire', 'url': 'https://x/Questionnaire/y', 'version': '1'}, 'questionnaire_has_no_items'),
])
def test_import_refuses_by_name(app, broken, code):
    with app.app_context(), pytest.raises(qs.QuestionnaireInvalid) as e:
        qs.import_questionnaire(broken)
    assert e.value.code == code


def test_cli_import(app, tmp_path):
    f = tmp_path / 'eps.json'
    f.write_text(json.dumps(EPS_Q), encoding='utf-8')
    runner = app.test_cli_runner()
    first = runner.invoke(args=['questionnaire', 'import', str(f)])
    assert first.exit_code == 0 and first.output.startswith('IMPORTED: ' + EPS_URL + '|1')
    assert runner.invoke(args=['questionnaire', 'import', str(f)]).output.startswith('UNCHANGED')
    assert EPS_URL + '|1' in runner.invoke(args=['questionnaire', 'list']).output


def test_order_a_questionnaire_by_canonical_and_download_it_inline(client, app, auth_on):
    """Care attaches the Questionnaire by url to a draft, finalizes, and the
    provider downloads it inline — with plan.pdhc unreachable throughout,
    because the JSON is request.pdhc's own frozen copy."""
    prov = str(uuid.uuid4())
    with app.app_context():
        qs.import_questionnaire(copy.deepcopy(EPS_Q))
        guid = _draft(app)
    app.config['AUTH_DISABLED'] = True          # the staff side (dev bypass)
    with patch('app.api.service_requests.patient_access.evaluate',
               return_value=MagicMock(allowed=True)):
        r = client.post(f'/api/v1/ServiceRequest/{guid}/forms',
                        json={'questionnaire_url': EPS_URL, 'questionnaire_version': '1'})
        assert r.status_code == 201, r.get_json()
        assert (r.get_json()['questionnaire_url'], r.get_json()['questionnaire_version']) == (EPS_URL, '1')
        dup = client.post(f'/api/v1/ServiceRequest/{guid}/forms',
                          json={'questionnaire_url': f'{EPS_URL}|1'})
        assert dup.status_code == 409
        missing = client.post(f'/api/v1/ServiceRequest/{guid}/forms',
                              json={'questionnaire_url': 'https://plan.pdhc.se/fhir/Questionnaire/nope'})
        assert (missing.status_code, missing.get_json()['code']) == (404, 'questionnaire_not_found')
        from app.services import form_service
        with patch.object(form_service, 'get_questionnaire',
                          return_value=({}, 502)) as asked_plan:
            fin = client.post(f'/api/v1/ServiceRequest/{guid}/finalize')
        assert fin.status_code == 200, fin.get_json()
        assert asked_plan.call_count == 0, 'plan.pdhc does not hold this Questionnaire'
    app.config['AUTH_DISABLED'] = False         # the provider side, PAT only
    with app.app_context():
        sr = ServiceRequest.query.filter_by(guid=guid).one()
        db.session.add(ServiceRequestContractMatch(
            service_request_guid=guid, contract_guid=sr.contract_guid,
            provider_org_guid=prov, status='sent'))
        db.session.commit()
        h = _pat(prov, sr.contract_guid)
    d = client.get(f'/api/v1/provider/download/{guid}', headers=h).get_json()
    assert len(d.get('questionnaires') or []) == 1, 'the Questionnaire travels inline'
    q = d['questionnaires'][0]
    assert (q['url'], q['version'], q['title']) == (EPS_URL, '1', 'EPS: patientens uppgifter')
    assert q['questionnaire'] == EPS_Q          # exactly as imported
    # and still contained in the FHIR resource, as plan-catalogue forms are
    contained = [c for c in d['fhir_resource']['contained']
                 if c.get('resourceType') == 'Questionnaire']
    assert [c['url'] for c in contained] == [EPS_URL]


def test_the_form_picker_guid_attaches_the_registry_questionnaire(app):
    """The web pickers post the registry row's guid as `form_guid`."""
    from app.services import service_request_service as srs
    with app.app_context():
        row, _ = qs.import_questionnaire(copy.deepcopy(EPS_Q))
        guid = _draft(app)
        assert {'guid': row.guid, 'questionnaire_url': EPS_URL} .items() <= \
            qs.catalogue_entries()[0].items()
        data, status = srs.add_form_to_request(guid, row.guid)
        assert status == 201
        srf = ServiceRequestForm.query.filter_by(service_request_guid=guid).one()
        assert (srf.questionnaire_url, srf.form_snapshot) == (EPS_URL, EPS_Q)
        assert data['questionnaire_version'] == '1'


def test_a_download_asks_plan_once_when_plan_is_down(client, app, auth_on):
    """With plan.pdhc down and nothing cached, describing N transactions must
    not wait out a timeout per lookup: one refresh attempt for the order."""
    import requests as rq
    cs._plan_cache.update(ts=0.0, rt={}, rt_name={}, unit={}, scale={}, valueset={}, label={})
    calls = []

    def down(url, **kw):
        calls.append(url)
        raise rq.ConnectionError('down')
    with patch.object(cs.requests, 'get', side_effect=down):
        d, _ = _download(client, app)
    assert len(calls) == 1, calls
    assert [t.get('label') for a in d['care_plan']['activities'] for t in a['transactions']] == [
        'bp_systolic', 'bp_diastolic', 'mood']      # falls back to the frozen name

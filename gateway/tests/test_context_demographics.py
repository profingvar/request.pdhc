"""SR context enriches with patient demographics resolved from ips.

gateway populates CDR1's patient row from these so care-delivery dashboards
show a name. Resolution is fail-soft: any ips error / not-found / missing name
must leave the keys absent (patient stays pseudonymous) and never raise.
"""
from types import SimpleNamespace
from unittest.mock import patch

from app.services import context_service as cs


def _fake_sr(patient_guid='pat-1'):
    return SimpleNamespace(
        guid='sr-1', status='active', patient_guid=patient_guid,
        contract_guid='c-1', requester_org_guid='org-1',
        requester_user_guid='u-1', requester_user_name='Dr X',
        plan_definition_guid='pd-1', plan_definition_snapshot={},
        fhir_resource={}, period_start=None, period_end=None,
    )


def _run(patient_body, status):
    with patch.object(cs, 'ServiceRequest') as SR, \
         patch.object(cs.patient_service, 'get_patient',
                      return_value=(patient_body, status)):
        SR.query.filter_by.return_value.first.return_value = _fake_sr()
        return cs.get_sr_context('sr-1')


def test_name_and_birth_added_from_given_family():
    ctx = _run({'resourceType': 'Patient',
                'name': [{'family': 'Holmgren', 'given': ['Anders']}],
                'birthDate': '1950-03-02'}, 200)
    assert ctx['patient_name'] == 'Anders Holmgren'
    assert ctx['patient_birth_date'] == '1950-03-02'


def test_text_name_preferred():
    ctx = _run({'name': [{'text': 'Karin Svensson'}]}, 200)
    assert ctx['patient_name'] == 'Karin Svensson'


def test_failsoft_on_404():
    ctx = _run({'code': 'not_found'}, 404)
    assert 'patient_name' not in ctx
    assert 'patient_birth_date' not in ctx


def test_failsoft_on_upstream_error():
    ctx = _run({'code': 'upstream_error'}, 502)
    assert 'patient_name' not in ctx


def test_failsoft_when_patient_has_no_name():
    ctx = _run({'resourceType': 'Patient', 'birthDate': '1950-03-02'}, 200)
    # No name → emit neither key (a lone birthDate is not useful; the dashboard
    # keys off the name). Patient stays pseudonymous.
    assert 'patient_name' not in ctx
    assert 'patient_birth_date' not in ctx


def test_failsoft_when_lookup_raises():
    with patch.object(cs, 'ServiceRequest') as SR, \
         patch.object(cs.patient_service, 'get_patient',
                      side_effect=RuntimeError('boom')):
        SR.query.filter_by.return_value.first.return_value = _fake_sr()
        ctx = cs.get_sr_context('sr-1')
    assert 'patient_name' not in ctx

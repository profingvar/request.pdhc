"""2026-11-20 — the SR context names the CarePlan the request is based on.

gateway forwards the context's fields to the CDR's clinical_context. The
context had no care_plan_guid, so 0 of the observations gateway delivered to
cdr1 carried one, although every ServiceRequest now has one (care_plan_link).
"""
from unittest.mock import patch

from app.services import context_service as cs
from tests.test_context_demographics import _fake_sr


def _ctx(sr):
    with patch.object(cs, 'ServiceRequest') as SR, \
         patch.object(cs.patient_service, 'get_patient', return_value=({}, 404)):
        SR.query.filter_by.return_value.first.return_value = sr
        return cs.get_sr_context('sr-1')


def test_the_context_carries_the_requests_care_plan_guid():
    sr = _fake_sr()
    sr.care_plan_guid = 'cp-1'
    assert _ctx(sr)['care_plan_guid'] == 'cp-1'


def test_a_request_without_a_care_plan_says_none_not_a_guess():
    assert _ctx(_fake_sr())['care_plan_guid'] is None

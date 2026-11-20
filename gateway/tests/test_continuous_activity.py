"""2026-11-20 — a continuous activity (CGM) in request.pdhc.

plan.pdhc now has timing_type 'continuous': ordered ONCE, runs for a required
active period, streams values about every sample interval. request must not
turn it into thousands of orders: the timeline draws one line start -> end,
and the provider feed sends Timing {count: 1, duration} plus the interval.
"""
from types import SimpleNamespace

from app.services.provider_feed_service import _fhir_timing, instantiated_care_plan
from app.services.timeline_service import build_timeline


def _cgm(**over):
    act = {'title': 'CGM', 'timing_type': 'continuous',
           'timing_bounds_mode': 'duration', 'timing_bounds_duration_value': 40,
           'timing_bounds_duration_unit': 'd',
           'sample_interval_value': 15, 'sample_interval_unit': 'min',
           'transactions': [{'concept_name': 'B-glucos', 'concept_guid': 'g1',
                             'transaction_guid': 't1'}]}
    act.update(over)
    return act


def test_timeline_draws_one_line_from_start_to_end_not_one_station_per_value():
    tl = build_timeline([_cgm()], start_date='2026-12-01', window_days=60)
    (line,) = tl['lines']
    assert [s['day'] for s in line['stations']] == [0, 40]
    assert line['stations'][-1]['terminus'] is True
    assert line['bound_end_date'] == '2027-01-10'
    assert line['cadence'] == 'Continuous, about every 15 min'
    assert line['endless'] is False and line['truncated'] is False


def test_timeline_marks_a_period_beyond_the_window_as_truncated():
    (line,) = build_timeline([_cgm()], start_date='2026-12-01', window_days=30)['lines']
    assert [s['day'] for s in line['stations']] == [0, 30]
    assert line['truncated'] is True and line['stations'][-1]['terminus'] is False


def test_timeline_respects_the_orders_own_end_date():
    (line,) = build_timeline([_cgm()], start_date='2026-12-01', end_date='2026-12-11')['lines']
    assert line['bound_end_day'] == 10


def test_feed_timing_is_one_occurrence_lasting_the_period():
    assert _fhir_timing(_cgm()) == {'repeat': {'count': 1, 'duration': 40, 'durationUnit': 'd'}}


def test_feed_sends_the_interval_and_never_a_frequency():
    sr = SimpleNamespace(care_plan_guid='cp', plan_definition_guid='pd', created_at=None,
                         plan_definition_snapshot={'title': 'MMD', 'version': '1.0.3',
                                                   'activities': [_cgm()]})
    (act,) = instantiated_care_plan(sr)['activities']
    assert act['timing_type'] == 'continuous'
    assert 'frequency' not in act['timing']['repeat']
    assert act['expected_sampling_interval'] == {
        'value': 15, 'unit': 'min', 'system': 'http://unitsofmeasure.org', 'code': 'min'}
    assert act['transactions'][0]['transaction_guid'] == 't1'


def test_repeat_activities_are_unchanged():
    rep = {'timing_type': 'repeat', 'timing_frequency': 1, 'timing_period': 1,
           'timing_period_unit': 'd', 'timing_bounds_mode': 'count', 'timing_bounds_count': 8}
    assert _fhir_timing(rep) == {'repeat': {'frequency': 1, 'period': 1, 'periodUnit': 'd', 'count': 8}}
    sr = SimpleNamespace(care_plan_guid='cp', plan_definition_guid='pd', created_at=None,
                         plan_definition_snapshot={'activities': [rep]})
    assert instantiated_care_plan(sr)['activities'][0]['expected_sampling_interval'] is None

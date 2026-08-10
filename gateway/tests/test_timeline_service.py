"""Metro-map schedule timeline helper (patient timeline visualisation).

Config-free unit tests — build_timeline is pure (no Flask), mirroring
test_reform_scope.py.
"""
from app.services.timeline_service import build_timeline, _cadence_label


def _daily(**over):
    act = {'title': 'Daily asthma diary', 'timing_type': 'repeat',
           'timing_frequency': 1, 'timing_period': 1, 'timing_period_unit': 'd',
           'transactions': [
               {'concept_name': 'asthma-peak-flow', 'requirement_type': 'required',
                'concept_unit_name': 'L/min', 'concept_guid': 'g1'},
               {'concept_name': 'asthma-wheeze', 'requirement_type': 'optional',
                'concept_guid': 'g2'}]}
    act.update(over)
    return act


def _weekly(**over):
    act = {'title': 'Weekly home spirometry', 'timing_type': 'repeat',
           'timing_frequency': 1, 'timing_period': 1, 'timing_period_unit': 'wk',
           'transactions': [{'concept_name': 'FEV1', 'requirement_type': 'optional',
                             'concept_guid': 'g3'}]}
    act.update(over)
    return act


def test_endless_daily_draws_first_month_then_truncates():
    tl = build_timeline([_daily()], start_date='2026-08-10')
    line = tl['lines'][0]
    assert line['endless'] is True
    assert line['truncated'] is True          # continues past the '…'
    # 30-day window, daily → stations at day 0..30 inclusive = 31.
    assert len(line['stations']) == 31
    assert line['stations'][0]['date'] == '2026-08-10'
    assert line['stations'][0]['label'] == 'D1'
    assert line['stations'][-1]['day'] == 30
    assert tl['any_truncated'] is True


def test_station_concepts_are_the_activity_transactions():
    tl = build_timeline([_daily()], start_date='2026-08-10')
    concepts = tl['lines'][0]['concepts']
    assert [c['name'] for c in concepts] == ['asthma-peak-flow', 'asthma-wheeze']
    assert concepts[0]['requirement'] == 'required'
    assert concepts[0]['unit'] == 'L/min'
    assert concepts[1]['unit'] is None


def test_weekly_cadence_stations_are_seven_days_apart():
    tl = build_timeline([_weekly()], start_date='2026-08-10')
    days = [s['day'] for s in tl['lines'][0]['stations']]
    assert days == [0, 7, 14, 21, 28]
    assert tl['lines'][0]['stations'][1]['label'] == 'W2'


def test_bounds_count_gives_solid_terminus_no_truncation():
    tl = build_timeline([_weekly(timing_bounds_mode='count',
                                 timing_bounds_count=4)],
                        start_date='2026-08-10')
    line = tl['lines'][0]
    assert line['endless'] is False
    assert line['truncated'] is False
    days = [s['day'] for s in line['stations']]
    assert days == [0, 7, 14, 21]             # exactly 4 occurrences
    assert line['stations'][-1]['terminus'] is True
    assert line['bound_end_day'] == 21


def test_period_end_bounds_and_truncates_when_beyond_window():
    # Ends well past the 30-day window → drawn to the window, then '…'.
    tl = build_timeline([_daily()], start_date='2026-08-10',
                        end_date='2026-12-31')
    line = tl['lines'][0]
    assert line['endless'] is False
    assert line['truncated'] is True
    assert line['stations'][-1]['day'] == 30  # capped at window
    assert line['bound_end_date'] == '2026-12-31'


def test_period_end_within_window_terminates_cleanly():
    tl = build_timeline([_daily()], start_date='2026-08-10',
                        end_date='2026-08-20')
    line = tl['lines'][0]
    assert line['truncated'] is False
    assert line['stations'][-1]['day'] == 10
    assert line['stations'][-1]['terminus'] is True


def test_multiple_lines_get_distinct_colours_and_shared_axis():
    tl = build_timeline([_daily(), _weekly()], start_date='2026-08-10')
    assert tl['lines'][0]['color'] != tl['lines'][1]['color']
    assert tl['axis_days'] == 30              # daily line reaches the window
    assert len(tl['gridlines']) >= 5          # weekly gridlines 0,7,14,21,28,30


def test_anchor_assumed_when_no_start_date():
    tl = build_timeline([_daily()])
    assert tl['anchor_assumed'] is True
    assert tl['anchor'] is not None


def test_empty_activities():
    tl = build_timeline([], start_date='2026-08-10')
    assert tl['lines'] == []
    assert tl['any_truncated'] is False


def test_cadence_labels():
    assert _cadence_label(1, 1, 'd') == 'Daily'
    assert _cadence_label(1, 1, 'wk') == 'Weekly'
    assert _cadence_label(1, 1, 'mo') == 'Monthly'
    assert _cadence_label(1, 2, 'wk') == 'Every 2 weeks'
    assert _cadence_label(3, 1, 'd') == '3× per day'

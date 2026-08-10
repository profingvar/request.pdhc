"""Build a 'metro-map' schedule timeline from PlanDefinition activities.

Each activity becomes a *line*; each scheduled occurrence of that activity
becomes a *station*. A station carries the list of concepts collected at that
point (identical across a line's stations — they are the activity's
transactions). Recurring activities with no end ("endless requests") are drawn
for the first month and then terminated with an ellipsis; bounded activities
(by count, by duration, or by the ServiceRequest's period_end) end in a solid
terminus.

Config-free (no Flask imports) so it unit-tests without the app bootstrap —
same pattern as ``reform_scope``.
"""
from datetime import date, datetime, timedelta

# Days per timing unit. PlanDefinition uses FHIR-ish codes d/wk/mo/a; we also
# accept the spelled-out forms defensively.
_UNIT_DAYS = {
    'd': 1, 'day': 1, 'days': 1,
    'wk': 7, 'week': 7, 'weeks': 7,
    'mo': 30, 'month': 30, 'months': 30,
    'a': 365, 'year': 365, 'years': 365,
}
# Single-letter station label prefix per cadence unit.
_UNIT_LABEL = {'d': 'D', 'wk': 'W', 'mo': 'M', 'a': 'Y'}
_UNIT_WORD = {'d': 'day', 'wk': 'week', 'mo': 'month', 'a': 'year'}

# Metro-line palette. Distinct hues are the one place decoration is warranted —
# a metro map is unreadable if lines can't be told apart. Kept tasteful and
# aligned with the PDHC primary (#2563eb) as line 1.
_LINE_COLORS = [
    '#2563eb', '#16a34a', '#d97706', '#db2777',
    '#7c3aed', '#0891b2', '#dc2626', '#4d7c0f',
]

WINDOW_DAYS = 30  # "first month" horizon for endless / long requests


def _parse_date(value):
    """Coerce an ISO date/datetime string (or date) to a date; None on failure."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (ValueError, TypeError):
        return None


def _unit_days(unit):
    return _UNIT_DAYS.get(str(unit or 'd').lower(), 1)


def _num(value, default):
    try:
        n = float(value)
        return int(n) if n.is_integer() else n
    except (TypeError, ValueError):
        return default


def _cadence_label(freq, period, unit):
    """Human cadence, e.g. 'Daily', 'Every 2 weeks', '3× per day'."""
    u = str(unit or 'd').lower()
    word = _UNIT_WORD.get(u, u)
    freq = _num(freq, 1)
    period = _num(period, 1)
    if freq == 1 and period == 1:
        return {'d': 'Daily', 'wk': 'Weekly', 'mo': 'Monthly',
                'a': 'Yearly'}.get(u, f'Every {word}')
    if freq == 1:
        return f'Every {period} {word}s'
    per = word if period == 1 else f'{period} {word}s'
    return f'{freq}× per {per}'


def _concepts_for(activity):
    """The concept list collected at each station of this activity."""
    out = []
    for t in activity.get('transactions') or []:
        out.append({
            'name': t.get('concept_name') or t.get('concept_guid') or '—',
            'requirement': (t.get('requirement_type') or 'optional'),
            'unit': t.get('concept_unit_name') or t.get('unit') or None,
            'guid': t.get('concept_guid'),
        })
    return out


def _bound_end_day(activity, anchor, hard_end, step):
    """Return the day-offset at which this activity ends, or None if endless.

    Considers, and takes the *earliest* of: an explicit bounds count, an
    explicit bounds duration, and the ServiceRequest's period_end (hard_end).
    """
    ends = []
    mode = activity.get('timing_bounds_mode')
    count = activity.get('timing_bounds_count')
    if mode == 'count' and count:
        n = _num(count, 0)
        if n and n >= 1:
            ends.append(step * (int(n) - 1))
    dur_val = activity.get('timing_bounds_duration_value')
    if mode == 'duration' and dur_val:
        dur_days = _num(dur_val, 0) * _unit_days(
            activity.get('timing_bounds_duration_unit'))
        if dur_days:
            ends.append(int(dur_days))
    if hard_end and anchor:
        he = (hard_end - anchor).days
        if he >= 0:
            ends.append(he)
    return min(ends) if ends else None


def build_timeline(activities, start_date=None, end_date=None,
                   window_days=WINDOW_DAYS):
    """Compute the metro-map model for a set of PlanDefinition activities.

    Returns a dict::

        {
          'anchor': '2026-08-10' | None,   # start date the schedule is drawn from
          'anchor_assumed': bool,          # True when we defaulted to 'today'
          'window_days': 30,
          'axis_days': <int>,              # x-extent of the drawing, in days
          'any_truncated': bool,
          'lines': [ { title, description, color, cadence, concepts[],
                       endless, truncated, bound_end_day, bound_end_date,
                       stations: [ {ordinal, day, date, label, terminus} ] } ]
        }
    """
    anchor = _parse_date(start_date)
    anchor_assumed = False
    if anchor is None:
        anchor = date.today()
        anchor_assumed = True
    hard_end = _parse_date(end_date)

    lines = []
    max_last_day = 0
    for i, act in enumerate(activities or []):
        unit = str(act.get('timing_period_unit') or 'd').lower()
        period = _num(act.get('timing_period'), 1)
        step = max(1, int(round((period or 1) * _unit_days(unit))))
        freq = _num(act.get('timing_frequency'), 1)

        bound_end = _bound_end_day(act, anchor, hard_end, step)
        endless = bound_end is None
        cutoff = window_days if endless else min(window_days, bound_end)

        label_prefix = _UNIT_LABEL.get(unit, 'S')
        stations = []
        day, ordinal = 0, 1
        while day <= cutoff:
            d = anchor + timedelta(days=day)
            stations.append({
                'ordinal': ordinal,
                'day': day,
                'date': d.isoformat(),
                'label': f'{label_prefix}{ordinal}',
                'terminus': (not endless and day == bound_end),
            })
            max_last_day = max(max_last_day, day)
            day += step
            ordinal += 1

        # The line continues past the drawn window if it's endless, or bounded
        # but the terminus lies beyond the window.
        truncated = endless or (bound_end is not None and bound_end > window_days)

        lines.append({
            'index': i,
            'title': act.get('title') or f'Activity {i + 1}',
            'description': act.get('description') or '',
            'color': _LINE_COLORS[i % len(_LINE_COLORS)],
            'cadence': _cadence_label(freq, period, unit),
            'concepts': _concepts_for(act),
            'endless': endless,
            'truncated': truncated,
            'bound_end_day': bound_end,
            'bound_end_date': (
                (anchor + timedelta(days=bound_end)).isoformat()
                if bound_end is not None else None),
            'stations': stations,
        })

    any_truncated = any(l['truncated'] for l in lines)
    axis_days = max_last_day
    if any_truncated:
        axis_days = max(axis_days, window_days)

    # Weekly gridlines (with dates) for the time axis — computed here because
    # date arithmetic is awkward in the template.
    gridlines = []
    gd = 0
    while gd <= axis_days:
        gridlines.append({'day': gd,
                          'date': (anchor + timedelta(days=gd)).isoformat()})
        gd += 7
    if axis_days and (not gridlines or gridlines[-1]['day'] != axis_days):
        gridlines.append({'day': axis_days,
                          'date': (anchor + timedelta(days=axis_days)).isoformat()})

    return {
        'anchor': anchor.isoformat(),
        'anchor_assumed': anchor_assumed,
        'window_days': window_days,
        'axis_days': axis_days,
        'any_truncated': any_truncated,
        'gridlines': gridlines,
        'lines': lines,
    }

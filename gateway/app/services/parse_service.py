import hashlib
import uuid


def _deterministic_guid(*parts):
    """Generate a deterministic GUID from input parts for idempotency."""
    combined = '|'.join(str(p) for p in parts if p)
    return str(uuid.UUID(hashlib.md5(combined.encode()).hexdigest()))


def _safe_get(data, *keys, default=''):
    """Safely traverse nested dict keys."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        elif isinstance(current, list) and isinstance(key, int) and key < len(current):
            current = current[key]
        else:
            return default
    return current if current is not None else default


def parse_careplan(careplan_data):
    """Transform a CarePlan structure into normalized transaction rows.

    Returns:
        tuple: (rows: list[dict], errors: list[str])
    """
    rows = []
    errors = []

    if not careplan_data or not isinstance(careplan_data, dict):
        return rows, ['Invalid or empty careplan data']

    careplan_guid = careplan_data.get('id', '')
    careplan_status = careplan_data.get('status', '')
    careplan_title = careplan_data.get('title', '')

    # Parse goals into a lookup
    goals = {}
    for goal_data in careplan_data.get('goal', []):
        goal_ref = _safe_get(goal_data, 'reference', default='')
        goal_id = goal_ref.split('/')[-1] if '/' in goal_ref else goal_ref
        goals[goal_id] = goal_data

    # Parse activities
    activities = careplan_data.get('activity', [])
    sort_order = 0

    for act_idx, activity in enumerate(activities):
        try:
            activity_guid = activity.get('id', str(act_idx))
            detail = activity.get('detail', activity.get('plannedActivityDetail', {}))
            if not detail and 'plannedActivityReference' in activity:
                detail = activity.get('plannedActivityReference', {})

            # Extract activity-level fields
            act_description = _safe_get(detail, 'description', default='')
            act_status = _safe_get(detail, 'status', default='')
            performer_type = ''
            performers = _safe_get(detail, 'performer', default=[])
            if isinstance(performers, list) and performers:
                performer_type = _safe_get(performers[0], 'display', default='')

            # Extract concept/code information
            code_data = _safe_get(detail, 'code', default={})
            codings = code_data.get('coding', []) if isinstance(code_data, dict) else []
            concept_guid = ''
            concept_name = ''
            concept_display = ''
            if codings:
                concept_guid = _safe_get(codings[0], 'code', default='')
                concept_name = _safe_get(codings[0], 'display', default='')
                concept_display = concept_name

            # Extract goal references for this activity
            goal_ids = _safe_get(detail, 'goal', default=[])
            goal_guid = ''
            goal_description = ''
            goal_priority = ''
            if isinstance(goal_ids, list) and goal_ids:
                first_goal_ref = goal_ids[0] if isinstance(goal_ids[0], str) else _safe_get(goal_ids[0], 'reference', default='')
                goal_id = first_goal_ref.split('/')[-1] if '/' in first_goal_ref else first_goal_ref
                if goal_id in goals:
                    goal_data = goals[goal_id]
                    goal_guid = goal_id
                    goal_description = _safe_get(goal_data, 'description', 'text', default='')
                    goal_priority = _safe_get(goal_data, 'priority', 'text', default='')

            # Extract expected values/ranges from extensions or direct fields
            expected_value = _safe_get(detail, 'quantity', 'value', default='')
            expected_unit = _safe_get(detail, 'quantity', 'unit', default='')
            range_low = ''
            range_high = ''

            # Check for extension-based ranges
            extensions = _safe_get(detail, 'extension', default=[])
            if isinstance(extensions, list):
                for ext in extensions:
                    ext_url = _safe_get(ext, 'url', default='')
                    if 'range' in ext_url.lower():
                        range_low = _safe_get(ext, 'valueRange', 'low', 'value', default='')
                        range_high = _safe_get(ext, 'valueRange', 'high', 'value', default='')
                    elif 'expected' in ext_url.lower():
                        expected_value = expected_value or _safe_get(ext, 'valueString', default='')

            requirement_type = _safe_get(detail, 'kind', default='')

            row = {
                'row_guid': _deterministic_guid(careplan_guid, activity_guid, sort_order),
                'careplan_guid': careplan_guid,
                'careplan_title': careplan_title,
                'careplan_status': careplan_status,
                'activity_guid': activity_guid,
                'activity_description': act_description,
                'activity_status': act_status,
                'transaction_guid': _deterministic_guid(careplan_guid, activity_guid, 'txn', sort_order),
                'concept_guid': concept_guid,
                'concept_name': concept_name,
                'concept_display': concept_display,
                'goal_guid': goal_guid,
                'goal_description': goal_description,
                'goal_priority': goal_priority,
                'expected_value': str(expected_value),
                'expected_unit': str(expected_unit),
                'range_low': str(range_low),
                'range_high': str(range_high),
                'requirement_type': requirement_type,
                'performer_type': performer_type,
                'sort_order': sort_order,
            }
            rows.append(row)
            sort_order += 1

        except Exception as e:
            errors.append(f"Error parsing activity {act_idx}: {str(e)}")

    return rows, errors

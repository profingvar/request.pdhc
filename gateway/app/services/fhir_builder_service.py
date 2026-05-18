"""Assembles FHIR R5 ServiceRequest with contained CarePlan."""

from datetime import datetime, timezone


def build_patient_excerpt(patient_data):
    """Extract key fields from an IPS patient for inclusion."""
    if not patient_data:
        return None
    return {
        'resourceType': 'Patient',
        'id': patient_data.get('id', ''),
        'name': patient_data.get('name', []),
        'gender': patient_data.get('gender', ''),
        'birthDate': patient_data.get('birthDate', ''),
        'identifier': patient_data.get('identifier', []),
    }


def get_patient_display_name(patient_data):
    """Extract display name from FHIR Patient resource."""
    if not patient_data:
        return 'Unknown'
    names = patient_data.get('name', [])
    if names:
        n = names[0]
        given = ' '.join(n.get('given', []))
        family = n.get('family', '')
        return f"{given} {family}".strip() or 'Unknown'
    return 'Unknown'


def _build_careplan(sr_model, snapshot, patient_name):
    """Build contained FHIR R5 CarePlan from the PlanDefinition snapshot.

    The CarePlan expresses what care is planned: goals and activities
    derived from the edited PlanDefinition snapshot.
    """
    careplan = {
        'resourceType': 'CarePlan',
        'id': f'careplan-{sr_model.guid}',
        'status': 'active',
        'intent': 'plan',
        'title': snapshot.get('title', ''),
        'subject': {
            'reference': f'Patient/{sr_model.patient_guid}',
            'display': patient_name,
        },
    }

    if snapshot.get('description'):
        careplan['description'] = snapshot['description']

    # PlanDefinition reference
    if sr_model.plan_definition_guid:
        careplan['instantiatesCanonical'] = [
            f'https://plan.pdhc.se/api/v1/plandefinitions/{sr_model.plan_definition_guid}'
        ]

    # Build goals
    goals_data = snapshot.get('goals', [])
    contained_goals = []
    goal_refs = []
    for idx, g in enumerate(goals_data):
        goal_id = f'goal-{idx}'
        fhir_goal = {
            'resourceType': 'Goal',
            'id': goal_id,
            'lifecycleStatus': 'planned',
            'description': {
                'text': g.get('concept_name') or 'Goal',
            },
            'subject': {
                'reference': f'Patient/{sr_model.patient_guid}',
            },
        }

        if g.get('concept_guid'):
            fhir_goal['description']['coding'] = [{
                'system': 'https://plan.pdhc.se/api/v1/concepts',
                'code': g['concept_guid'],
                'display': g.get('concept_name', ''),
            }]

        if g.get('priority'):
            fhir_goal['priority'] = {
                'coding': [{'code': g['priority']}],
            }

        target_type = g.get('target_type')
        if target_type:
            target = {}
            # Helper: build a FHIR Quantity with UCUM system+code from
            # the enriched snapshot field target_unit_name (plan.pdhc
            # writes the UCUM code into the goal JSON on save).
            unit_name = g.get('target_unit_name')

            def _qty(value):
                q = {'value': value}
                if unit_name:
                    q['unit'] = unit_name
                    q['system'] = 'http://unitsofmeasure.org'
                    q['code'] = unit_name
                return q

            if target_type == 'quantity' and g.get('target_quantity') is not None:
                target['detailQuantity'] = _qty(g['target_quantity'])
                if g.get('target_operator'):
                    target['detailQuantity']['comparator'] = g['target_operator']
            elif target_type == 'range':
                target['detailRange'] = {}
                if g.get('target_range_low') is not None:
                    target['detailRange']['low'] = _qty(g['target_range_low'])
                if g.get('target_range_high') is not None:
                    target['detailRange']['high'] = _qty(g['target_range_high'])
            elif target_type == 'categorical' and g.get('target_categorical_text'):
                cc = {'text': g['target_categorical_text']}
                vs_guid = g.get('target_categorical_valueset')
                if vs_guid:
                    coding = {
                        'system': f'https://plan.pdhc.se/api/v1/valuesets/{vs_guid}',
                        'code': g.get('target_categorical_code') or g['target_categorical_text'],
                    }
                    if g.get('target_categorical_display'):
                        coding['display'] = g['target_categorical_display']
                    cc['coding'] = [coding]
                target['detailCodeableConcept'] = cc
            if target:
                fhir_goal['target'] = [target]

        contained_goals.append(fhir_goal)
        goal_refs.append({'reference': f'#{goal_id}'})

    if goal_refs:
        careplan['goal'] = goal_refs

    # Build activities
    activities_data = snapshot.get('activities', [])
    if activities_data:
        careplan['activity'] = []
        for act_data in activities_data:
            detail = {'status': 'not-started'}

            txns = act_data.get('transactions', [])
            code_coding = []
            if txns:
                for txn in txns:
                    if txn.get('concept_guid'):
                        code_coding.append({
                            'system': 'https://plan.pdhc.se/api/v1/concepts',
                            'code': txn['concept_guid'],
                            'display': txn.get('concept_name', ''),
                        })

            if code_coding:
                detail['code'] = {
                    'coding': code_coding,
                    'text': act_data.get('title', ''),
                }
            elif act_data.get('title'):
                detail['code'] = {'text': act_data['title']}

            if act_data.get('description'):
                detail['description'] = act_data['description']

            if act_data.get('performer_type'):
                detail['performer'] = [{'display': act_data['performer_type']}]

            timing_type = act_data.get('timing_type')
            if timing_type == 'repeat' and act_data.get('timing_frequency'):
                repeat = {
                    'frequency': act_data['timing_frequency'],
                    'period': act_data.get('timing_period') or 1,
                    'periodUnit': act_data.get('timing_period_unit') or 'd',
                }
                if act_data.get('duration_value'):
                    repeat['duration'] = act_data['duration_value']
                    repeat['durationUnit'] = act_data.get('duration_unit') or 'min'
                bounds_mode = act_data.get('timing_bounds_mode')
                if bounds_mode == 'count' and act_data.get('timing_bounds_count'):
                    repeat['count'] = act_data['timing_bounds_count']
                elif bounds_mode == 'duration' and act_data.get('timing_bounds_duration_value'):
                    unit = act_data.get('timing_bounds_duration_unit') or 'mo'
                    repeat['boundsDuration'] = {
                        'value': act_data['timing_bounds_duration_value'],
                        'unit': unit,
                        'system': 'http://unitsofmeasure.org',
                        'code': unit,
                    }
                detail['scheduledTiming'] = {'repeat': repeat}
            elif timing_type == 'once' and act_data.get('duration_value'):
                detail['scheduledTiming'] = {
                    'repeat': {
                        'duration': act_data['duration_value'],
                        'durationUnit': act_data.get('duration_unit') or 'min',
                    }
                }

            if txns:
                first_txn = txns[0]
                if first_txn.get('expected_value'):
                    try:
                        detail['quantity'] = {'value': float(first_txn['expected_value'])}
                    except (ValueError, TypeError):
                        pass
                if first_txn.get('range_min') is not None or first_txn.get('range_max') is not None:
                    detail['extension'] = [{
                        'url': 'http://pdhc.se/fhir/StructureDefinition/expected-range',
                        'valueRange': {},
                    }]
                    if first_txn.get('range_min') is not None:
                        detail['extension'][0]['valueRange']['low'] = {'value': first_txn['range_min']}
                    if first_txn.get('range_max') is not None:
                        detail['extension'][0]['valueRange']['high'] = {'value': first_txn['range_max']}

            if goal_refs:
                detail['goal'] = list(goal_refs)

            activity = {'detail': detail}

            activity_guid = act_data.get('guid', '')
            if txns:
                activity['_pdhc_activity_guid'] = activity_guid
                activity['_pdhc_transactions'] = []
                for txn in txns:
                    txn_entry = {}
                    # transaction_guid is the stable plan-level ID the
                    # gateway keys its txn_map on.  Fall back to
                    # concept_guid for snapshots that predate per-txn GUIDs.
                    txn_entry['transaction_guid'] = txn.get('guid') or txn.get('concept_guid', '')
                    txn_entry['activity_guid'] = activity_guid
                    if txn.get('concept_guid'):
                        txn_entry['concept_guid'] = txn['concept_guid']
                        txn_entry['concept_name'] = txn.get('concept_name', '')
                        txn_entry['concept_url'] = f'https://plan.pdhc.se/api/v1/concepts/{txn["concept_guid"]}'
                    if txn.get('requirement_type'):
                        txn_entry['requirement_type'] = txn['requirement_type']
                    if txn.get('expected_value'):
                        txn_entry['expected_value'] = txn['expected_value']
                    if txn.get('unit'):
                        txn_entry['unit'] = txn['unit']
                    if txn.get('range_min') is not None:
                        txn_entry['range_min'] = txn['range_min']
                    if txn.get('range_max') is not None:
                        txn_entry['range_max'] = txn['range_max']
                    if txn_entry:
                        activity['_pdhc_transactions'].append(txn_entry)

            careplan['activity'].append(activity)

    return careplan, contained_goals


def build_service_request_resource(sr_model):
    """Assemble the full FHIR R5 ServiceRequest with contained CarePlan.

    The ServiceRequest is the envelope:
      - CarePlan (goals + activities from PlanDefinition)
      - Contract reference
      - Requester org + professional
      - Receiver org/professional (from matched provider, optional)
      - Send date (authoredOn)
      - Validity period (occurrencePeriod)

    Args:
        sr_model: ServiceRequest SQLAlchemy model instance

    Returns:
        dict: FHIR R5 ServiceRequest resource
    """
    patient_name = get_patient_display_name(sr_model.patient_excerpt)
    snapshot = sr_model.plan_definition_snapshot or {}
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build the contained CarePlan
    careplan, contained_goals = _build_careplan(sr_model, snapshot, patient_name)

    resource = {
        'resourceType': 'ServiceRequest',
        'id': sr_model.guid,
        'status': sr_model.status,
        'intent': sr_model.intent,
        'priority': sr_model.priority,

        # What is being requested — the CarePlan
        'code': {
            'text': snapshot.get('title', 'Service Request'),
        },

        # Who it is for
        'subject': {
            'reference': f'Patient/{sr_model.patient_guid}',
            'display': patient_name,
        },

        # Who is requesting (the logged-in professional)
        'requester': {
            'reference': f'Practitioner/{sr_model.requester_user_guid}',
            **(({'display': sr_model.requester_user_name} if sr_model.requester_user_name else {})),
        },

        # Send date
        'authoredOn': sr_model.created_at.isoformat() if sr_model.created_at else now_iso,

        # Reference to the contained CarePlan
        'supportingInfo': [{
            'reference': f'#careplan-{sr_model.guid}',
            'display': 'Contained CarePlan',
        }],
    }

    # PlanDefinition reference
    if sr_model.plan_definition_guid:
        resource['instantiatesCanonical'] = [
            f'https://plan.pdhc.se/api/v1/plandefinitions/{sr_model.plan_definition_guid}'
        ]

    # Contract reference
    if sr_model.contract_guid:
        resource['basedOn'] = [{
            'reference': f'https://contract.pdhc.se/fhir/Contract/{sr_model.contract_guid}',
        }]

    # Requester organisation
    if sr_model.requester_org_guid:
        resource['requester']['extension'] = [{
            'url': 'http://pdhc.se/fhir/StructureDefinition/requester-organization',
            'valueReference': {
                'reference': f'Organization/{sr_model.requester_org_guid}',
                **(({'display': sr_model.requester_org_name} if sr_model.requester_org_name else {})),
            },
        }]

    # Receiver org/professional (from matched providers — optional)
    performers = _build_performer_refs(sr_model)
    if performers:
        resource['performer'] = performers

    # Validity period for the request
    if sr_model.period_start or sr_model.period_end:
        resource['occurrencePeriod'] = {}
        if sr_model.period_start:
            resource['occurrencePeriod']['start'] = sr_model.period_start.isoformat()
        if sr_model.period_end:
            resource['occurrencePeriod']['end'] = sr_model.period_end.isoformat()

    # Notes
    if sr_model.notes:
        resource['note'] = [{'text': sr_model.notes}]

    # Contained resources: Patient excerpt + Goals + CarePlan + Questionnaires
    contained = []
    if sr_model.patient_excerpt:
        contained.append(sr_model.patient_excerpt)
    contained.extend(contained_goals)
    contained.append(careplan)

    # Attach form Questionnaire snapshots as contained resources
    form_refs = []
    if hasattr(sr_model, 'forms'):
        for srf in sr_model.forms:
            if srf.form_snapshot:
                q = dict(srf.form_snapshot)
                q.setdefault('resourceType', 'Questionnaire')
                q['id'] = f'questionnaire-{srf.form_guid}'
                contained.append(q)
                form_refs.append({
                    'reference': f'#questionnaire-{srf.form_guid}',
                    'display': srf.display_title or 'Questionnaire',
                })

    resource['contained'] = contained

    # Add form references to supportingInfo
    if form_refs:
        resource['supportingInfo'].extend(form_refs)

    return resource


def _build_performer_refs(sr_model):
    """Build performer references from accepted contract matches (receiver org/professional)."""
    performers = []
    if not hasattr(sr_model, 'contract_matches'):
        return performers

    for match in sr_model.contract_matches:
        if match.status in ('accepted', 'sent', 'pending'):
            performer = {
                'reference': f'Organization/{match.provider_org_guid}',
            }
            if match.provider_name:
                performer['display'] = match.provider_name
            performers.append(performer)

    return performers


# Alias for backward compatibility
build_careplan_resource = build_service_request_resource

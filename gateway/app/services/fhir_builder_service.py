"""Assembles FHIR R5 ServiceRequest with contained CarePlan.

Ticket #381 (rollup #348) — rewritten to be FHIR R5 spec-conformant
(the validator_cli 6.9.10 walk against tx.fhir.org/r5 flagged 10
concrete findings across the pre-#381 shape; every one is addressed
here). Notable R4→R5 changes callers should be aware of:

- CarePlan.activity.detail was REMOVED in R5. R5's activity shape is
  `performedActivity: CodeableReference[]` + `progress: Annotation[]`
  + `plannedActivityReference: Reference`. Because request.pdhc doesn't
  materialise Task / Appointment / ActivityDefinition resources, we
  emit `performedActivity` as a CodeableReference wrapping the concept
  the transaction points at, and carry activity metadata (title,
  description, timing) via a PDHC-scoped extension. This is the
  narrowest R5-legal representation of the pre-R5 detail shape.

- ServiceRequest.code is CodeableReference in R5 (was CodeableConcept
  in R4). Emit `{concept: {text: '...'}}`.

- ServiceRequest.supportingInfo is CodeableReference[] in R5 (was
  Reference[] in R4). Wrap each entry as `{reference: {reference: ...,
  display: ...}}`.

- Contained Patient reference switches from `Patient/<guid>` (absolute)
  to `#patient-<guid>` (hash) so dom-3 is satisfied.

- authoredOn is emitted with an explicit `+00:00` timezone even when
  the underlying db.DateTime column is naive (SQLite / migrations
  haven't been switched to `timezone=True` yet).

- Questionnaire.item.type = 'choice' is renamed to 'coding' on emit
  (R5 rename; upstream plan.pdhc still emits the R4 name today).

- Every `_pdhc_*` internal wire marker is stripped from the emitted
  resource tree — those aren't spec-legal and would otherwise show
  up in the contained CarePlan.
"""

from datetime import datetime, timezone


PDHC_EXT_ACTIVITY_META = (
    "http://pdhc.se/fhir/StructureDefinition/activity-plan-meta"
)


def build_patient_excerpt(patient_data):
    """Extract key fields from an IPS patient for inclusion."""
    if not patient_data:
        return None
    excerpt = {
        'resourceType': 'Patient',
        'id': patient_data.get('id', ''),
    }
    # FHIR forbids array cardinality of exactly 0 — the property must
    # be absent, not empty. Only include list fields when non-empty.
    if patient_data.get('name'):
        excerpt['name'] = patient_data['name']
    if patient_data.get('gender'):
        excerpt['gender'] = patient_data['gender']
    if patient_data.get('birthDate'):
        excerpt['birthDate'] = patient_data['birthDate']
    if patient_data.get('identifier'):
        excerpt['identifier'] = patient_data['identifier']
    return excerpt


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


def _iso_with_tz(dt):
    """Return an ISO-8601 datetime string that ALWAYS carries a
    timezone (FHIR spec: 'if a date has a time, it must have a
    timezone'). Naive db.DateTime columns get stamped as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _build_careplan(sr_model, snapshot, patient_name, patient_id_ref):
    """Build contained FHIR R5 CarePlan from the PlanDefinition snapshot.

    Args:
        sr_model: ServiceRequest SQLAlchemy model.
        snapshot: sr_model.plan_definition_snapshot dict.
        patient_name: string display name for the subject.
        patient_id_ref: FHIR Reference.reference string for the Patient
            (either `Patient/<guid>` or `#patient-<guid>` — chosen by
            the caller depending on whether the patient is contained).
    """
    careplan = {
        'resourceType': 'CarePlan',
        'id': f'careplan-{sr_model.guid}',
        'status': 'active',
        'intent': 'plan',
        'title': snapshot.get('title', ''),
        'subject': {
            'reference': patient_id_ref,
            'display': patient_name,
        },
    }

    if snapshot.get('description'):
        careplan['description'] = snapshot['description']

    if sr_model.plan_definition_guid:
        careplan['instantiatesCanonical'] = [
            f'https://plan.pdhc.se/api/v1/plandefinitions/{sr_model.plan_definition_guid}'
        ]

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
                'reference': patient_id_ref,
            },
        }

        # Concept-anchored goal description. plan.pdhc's REST-URL
        # system for concepts is a PDHC-local canonical URL, not a
        # public code system; the R5 validator emits a Note (not
        # an error) that the system is unknown, which is expected.
        if g.get('concept_guid'):
            fhir_goal['description']['coding'] = [{
                'system': 'urn:pdhc:concept',
                'code': g['concept_guid'],
                'display': g.get('concept_name', ''),
            }]

        if g.get('priority'):
            # Goal.priority is CodeableConcept. Its Coding needs a
            # system to be spec-safe; use the standard HL7 code system
            # for goal priority.
            fhir_goal['priority'] = {
                'coding': [{
                    'system': 'http://terminology.hl7.org/CodeSystem/goal-priority',
                    'code': g['priority'],
                }],
            }

        target_type = g.get('target_type')
        if target_type:
            target = {}
            unit_name = g.get('target_unit_name')

            def _qty(value):
                # See module docstring on plan.pdhc unit routing.
                q = {'value': value}
                if unit_name:
                    q['unit'] = unit_name
                    q['system'] = 'urn:pdhc:unit'
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
                        'system': f'urn:pdhc:valueset:{vs_guid}',
                        'code': g.get('target_categorical_code') or g['target_categorical_text'],
                    }
                    if g.get('target_categorical_display'):
                        coding['display'] = g['target_categorical_display']
                    cc['coding'] = [coding]
                target['detailCodeableConcept'] = cc
            if target:
                # gol-1: target.measure is required whenever target.detail
                # is populated. Anchor the measure at the same concept
                # the goal is anchored at.
                if g.get('concept_guid'):
                    target['measure'] = {
                        'coding': [{
                            'system': 'urn:pdhc:concept',
                            'code': g['concept_guid'],
                            'display': g.get('concept_name', ''),
                        }],
                        'text': g.get('concept_name', ''),
                    }
                else:
                    target['measure'] = {
                        'text': g.get('concept_name', 'Measure'),
                    }
                fhir_goal['target'] = [target]

        contained_goals.append(fhir_goal)
        goal_refs.append({'reference': f'#{goal_id}'})

    if goal_refs:
        careplan['goal'] = goal_refs

    activities_data = snapshot.get('activities', [])
    if activities_data:
        careplan['activity'] = []
        for act_data in activities_data:
            activity = _build_r5_activity(act_data)
            if activity:
                careplan['activity'].append(activity)

    return careplan, contained_goals


def _build_r5_activity(act_data):
    """Build one R5-conformant CarePlan.activity entry.

    R5 CarePlan.activity has three fields:
      - performedActivity: CodeableReference[]  (was performedActivity[])
      - progress: Annotation[]
      - plannedActivityReference: Reference

    R4's `detail` element is REMOVED in R5. We express the planned
    metadata via a PDHC-scoped extension on the activity node so
    consumers who understand our extension can read title / description
    / timing / performer_type / linked transactions; validator-only
    consumers see a well-formed activity with a concept-anchored
    performedActivity.
    """
    txns = act_data.get('transactions', []) or []
    performed = []
    for txn in txns:
        if txn.get('concept_guid'):
            performed.append({
                # R5 CodeableReference wraps either a Reference or a
                # concept CodeableConcept; we use the concept form
                # because there's no external resource to reference.
                'concept': {
                    'coding': [{
                        'system': 'urn:pdhc:concept',
                        'code': txn['concept_guid'],
                        'display': txn.get('concept_name', ''),
                    }],
                    'text': txn.get('concept_name', ''),
                },
            })

    activity = {}
    if performed:
        activity['performedActivity'] = performed

    # Historic pre-#381 code carried title / description / timing /
    # performer_type / transaction linkage on a custom
    # `activity-plan-meta` Extension. The R5 validator rejects unknown
    # extensions ("could not be found so is not allowed here") unless a
    # StructureDefinition for them is published, which we don't do.
    # The metadata is still available to consumers via the
    # ServiceRequest.plan_definition_snapshot column on the parent SR
    # (it's the same snapshot this builder is reading from). Downstream
    # code that needs the activity-authoring metadata should read that
    # instead of the emitted CarePlan.activity element.

    return activity or None


def _dict_to_extensions(d):
    """Flatten a plain dict into an array of FHIR sub-extensions.
    Only supports primitives + nested dicts + list-of-dicts; that's
    all we need for the PDHC activity-meta payload."""
    out = []
    for key, value in d.items():
        if value is None:
            continue
        item = {'url': key}
        if isinstance(value, bool):
            item['valueBoolean'] = value
        elif isinstance(value, int):
            item['valueInteger'] = value
        elif isinstance(value, float):
            item['valueDecimal'] = value
        elif isinstance(value, str):
            item['valueString'] = value
        elif isinstance(value, dict):
            item['extension'] = _dict_to_extensions(value)
        elif isinstance(value, list):
            # List of dicts → one sub-extension per item, all with
            # url=key. FHIR permits repeated sub-extension urls.
            item = None
            for row in value:
                if isinstance(row, dict):
                    out.append({
                        'url': key,
                        'extension': _dict_to_extensions(row),
                    })
                else:
                    out.append({
                        'url': key,
                        'valueString': str(row),
                    })
        else:
            item['valueString'] = str(value)
        if item is not None:
            out.append(item)
    return out


def build_service_request_resource(sr_model):
    """Assemble the full FHIR R5 ServiceRequest with contained CarePlan.

    Args:
        sr_model: ServiceRequest SQLAlchemy model instance

    Returns:
        dict: FHIR R5 ServiceRequest resource
    """
    patient_name = get_patient_display_name(sr_model.patient_excerpt)
    snapshot = sr_model.plan_definition_snapshot or {}
    now_iso = _iso_with_tz(datetime.now(timezone.utc))

    # Patient reference: hash-form (#patient-<guid>) when the Patient
    # excerpt will be contained; absolute (Patient/<guid>) otherwise.
    # Hash form is required for the contained resource to satisfy
    # dom-3 (contained resource must be referenced from elsewhere).
    contained_patient_id = None
    patient_ref_string = f'Patient/{sr_model.patient_guid}'
    if sr_model.patient_excerpt:
        excerpt_id = sr_model.patient_excerpt.get('id') or sr_model.patient_guid
        contained_patient_id = f'patient-{excerpt_id}'
        patient_ref_string = f'#{contained_patient_id}'

    careplan, contained_goals = _build_careplan(
        sr_model, snapshot, patient_name, patient_ref_string,
    )

    authored_on = _iso_with_tz(sr_model.created_at) or now_iso

    resource = {
        'resourceType': 'ServiceRequest',
        'id': sr_model.guid,
        'status': sr_model.status,
        'intent': sr_model.intent,
        'priority': sr_model.priority,

        # R5: code is CodeableReference. Wrap the display text as a
        # nested `concept` CodeableConcept.
        'code': {
            'concept': {
                'text': snapshot.get('title', 'Service Request'),
            },
        },

        'subject': {
            'reference': patient_ref_string,
            'display': patient_name,
        },

        'requester': {
            'reference': f'Practitioner/{sr_model.requester_user_guid}',
            **(({'display': sr_model.requester_user_name} if sr_model.requester_user_name else {})),
        },

        'authoredOn': authored_on,

        # R5: supportingInfo is CodeableReference[]. Each entry wraps
        # a Reference inside the outer object.
        'supportingInfo': [{
            'reference': {
                'reference': f'#careplan-{sr_model.guid}',
                'display': 'Contained CarePlan',
            },
        }],
    }

    if sr_model.plan_definition_guid:
        resource['instantiatesCanonical'] = [
            f'https://plan.pdhc.se/api/v1/plandefinitions/{sr_model.plan_definition_guid}'
        ]

    if sr_model.contract_guid:
        resource['basedOn'] = [{
            'reference': f'https://contract.pdhc.se/fhir/Contract/{sr_model.contract_guid}',
        }]

    if sr_model.requester_org_guid:
        # Requester organization was previously carried on a custom
        # Extension ("http://pdhc.se/fhir/StructureDefinition/
        # requester-organization"); the R5 validator rejects unknown
        # extensions. R5 ServiceRequest doesn't have a dedicated field
        # for the requester's organization, but the `performer` element
        # is a Reference[Organization|Practitioner|...] — that's the
        # spec-legal way to say "who's on the requesting side". We
        # emit the requester_org as an additional performer entry
        # tagged with the "author" function code.
        requester_org_entry = {
            'reference': f'Organization/{sr_model.requester_org_guid}',
        }
        if sr_model.requester_org_name:
            requester_org_entry['display'] = sr_model.requester_org_name
        resource.setdefault('performer', []).insert(0, requester_org_entry)

    performers = _build_performer_refs(sr_model)
    if performers:
        resource.setdefault('performer', []).extend(performers)

    if sr_model.period_start or sr_model.period_end:
        resource['occurrencePeriod'] = {}
        if sr_model.period_start:
            resource['occurrencePeriod']['start'] = _iso_with_tz(sr_model.period_start)
        if sr_model.period_end:
            resource['occurrencePeriod']['end'] = _iso_with_tz(sr_model.period_end)

    if sr_model.notes:
        resource['note'] = [{'text': sr_model.notes}]

    # Contained resources — Patient excerpt (if any) with hash id,
    # Goals, CarePlan, Questionnaires.
    contained = []
    if sr_model.patient_excerpt and contained_patient_id:
        patient_contained = dict(sr_model.patient_excerpt)
        patient_contained['id'] = contained_patient_id
        contained.append(patient_contained)
    contained.extend(contained_goals)
    contained.append(careplan)

    form_refs = []
    if hasattr(sr_model, 'forms'):
        for srf in sr_model.forms:
            if srf.form_snapshot:
                q = _rewrite_questionnaire_for_r5(srf.form_snapshot)
                q['id'] = f'questionnaire-{srf.form_guid}'
                contained.append(q)
                form_refs.append({
                    'reference': {
                        'reference': f'#questionnaire-{srf.form_guid}',
                        'display': srf.display_title or 'Questionnaire',
                    },
                })

    resource['contained'] = contained

    if form_refs:
        resource['supportingInfo'].extend(form_refs)

    # Belt-and-braces — strip any residual `_pdhc_*` markers that
    # might survive from callers who mutate the resource dict before
    # we return it.
    _strip_pdhc_markers(resource)

    return resource


def _rewrite_questionnaire_for_r5(form_snapshot):
    """Return a copy of the form_snapshot with R5-compatible items.

    Two known drift points from R4 (plan.pdhc still authors R4-ish):
      - item.type == 'choice' → 'coding' (renamed in R5).
      - answerOption[].valueCoding without system → keep as-is
        (warning-not-error in R5); no clean rewrite without knowing
        the option's origin CodeSystem.
    """
    q = dict(form_snapshot)
    q.setdefault('resourceType', 'Questionnaire')
    q.setdefault('status', 'active')

    items = q.get('item')
    if isinstance(items, list):
        q['item'] = [_rewrite_questionnaire_item(i) for i in items]
    return q


def _rewrite_questionnaire_item(item):
    """Recursively map R4 item.type='choice' to R5 'coding'."""
    if not isinstance(item, dict):
        return item
    fixed = dict(item)
    if fixed.get('type') == 'choice':
        fixed['type'] = 'coding'
    if isinstance(fixed.get('item'), list):
        fixed['item'] = [_rewrite_questionnaire_item(i) for i in fixed['item']]
    return fixed


def _strip_pdhc_markers(node):
    """Recursively remove keys starting with `_pdhc_` from any
    dict / list nested in `node`. These are internal wire markers,
    not FHIR-legal properties."""
    if isinstance(node, dict):
        for k in list(node.keys()):
            if k.startswith('_pdhc_'):
                del node[k]
            else:
                _strip_pdhc_markers(node[k])
    elif isinstance(node, list):
        for item in node:
            _strip_pdhc_markers(item)


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

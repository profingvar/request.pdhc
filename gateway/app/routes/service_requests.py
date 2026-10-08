"""Web UI routes for ServiceRequest workflow."""

import requests as http_requests
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import (
    service_request_service, patient_service,
    plan_definition_service, contract_service, form_service,
    timeline_service,
)
from app.services.match_service import (
    find_and_create_matches, find_eligible_providers,
    dispatch_to_provider, list_matches_for_request,
)
from app.services.push_service import push_all_matches, list_receipts_for_request
from app.services.auth_service import get_current_user_guid, get_current_access_blob
from app.services.reform_scope import (
    caller_org_ids as _caller_org_ids,
    caller_org_names as _caller_org_names,
)

service_requests_web_bp = Blueprint('service_requests_web', __name__)


_SSO_ORG_CACHE = {}


def _get_sso_org_name(org_guid):
    """Resolve org_guid → name via SSO public catalog (cached per process)."""
    if not org_guid:
        return None
    if org_guid in _SSO_ORG_CACHE:
        return _SSO_ORG_CACHE[org_guid]
    try:
        sso_base = current_app.config.get(
            'SSO_INTERNAL_URL', current_app.config.get('SSO_BASE_URL', '')
        ).rstrip('/')
        resp = http_requests.get(f"{sso_base}/api/public/organisations", timeout=5)
        if resp.status_code == 200:
            for o in resp.json() or []:
                gid = o.get('organisation_guid') or o.get('guid') or ''
                if gid:
                    _SSO_ORG_CACHE[gid] = o.get('name', '')
    except http_requests.RequestException:
        pass
    return _SSO_ORG_CACHE.get(org_guid)


def _clinics_for_orgs(org_ids, *, all_orgs=False):
    """Map the caller's ORGANISATION guids to ips CLINIC rows.

    The one place the two identifier spaces meet. An SSO access blob names
    organisations; ips's patient-assignment endpoint is keyed by clinic.
    `clinics.guid` != `clinics.organisation_guid`, and treating them as one
    value is #779 — a gate that did exactly that denied every non-SU caller
    while twelve unit tests passed, because the fixture fed both sides the
    same guid.

    Returns [{'org_guid', 'clinic_guid', 'name'}], ordered by name. Raises
    PatientListUnavailable if ips cannot be asked.
    """
    clinics = patient_service.list_clinics()
    wanted = {str(o) for o in (org_ids or [])}
    out = []
    for c in clinics:
        org = str(c.get('organisation_guid') or '')
        if not org:
            # A clinic with no organisation cannot be matched to an
            # affiliation. Skipped rather than shown, since selecting it
            # would scope a request to an organisation that does not exist.
            continue
        if all_orgs or org in wanted:
            out.append({'org_guid': org,
                        'clinic_guid': str(c.get('guid') or ''),
                        'name': c.get('name') or org})
    out.sort(key=lambda x: (x['name'] or '').lower())
    return out


def _patients_for_clinic(clinic_guid):
    """The ASSIGNMENT-based patient list for one clinic, from ips.

    Replaces "fetch every patient, then keep the ones whose
    managingOrganization matches". That asked a projection instead of the
    record: ips's `PatientClinicAssignment` is the fact, `managingOrganization`
    is a copy of it that can drift — ips surfaces the disagreement as
    `custodian_mismatch` (#792) rather than resolving it quietly — and the copy
    is single-valued where the assignment is many-to-many.

    Measured on production 2026-10-08: all 122 assigned patients currently
    agree and none is multi-org, so the old filter hid nobody TODAY. It was
    wrong in the way that waits: the first patient moved between clinics, or
    assigned to two, is the one it gets wrong, and the symptom is a clinician
    unable to find their own patient.
    """
    return patient_service.list_clinic_patients(clinic_guid)


@service_requests_web_bp.route('/service-requests')
@requires_auth
def list_view():
    """List ServiceRequests (org-filtered)."""
    blob = get_current_access_blob()
    is_su = blob.get('is_su_admin', False) if blob else False
    org_guid = (_caller_org_ids(blob) or [None])[0] if blob else None  # M0 #419

    status_filter = request.args.get('status')
    page = int(request.args.get('page', 1))

    data, _ = service_request_service.list_service_requests(
        user_guid=get_current_user_guid(),
        org_guid=org_guid,
        is_su_admin=is_su,
        status_filter=status_filter,
        page=page,
    )
    return render_template('service_requests/list.html',
                           items=data.get('items', []),
                           total=data.get('total', 0),
                           page=page,
                           per_page=data.get('per_page', 50),
                           status_filter=status_filter or '')


@service_requests_web_bp.route('/service-requests/archived')
@requires_auth
def archived_view():
    """List archived and revoked ServiceRequests."""
    blob = get_current_access_blob()
    is_su = blob.get('is_su_admin', False) if blob else False
    org_guid = (_caller_org_ids(blob) or [None])[0] if blob else None  # M0 #419

    status_filter = request.args.get('status', '')
    page = int(request.args.get('page', 1))

    # If a specific terminal status is chosen, use it; otherwise show both
    if status_filter in ('archived', 'revoked'):
        sf = status_filter
    else:
        sf = None

    data, _ = service_request_service.list_service_requests(
        user_guid=get_current_user_guid(),
        org_guid=org_guid,
        is_su_admin=is_su,
        status_filter=sf,
        include_archived=True,
        page=page,
    )

    # If no specific filter, manually filter to only archived+revoked
    items = data.get('items', [])
    if not sf:
        items = [i for i in items if i.get('status') in ('archived', 'revoked')]

    return render_template('service_requests/archived.html',
                           items=items,
                           total=len(items),
                           page=page,
                           per_page=data.get('per_page', 50),
                           status_filter=status_filter or '')


@service_requests_web_bp.route('/service-requests/create', methods=['GET', 'POST'])
@requires_auth
@requires_role('read_write')
def create_view():
    """Create a new ServiceRequest — pick patient + PlanDefinition."""
    blob = get_current_access_blob()
    # M0 #409: organisation_warning is being retired (S9's activation gate
    # replaced it). Compute the same fact from the reform fields when the
    # legacy flag is absent: no affiliation and no legacy org = warn.
    no_org = (blob.get('organisation_warning')
              if 'organisation_warning' in (blob or {})
              else not ((blob or {}).get('affiliations')
                        or (blob or {}).get('organization_ids')))
    if blob and no_org and not blob.get('is_su_admin'):
        flash('You must belong to an organisation before creating ServiceRequests. '
              'Contact your administrator.', 'danger')
        return redirect(url_for('service_requests_web.list_view'))

    if request.method == 'POST':
        patient_guid = request.form.get('patient_guid', '')
        plan_definition_guid = request.form.get('plan_definition_guid', '')
        notes = request.form.get('notes', '')
        requesting_org_guid = request.form.get('requesting_org_guid', '') or None

        if not patient_guid or not plan_definition_guid:
            flash('Patient and PlanDefinition are required', 'danger')
        else:
            blob = get_current_access_blob()
            is_su = bool(blob.get('is_su_admin', False)) if blob else False
            caller_org_ids_list = _caller_org_ids(blob) if blob else []  # M0 #419
            caller_org_names_map = _caller_org_names(blob) if blob else {}

            # Mirror the API gate (#226): multi-org callers must pick
            # explicitly; the chosen org must be one of theirs.
            if requesting_org_guid and not is_su \
                    and requesting_org_guid not in caller_org_ids_list:
                flash('Selected organisation is not one of yours.', 'danger')
                return redirect(url_for('service_requests_web.create_view'))
            if not requesting_org_guid and not is_su:
                if len(caller_org_ids_list) > 1:
                    flash('Pick the requesting organisation '
                          '(Lag 2022:913 chain-of-custody).', 'danger')
                    return redirect(url_for('service_requests_web.create_view'))
                if caller_org_ids_list:
                    requesting_org_guid = caller_org_ids_list[0]

            org_guid = requesting_org_guid
            org_name = caller_org_names_map.get(org_guid)  # M0 #419: paired
            user_name = blob.get('display_name', blob.get('email', '')) if blob else None

            data, status = service_request_service.create_service_request(
                patient_guid=patient_guid,
                plan_definition_guid=plan_definition_guid,
                user_guid=get_current_user_guid(),
                org_guid=org_guid,
                user_name=user_name,
                org_name=org_name,
                notes=notes,
                ip_address=request.remote_addr,
            )
            if status == 201:
                # Attach selected forms
                selected_forms = request.form.getlist('form_guids')
                for idx, fg in enumerate(selected_forms):
                    if fg:
                        service_request_service.add_form_to_request(
                            sr_guid=data['guid'],
                            form_guid=fg,
                            sort_order=idx,
                            user_guid=get_current_user_guid(),
                            ip_address=request.remote_addr,
                        )
                flash('ServiceRequest created', 'success')
                return redirect(url_for('service_requests_web.view_detail', guid=data['guid']))
            flash(f"Error: {data.get('message', 'Unknown')}", 'danger')

    # ── The organisation comes FIRST, and it decides the patient list ──
    #
    # Previously this page fetched EVERY patient from ips and filtered them in
    # Python on `Patient.managingOrganization`, while a separate "Requesting
    # organisation" control further down the form recorded chain-of-custody.
    # Two problems with that, one of shape and one of substance:
    #
    #   * The two controls could disagree. Nothing stopped a caller recording
    #     org A for custody while selecting a patient belonging to org B.
    #   * `managingOrganization` is a PROJECTION of the clinic assignment, not
    #     the record. ips treats `PatientClinicAssignment` as authoritative and
    #     reports a disagreement as `custodian_mismatch` (#792) rather than
    #     resolving it silently, exactly because the two drift.
    #
    # So there is now ONE organisation choice, at the top, and it does both
    # jobs: it scopes the patient list and it is the `requesting_org_guid`.
    blob = get_current_access_blob()
    is_su = blob.get('is_su_admin', False) if blob else False
    user_org_ids = _caller_org_ids(blob) if blob else []  # M0 #419
    caller_org_names_map = _caller_org_names(blob) if blob else {}

    patients = []
    patient_list_error = None
    org_clinics = []
    selected_org = (request.args.get('org') or '').strip() or None

    try:
        org_clinics = _clinics_for_orgs(user_org_ids, all_orgs=is_su)
    except patient_service.PatientListUnavailable as e:
        # An empty selector must never stand in for "we could not ask".
        patient_list_error = str(e)
        current_app.logger.error(
            'create_view: cannot resolve clinics from ips — %s', e)

    # A non-SU caller may only act for an organisation they are affiliated
    # with. Mirrors the POST gate below rather than trusting the query string.
    allowed_orgs = {c['org_guid'] for c in org_clinics}
    if selected_org and not is_su and selected_org not in allowed_orgs:
        flash('Selected organisation is not one of yours.', 'danger')
        selected_org = None

    # One affiliation -> no choice to make, so make it for them.
    if not selected_org and len(org_clinics) == 1:
        selected_org = org_clinics[0]['org_guid']

    if selected_org and patient_list_error is None:
        # An organisation can own more than one clinic; union their patients
        # and de-duplicate, because the caller picked the ORGANISATION.
        seen = set()
        try:
            for c in org_clinics:
                if c['org_guid'] != selected_org:
                    continue
                for pt in _patients_for_clinic(c['clinic_guid']):
                    g = str(pt.get('guid') or pt.get('id') or '')
                    if g and g not in seen:
                        seen.add(g)
                        patients.append(pt)
        except patient_service.PatientListUnavailable as e:
            patients = []
            patient_list_error = str(e)
            current_app.logger.error(
                'create_view: cannot list patients for org %s — %s',
                str(selected_org)[:8], e)
        patients.sort(key=lambda x: ((x.get('family_name') or '').lower(),
                                     (x.get('given_name') or '').lower()))

    plandefs_data, _ = plan_definition_service.list_plan_definitions()
    if isinstance(plandefs_data, dict):
        plandefs = plandefs_data.get('items', plandefs_data.get('entry', []))
    else:
        plandefs = plandefs_data if isinstance(plandefs_data, list) else []

    # Fetch full PlanDefinition data (with fhir_data/actions) for each
    plandefs_full = {}
    for pd in plandefs:
        guid = pd.get('guid', pd.get('id', ''))
        if guid:
            full_data, st = plan_definition_service.get_plan_definition(guid)
            if st == 200:
                plandefs_full[guid] = full_data

    # Fetch forms catalogue from Plan
    forms_data, _ = form_service.list_forms()
    if isinstance(forms_data, dict):
        forms_list = forms_data.get('forms', forms_data.get('items', forms_data.get('entry', [])))
    else:
        forms_list = forms_data if isinstance(forms_data, list) else []

    # The organisation picker (#226) is the SAME control as the patient-list
    # scope now, so there is one list and one selection. Names prefer the
    # access blob (what the caller is told they belong to) and fall back to the
    # ips clinic name, so a mismatch between the two shows up as a name the
    # caller does not recognise rather than silently resolving.
    caller_orgs = [
        {'guid': c['org_guid'],
         'name': caller_org_names_map.get(c['org_guid']) or c['name']}
        for c in org_clinics
    ]
    # De-duplicate: one organisation owning several clinics is one choice.
    _seen_org = set()
    caller_orgs = [o for o in caller_orgs
                   if not (o['guid'] in _seen_org or _seen_org.add(o['guid']))]

    import json
    return render_template('service_requests/create.html',
                           patients=patients, plandefs=plandefs, forms=forms_list,
                           plandefs_full_json=json.dumps(plandefs_full),
                           caller_orgs=caller_orgs,
                           selected_org=selected_org,
                           patient_list_error=patient_list_error,
                           is_su_admin=is_su)


@service_requests_web_bp.route('/service-requests/<guid>')
@requires_auth
def view_detail(guid):
    """View a single ServiceRequest with its matches."""
    data, status = service_request_service.get_service_request(guid)
    if status != 200:
        flash('ServiceRequest not found', 'danger')
        return redirect(url_for('service_requests_web.list_view'))

    # Backfill missing org name from SSO public catalog
    if data.get('requester_org_guid') and not data.get('requester_org_name'):
        data['requester_org_name'] = _get_sso_org_name(data['requester_org_guid'])

    matches_data, _ = list_matches_for_request(guid)
    matches = matches_data.get('matches', []) if isinstance(matches_data, dict) else []

    receipts_data, _ = list_receipts_for_request(guid)
    receipts = receipts_data.get('receipts', []) if isinstance(receipts_data, dict) else []

    forms_data, _ = service_request_service.list_forms_for_request(guid)
    sr_forms = forms_data.get('forms', []) if isinstance(forms_data, dict) else []

    # Resolve contract name from contract.pdhc
    contract_name = None
    contract_names = {}
    if data.get('contract_guid'):
        c_data, c_status = contract_service.get_contract(data['contract_guid'])
        if c_status == 200 and isinstance(c_data, dict):
            contract_name = c_data.get('name') or c_data.get('title')
            contract_names[data['contract_guid']] = contract_name

    # Build contract name lookup for matches
    for m in matches:
        cg = m.get('contract_guid', '')
        if cg and cg not in contract_names:
            c_data, c_status = contract_service.get_contract(cg)
            if c_status == 200 and isinstance(c_data, dict):
                contract_names[cg] = c_data.get('name') or c_data.get('title') or ''

    # Find eligible providers for active SRs (two-step dispatch)
    eligible = []
    if data.get('status') == 'active':
        elig_data, elig_status = find_eligible_providers(guid)
        if elig_status == 200:
            eligible = elig_data.get('eligible', [])

    # If draft, also fetch catalogue for add-form picker
    available_forms = []
    if data.get('status') == 'draft':
        cat_data, _ = form_service.list_forms()
        if isinstance(cat_data, dict):
            available_forms = cat_data.get('forms', cat_data.get('items', cat_data.get('entry', [])))
        elif isinstance(cat_data, list):
            available_forms = cat_data

    return render_template('service_requests/view.html', sr=data, matches=matches,
                           receipts=receipts, sr_forms=sr_forms, available_forms=available_forms,
                           contract_name=contract_name, contract_names=contract_names,
                           eligible_providers=eligible)


def _timeline_lines_for_js(tl):
    """Compact per-line payload for the metro-map hover tooltips (JS)."""
    return [
        {'index': l['index'], 'title': l['title'], 'color': l['color'],
         'cadence': l['cadence'], 'concepts': l['concepts']}
        for l in tl['lines']
    ]


@service_requests_web_bp.route('/service-requests/<guid>/timeline')
@requires_auth
def timeline_view(guid):
    """Metro-map schedule timeline for a ServiceRequest's plan.

    Draws the patient-specific snapshot (falling back to the live
    PlanDefinition), anchored at the request's period_start and bounded by its
    period_end. Endless recurrences show the first month, then a '…'.
    """
    import json
    data, status = service_request_service.get_service_request(guid)
    if status != 200:
        flash('ServiceRequest not found', 'danger')
        return redirect(url_for('service_requests_web.list_view'))

    snapshot = dict(data.get('plan_definition_snapshot') or {})
    activities = snapshot.get('activities')
    if not activities and data.get('plan_definition_guid'):
        pd, st = plan_definition_service.get_plan_definition(
            data['plan_definition_guid'])
        if st == 200 and isinstance(pd, dict):
            activities = pd.get('activities') or []
            snapshot.setdefault('title', pd.get('title') or pd.get('name'))
    activities = activities or []

    tl = timeline_service.build_timeline(
        activities,
        start_date=data.get('period_start'),
        end_date=data.get('period_end'),
    )
    plan_title = snapshot.get('title') or snapshot.get('name') or 'PlanDefinition'
    return render_template(
        'service_requests/plan_timeline.html',
        tl=tl,
        lines_json=json.dumps(_timeline_lines_for_js(tl)),
        plan_title=plan_title,
        patient_label=(data.get('patient_guid') or '')[:8] or None,
        back_url=url_for('service_requests_web.view_detail', guid=guid),
    )


@service_requests_web_bp.route('/plan-timeline/<plandef_guid>')
@requires_auth
def plan_timeline_preview(plandef_guid):
    """Metro-map preview of a PlanDefinition's schedule (no patient/SR).

    Anchored at today; recurrences are treated as endless unless the plan
    itself bounds the activity (count/duration).
    """
    import json
    pd, st = plan_definition_service.get_plan_definition(plandef_guid)
    if st != 200 or not isinstance(pd, dict):
        flash('PlanDefinition not found', 'danger')
        return redirect(url_for('service_requests_web.create_view'))
    activities = pd.get('activities') or []
    tl = timeline_service.build_timeline(activities)
    plan_title = pd.get('title') or pd.get('name') or 'PlanDefinition'
    return render_template(
        'service_requests/plan_timeline.html',
        tl=tl,
        lines_json=json.dumps(_timeline_lines_for_js(tl)),
        plan_title=plan_title,
        patient_label=None,
        back_url=request.referrer or url_for('service_requests_web.create_view'),
    )


@service_requests_web_bp.route('/service-requests/<guid>/edit-plan', methods=['GET', 'POST'])
@requires_auth
@requires_role('read_write')
def edit_plan(guid):
    """Edit the PlanDefinition snapshot (draft only)."""
    import json
    data, status = service_request_service.get_service_request(guid)
    if status != 200:
        flash('ServiceRequest not found', 'danger')
        return redirect(url_for('service_requests_web.list_view'))

    if data['status'] != 'draft':
        flash('Can only edit PlanDefinition in draft status', 'warning')
        return redirect(url_for('service_requests_web.view_detail', guid=guid))

    if request.method == 'POST':
        try:
            goals_data = json.loads(request.form.get('goal', '[]'))
            actions_data = json.loads(request.form.get('action', '[]'))
        except json.JSONDecodeError:
            flash('Invalid JSON in goals or actions', 'danger')
            return redirect(url_for('service_requests_web.edit_plan', guid=guid))

        # Rebuild snapshot with edited goals and actions + metadata
        snapshot = dict(data.get('plan_definition_snapshot') or {})
        snapshot['title'] = request.form.get('title', snapshot.get('title', ''))
        snapshot['description'] = request.form.get('description', snapshot.get('description', ''))
        snapshot['goals'] = goals_data
        snapshot['activities'] = actions_data

        result, st = service_request_service.update_plan_definition_snapshot(
            guid=guid,
            edited_snapshot=snapshot,
            user_guid=get_current_user_guid(),
            ip_address=request.remote_addr,
        )
        if st == 200:
            flash('PlanDefinition snapshot updated', 'success')
            return redirect(url_for('service_requests_web.view_detail', guid=guid))
        flash(f"Error: {result.get('message', 'Unknown')}", 'danger')

    # Fetch concepts, units, valuesets from plan.pdhc for the builder
    concepts = plan_definition_service.list_concepts()
    units = plan_definition_service.list_units()
    valuesets = plan_definition_service.list_valuesets()

    # Extract existing goals and actions from snapshot
    snapshot = data.get('plan_definition_snapshot') or {}
    existing_goals = snapshot.get('goals', [])
    existing_actions = snapshot.get('activities', [])

    return render_template('service_requests/edit_plan.html',
                           sr=data,
                           concepts_json=json.dumps(concepts),
                           units_json=json.dumps(units),
                           valuesets_json=json.dumps(valuesets),
                           existing_goals_json=json.dumps(existing_goals),
                           existing_actions_json=json.dumps(existing_actions))


@service_requests_web_bp.route('/service-requests/<guid>/finalize', methods=['POST'])
@requires_auth
@requires_role('read_write')
def finalize_view(guid):
    """Finalize a draft ServiceRequest."""
    data, status = service_request_service.finalize_service_request(
        guid=guid,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    if status == 200:
        flash('ServiceRequest finalized and active', 'success')
    else:
        flash(f"Error: {data.get('message', 'Unknown')}", 'danger')
    return redirect(url_for('service_requests_web.view_detail', guid=guid))


@service_requests_web_bp.route('/service-requests/<guid>/archive', methods=['POST'])
@requires_auth
@requires_role('read_write')
def archive_view(guid):
    """Archive a ServiceRequest."""
    data, status = service_request_service.archive_service_request(
        guid=guid,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    if status == 200:
        flash('ServiceRequest archived', 'success')
    else:
        flash(f"Error: {data.get('message', 'Unknown')}", 'danger')
    next_url = request.form.get('next')
    if next_url == 'list':
        return redirect(url_for('service_requests_web.list_view'))
    return redirect(url_for('service_requests_web.view_detail', guid=guid))


@service_requests_web_bp.route('/service-requests/<guid>/revoke', methods=['POST'])
@requires_auth
@requires_role('read_write')
def revoke_view(guid):
    """Revoke a ServiceRequest."""
    data, status = service_request_service.revoke_service_request(
        guid=guid,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    if status == 200:
        flash('ServiceRequest revoked', 'success')
    else:
        flash(f"Error: {data.get('message', 'Unknown')}", 'danger')
    next_url = request.form.get('next')
    if next_url == 'archived':
        return redirect(url_for('service_requests_web.archived_view'))
    if next_url == 'list':
        return redirect(url_for('service_requests_web.list_view'))
    return redirect(url_for('service_requests_web.view_detail', guid=guid))


@service_requests_web_bp.route('/service-requests/<guid>/find-matches', methods=['POST'])
@requires_auth
@requires_role('read_write')
def find_matches_view(guid):
    """Find matching contracts for an active ServiceRequest (legacy)."""
    data, status = find_and_create_matches(
        service_request_guid=guid,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    if status == 200:
        count = data.get('matches_created', 0)
        flash(f'{count} contract match(es) found', 'success')
    else:
        flash(f"Error: {data.get('message', 'Unknown')}", 'danger')
    return redirect(url_for('service_requests_web.view_detail', guid=guid))


@service_requests_web_bp.route('/service-requests/<guid>/dispatch', methods=['POST'])
@requires_auth
@requires_role('read_write')
def dispatch_view(guid):
    """Dispatch ServiceRequest to a chosen provider."""
    contract_guid = request.form.get('contract_guid', '')
    provider_org_guid = request.form.get('provider_org_guid', '')
    provider_name = request.form.get('provider_name', '')

    if not contract_guid or not provider_org_guid:
        flash('Missing contract or provider', 'danger')
        return redirect(url_for('service_requests_web.view_detail', guid=guid))

    data, status = dispatch_to_provider(
        service_request_guid=guid,
        contract_guid=contract_guid,
        provider_org_guid=provider_org_guid,
        provider_name=provider_name,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    if status == 200:
        flash(f'Dispatched to {provider_name or provider_org_guid}', 'success')
    else:
        flash(f"Error: {data.get('message', 'Unknown')}", 'danger')
    return redirect(url_for('service_requests_web.view_detail', guid=guid))


@service_requests_web_bp.route('/service-requests/<guid>/add-form', methods=['POST'])
@requires_auth
@requires_role('read_write')
def add_form_view(guid):
    """Attach a form to a draft ServiceRequest."""
    form_guid = request.form.get('form_guid', '')
    if not form_guid:
        flash('No form selected', 'danger')
    else:
        data, status = service_request_service.add_form_to_request(
            sr_guid=guid,
            form_guid=form_guid,
            sort_order=int(request.form.get('sort_order', 0)),
            user_guid=get_current_user_guid(),
            ip_address=request.remote_addr,
        )
        if status == 201:
            flash('Form attached', 'success')
        else:
            flash(f"Error: {data.get('message', 'Unknown')}", 'danger')
    return redirect(url_for('service_requests_web.view_detail', guid=guid))


@service_requests_web_bp.route('/service-requests/<guid>/remove-form/<form_sr_guid>', methods=['POST'])
@requires_auth
@requires_role('read_write')
def remove_form_view(guid, form_sr_guid):
    """Remove an attached form from a draft ServiceRequest."""
    data, status = service_request_service.remove_form_from_request(
        sr_guid=guid,
        form_sr_guid=form_sr_guid,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    if status == 200:
        flash('Form removed', 'success')
    else:
        flash(f"Error: {data.get('message', 'Unknown')}", 'danger')
    return redirect(url_for('service_requests_web.view_detail', guid=guid))


@service_requests_web_bp.route('/service-requests/<guid>/form/<form_sr_guid>')
@requires_auth
def view_form_detail(guid, form_sr_guid):
    """View a single attached form's Questionnaire + render-ready JSON."""
    import json as json_mod
    sr_data, sr_status = service_request_service.get_service_request(guid)
    if sr_status != 200:
        flash('ServiceRequest not found', 'danger')
        return redirect(url_for('service_requests_web.list_view'))

    forms_data, _ = service_request_service.list_forms_for_request(guid)
    sr_forms = forms_data.get('forms', []) if isinstance(forms_data, dict) else []
    form_detail = next((f for f in sr_forms if f['guid'] == form_sr_guid), None)
    if not form_detail:
        flash('Form attachment not found', 'danger')
        return redirect(url_for('service_requests_web.view_detail', guid=guid))

    return render_template('service_requests/form_detail.html',
                           sr=sr_data, form=form_detail,
                           snapshot_json=json_mod.dumps(form_detail.get('form_snapshot'), indent=2) if form_detail.get('form_snapshot') else None,
                           render_ready_json=json_mod.dumps(form_detail.get('render_ready_snapshot'), indent=2) if form_detail.get('render_ready_snapshot') else None)


@service_requests_web_bp.route('/service-requests/<guid>/push-all', methods=['POST'])
@requires_auth
@requires_role('read_write')
def push_all_view(guid):
    """Push ServiceRequest to all pending matched providers."""
    data, status = push_all_matches(
        service_request_guid=guid,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    if status == 200:
        count = data.get('pushed', 0)
        flash(f'Pushed to {count} provider(s)', 'success')
    else:
        flash(f"Error: {data.get('message', 'Unknown')}", 'danger')
    return redirect(url_for('service_requests_web.view_detail', guid=guid))

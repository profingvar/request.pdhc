"""Web UI routes for ServiceRequest workflow."""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import (
    service_request_service, patient_service,
    plan_definition_service, contract_service, form_service,
)
from app.services.match_service import find_and_create_matches, list_matches_for_request
from app.services.push_service import push_all_matches, list_receipts_for_request
from app.services.auth_service import get_current_user_guid, get_current_access_blob

service_requests_web_bp = Blueprint('service_requests_web', __name__)


def _patient_matches_org(patient, org_ids):
    """Check if a patient's managingOrganization matches any of the user's orgs."""
    managing = patient.get('managingOrganization', {})
    ref = managing.get('reference', '')
    # ref is like "Organization/some-guid"
    if ref.startswith('Organization/'):
        patient_org = ref.replace('Organization/', '')
        return patient_org in org_ids
    return False


@service_requests_web_bp.route('/service-requests')
@requires_auth
def list_view():
    """List ServiceRequests (org-filtered)."""
    blob = get_current_access_blob()
    is_su = blob.get('is_su_admin', False) if blob else False
    org_guid = (blob.get('organization_ids') or [None])[0] if blob else None

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
    org_guid = (blob.get('organization_ids') or [None])[0] if blob else None

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
    if blob and blob.get('organisation_warning') and not blob.get('is_su_admin'):
        flash('You must belong to an organisation before creating ServiceRequests. '
              'Contact your administrator.', 'danger')
        return redirect(url_for('service_requests_web.list_view'))

    if request.method == 'POST':
        patient_guid = request.form.get('patient_guid', '')
        plan_definition_guid = request.form.get('plan_definition_guid', '')
        notes = request.form.get('notes', '')

        if not patient_guid or not plan_definition_guid:
            flash('Patient and PlanDefinition are required', 'danger')
        else:
            blob = get_current_access_blob()
            org_guid = (blob.get('organization_ids') or [None])[0] if blob else None
            org_name = (blob.get('organization_names') or [None])[0] if blob else None
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

    # Fetch patients from IPS and filter by organisation
    blob = get_current_access_blob()
    is_su = blob.get('is_su_admin', False) if blob else False
    user_org_ids = blob.get('organization_ids', []) if blob else []

    patients_data, ps = patient_service.list_patients()
    patients = []
    if ps == 200:
        if isinstance(patients_data, dict) and patients_data.get('resourceType') == 'Bundle':
            patients = [e.get('resource', e) for e in patients_data.get('entry', [])]
        elif isinstance(patients_data, list):
            patients = patients_data

        # Non-SU users: filter to patients from their organisation(s)
        if not is_su and user_org_ids:
            patients = [
                p for p in patients
                if _patient_matches_org(p, user_org_ids)
            ]

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

    import json
    return render_template('service_requests/create.html',
                           patients=patients, plandefs=plandefs, forms=forms_list,
                           plandefs_full_json=json.dumps(plandefs_full))


@service_requests_web_bp.route('/service-requests/<guid>')
@requires_auth
def view_detail(guid):
    """View a single ServiceRequest with its matches."""
    data, status = service_request_service.get_service_request(guid)
    if status != 200:
        flash('ServiceRequest not found', 'danger')
        return redirect(url_for('service_requests_web.list_view'))

    matches_data, _ = list_matches_for_request(guid)
    matches = matches_data.get('matches', []) if isinstance(matches_data, dict) else []

    receipts_data, _ = list_receipts_for_request(guid)
    receipts = receipts_data.get('receipts', []) if isinstance(receipts_data, dict) else []

    forms_data, _ = service_request_service.list_forms_for_request(guid)
    sr_forms = forms_data.get('forms', []) if isinstance(forms_data, dict) else []

    # If draft, also fetch catalogue for add-form picker
    available_forms = []
    if data.get('status') == 'draft':
        cat_data, _ = form_service.list_forms()
        if isinstance(cat_data, dict):
            available_forms = cat_data.get('forms', cat_data.get('items', cat_data.get('entry', [])))
        elif isinstance(cat_data, list):
            available_forms = cat_data

    return render_template('service_requests/view.html', sr=data, matches=matches,
                           receipts=receipts, sr_forms=sr_forms, available_forms=available_forms)


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
    return redirect(url_for('service_requests_web.view_detail', guid=guid))


@service_requests_web_bp.route('/service-requests/<guid>/find-matches', methods=['POST'])
@requires_auth
@requires_role('read_write')
def find_matches_view(guid):
    """Find matching contracts for an active ServiceRequest."""
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

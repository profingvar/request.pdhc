import re

from flask import (Blueprint, current_app, render_template, request, redirect,
                   url_for, flash)
from app.middleware.auth_middleware import requires_auth, requires_role
from app.services import care_hierarchy_service, patient_service
from app.services.audit_service import log_event
from app.services.auth_service import (get_current_user_guid,
                                       get_upstream_token)

#: The Swedish personal identity number OID, as ips stamps it.
PERSONNUMMER_SYSTEM = 'urn:oid:1.2.752.129.2.1.3.1'

_PNR_RE = re.compile(r'^(?:\d{8}|\d{6})-\d{4}$')


def _personnummer_problem(value):
    """A SHAPE problem with the value, or None. Deliberately not a checksum.

    An earlier version of this computed the Luhn check digit here and got it
    wrong — it reported "check digit does not match" for 19610115-9638, a
    number ips's own generator produced and considers valid. Telling a
    clinician that a real patient's identifier is invalid is worse than saying
    nothing about it, so the checksum is gone rather than debugged.

    ips owns the authoritative check (`gateway/app/services/personnummer.py`,
    #789) and this service should ask it rather than keep a second
    implementation that can disagree — two implementations of one rule is the
    shape that cost #784 and #786 a day each. There is no endpoint for it
    today; until there is, this reports only what can be judged without
    arithmetic.

    That is still worth doing, because it catches the fault actually present
    in the data: #789 produced 15-character values with the century doubled
    ("19" + "19580314" -> 1919580314-8691), and patients created before the
    fix still carry them. A wrong LENGTH is unambiguous.
    """
    v = (value or '').strip()
    if not _PNR_RE.match(v):
        return (f'not the shape of a personnummer — expected YYYYMMDD-NNNN '
                f'or YYMMDD-NNNN, got {len(v)} characters. A 15-character '
                f'value is the doubled-century bug (#789)')
    return None


patients_web_bp = Blueprint('patients_web', __name__)


@patients_web_bp.route('/patients')
@requires_auth
def list_patients():
    params = dict(request.args)
    data, status = patient_service.list_patients(params)
    patients = []
    if status == 200:
        if isinstance(data, dict) and data.get('resourceType') == 'Bundle':
            patients = [e.get('resource', e) for e in data.get('entry', [])]
        elif isinstance(data, list):
            patients = data
    return render_template('patients/list.html', patients=patients, params=params)


@patients_web_bp.route('/patients/<guid>')
@requires_auth
def view_patient(guid):
    """Everything ips holds about this patient, plus both organisation levels.

    Three things this page has to get right, each of which it previously did
    not:

    **The assignment, not the projection.** `Patient.managingOrganization` is a
    copy of the clinic assignment that can drift; ips treats
    `PatientClinicAssignment` as the record and reports a disagreement as
    `custodian_mismatch` (#792) rather than resolving it. Both are shown, and
    labelled for what they are.

    **Caregiver AND care unit, each with name and guid.** ips knows only which
    organisation; whether that organisation is a vårdgivare or a vårdenhet
    lives in sso. The level matters legally — a vårdenhet is the spärrgräns,
    the boundary a block applies across — so the page says which it is instead
    of printing one name labelled "organisation".

    **Unavailable is not absent.** Each of the three sources can fail
    independently, and each failure is reported as a failure rather than as an
    empty field. "This patient has no caregiver" and "we could not ask sso"
    look identical in a table and mean opposite things.
    """
    data, status = patient_service.get_patient(guid)
    if status != 200:
        flash(f"Error loading patient: {data.get('message', 'Unknown error')}", 'danger')
        return redirect(url_for('patients_web.list_patients'))

    # ── the authoritative assignment ──
    assignments, assignment_error = [], None
    try:
        assignments = patient_service.get_patient_clinics(guid)
    except patient_service.PatientListUnavailable as e:
        assignment_error = str(e)
        current_app.logger.error(
            'view_patient %s: cannot read clinic assignments — %s',
            str(guid)[:8], e)

    # ── each assigned organisation placed in sso's care hierarchy ──
    bearer = get_upstream_token()
    hierarchy, hierarchy_error = [], None
    seen_orgs = set()
    for a in assignments:
        org = str(a.get('organisation_guid') or '')
        if not org or org in seen_orgs:
            continue
        seen_orgs.add(org)
        entry = {'clinic_guid': a.get('guid'), 'clinic_name': a.get('name'),
                 'org_guid': org, 'resolved': None}
        if hierarchy_error is None:
            try:
                entry['resolved'] = care_hierarchy_service.resolve(org, bearer)
            except care_hierarchy_service.HierarchyUnavailable as e:
                hierarchy_error = str(e)
                current_app.logger.error(
                    'view_patient %s: cannot resolve org %s in sso — %s',
                    str(guid)[:8], org[:8], e)
        hierarchy.append(entry)

    # ── the managingOrganization projection, and whether it agrees ──
    ref = ((data.get('managingOrganization') or {}).get('reference') or '')
    managing_guid = ref.split('/')[-1] if '/' in ref else ''
    managing_name = (data.get('managingOrganization') or {}).get('display')
    custodian_mismatch = None
    if assignment_error is None:
        if managing_guid and not assignments:
            custodian_mismatch = (
                f'The Patient resource names organisation {managing_guid}, but '
                f'ips records NO clinic assignment. The assignment is the '
                f'record, so this patient is invisible to every '
                f'organisation-scoped reader.')
        elif managing_guid and managing_guid not in seen_orgs:
            custodian_mismatch = (
                f'managingOrganization is {managing_guid} but the '
                f'authoritative assignment is '
                f'{", ".join(sorted(seen_orgs))}. The assignment wins; the '
                f'Patient resource is stale.')

    # ── is the personnummer actually valid? ──
    identifiers = []
    for ident in (data.get('identifier') or []):
        val = ident.get('value') or ''
        entry = {'system': ident.get('system') or '', 'value': val,
                 'problem': None}
        if entry['system'] == PERSONNUMMER_SYSTEM and val:
            # #789 produced 15-character values with the century doubled
            # ("19" + "19580314"), whose check digit was right about 10% of
            # the time by chance. Patients created before that fix still
            # carry them, so the page checks rather than displaying a broken
            # identifier as though it were fine.
            entry['problem'] = _personnummer_problem(val)
        identifiers.append(entry)

    return render_template('patients/view.html', patient=data,
                           identifiers=identifiers,
                           assignments=assignments,
                           assignment_error=assignment_error,
                           hierarchy=hierarchy,
                           hierarchy_error=hierarchy_error,
                           managing_guid=managing_guid,
                           managing_name=managing_name,
                           custodian_mismatch=custodian_mismatch)


@patients_web_bp.route('/patients/create', methods=['GET', 'POST'])
@requires_auth
@requires_role('read_write')
def create_patient():
    if request.method == 'POST':
        payload = {
            'resourceType': 'Patient',
            'name': [{'family': request.form.get('family', ''), 'given': [request.form.get('given', '')]}],
            'gender': request.form.get('gender', ''),
            'birthDate': request.form.get('birthDate', ''),
            'active': request.form.get('active', 'true') == 'true',
        }
        telecom_value = request.form.get('telecom', '')
        if telecom_value:
            payload['telecom'] = [{'system': 'phone', 'value': telecom_value}]

        data, status = patient_service.create_patient(payload)
        if status in (200, 201):
            log_event(
                user_guid=get_current_user_guid(),
                action='patient.create',
                resource_type='Patient',
                resource_guid=data.get('id', ''),
                ip_address=request.remote_addr,
            )
            flash('Patient created successfully', 'success')
            return redirect(url_for('patients_web.list_patients'))
        flash(f"Error: {data.get('message', 'Creation failed')}", 'danger')

    return render_template('patients/create.html')


@patients_web_bp.route('/patients/<guid>/edit', methods=['GET', 'POST'])
@requires_auth
@requires_role('read_write')
def edit_patient(guid):
    if request.method == 'POST':
        payload = {
            'resourceType': 'Patient',
            'id': guid,
            'name': [{'family': request.form.get('family', ''), 'given': [request.form.get('given', '')]}],
            'gender': request.form.get('gender', ''),
            'birthDate': request.form.get('birthDate', ''),
            'active': request.form.get('active', 'true') == 'true',
        }
        telecom_value = request.form.get('telecom', '')
        if telecom_value:
            payload['telecom'] = [{'system': 'phone', 'value': telecom_value}]

        data, status = patient_service.update_patient(guid, payload)
        if status in (200, 201):
            log_event(
                user_guid=get_current_user_guid(),
                action='patient.update',
                resource_type='Patient',
                resource_guid=guid,
                ip_address=request.remote_addr,
            )
            flash('Patient updated', 'success')
            return redirect(url_for('patients_web.view_patient', guid=guid))
        flash(f"Error: {data.get('message', 'Update failed')}", 'danger')

    data, status = patient_service.get_patient(guid)
    if status != 200:
        flash('Patient not found', 'danger')
        return redirect(url_for('patients_web.list_patients'))
    return render_template('patients/edit.html', patient=data)


@patients_web_bp.route('/patients/<guid>/delete', methods=['POST'])
@requires_auth
@requires_role('read_write')
def delete_patient(guid):
    data, status = patient_service.delete_patient(guid)
    if status == 200:
        log_event(
            user_guid=get_current_user_guid(),
            action='patient.delete',
            resource_type='Patient',
            resource_guid=guid,
            ip_address=request.remote_addr,
        )
        flash('Patient deleted', 'success')
    else:
        flash(f"Error: {data.get('message', 'Delete failed')}", 'danger')
    return redirect(url_for('patients_web.list_patients'))

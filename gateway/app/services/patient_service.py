import requests
from flask import current_app

from app.services.session_headers import outbound_session_headers


def _headers():
    """Build headers for upstream IPS requests using service API key."""
    headers = {'Content-Type': 'application/fhir+json', 'Accept': 'application/fhir+json'}
    api_key = current_app.config.get('IPS_API_KEY')
    if api_key:
        headers['Authorization'] = f'ApiKey {api_key}'
    headers.update(outbound_session_headers())
    return headers


def _ips_url(path=''):
    base = current_app.config['IPS_BASE_URL'].rstrip('/')
    return f"{base}/fhir/Patient{path}"


def list_patients(params=None):
    """List/search patients from IPS backend."""
    try:
        resp = requests.get(_ips_url(), headers=_headers(), params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def get_patient(guid):
    """Get a single patient by GUID from IPS backend."""
    try:
        resp = requests.get(_ips_url(f'/{guid}'), headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return {'code': 'not_found', 'message': f'Patient {guid} not found'}, 404
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def create_patient(payload):
    """Create a patient on IPS backend."""
    try:
        resp = requests.post(_ips_url(), headers=_headers(), json=payload, timeout=15)
        if resp.status_code in (400, 422):
            return resp.json(), resp.status_code
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def update_patient(guid, payload):
    """Update a patient on IPS backend."""
    try:
        resp = requests.put(_ips_url(f'/{guid}'), headers=_headers(), json=payload, timeout=15)
        if resp.status_code in (400, 404, 422):
            return resp.json(), resp.status_code
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def delete_patient(guid):
    """Delete a patient on IPS backend."""
    try:
        resp = requests.delete(_ips_url(f'/{guid}'), headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return {'code': 'not_found', 'message': f'Patient {guid} not found'}, 404
        resp.raise_for_status()
        if resp.status_code == 204:
            return {'message': 'Patient deleted'}, 200
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def get_patient_clinic_guids(patient_guid):
    """Return the list of clinic GUIDs a patient is assigned to via
    ips.pdhc PatientClinicAssignment.

    **NOT FOR AUTHORISATION. Use `get_patient_clinic_orgs` for that.**

    These are ips `Clinic.guid` primary keys. An access blob carries sso
    ORGANISATION guids, and the two spaces are never equal — 0 of ips's 9
    clinics had `guid == organisation_guid` when measured 2026-10-06. The
    ServiceRequest create gate used to intersect this return value with
    `caller_org_ids` and therefore denied every non-SU caller for as long as it
    existed (#779). It was invisible because all 27 ServiceRequests on the
    platform were created by an SU admin, who skips the gate.

    As of #779 this function has **no callers**. It is kept because the
    deployed tree may lag local git, so deleting it here could break a release
    that still imports it — not because anything should start using it.

    Was used by ServiceRequest create to enforce patient-org need-to-know
    (PDL Ch 4 §§ 1-2; ticket #225), until #779 corrected the comparison.

    Returns:
        (clinic_guids: list[str], status: int)
        On success: ([...], 200) — may be empty list when patient has
        no assignments.
        On not-found: ([], 404).
        On upstream error: ([], 502 or 5xx as returned).
    """
    base = current_app.config['IPS_BASE_URL'].rstrip('/')
    url = f"{base}/api/v1/patients/{patient_guid}/clinics"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return [], 404
        resp.raise_for_status()
        clinics = resp.json() or []
        return [c.get('guid') for c in clinics if c.get('guid')], 200
    except requests.RequestException as e:
        current_app.logger.warning(
            "ips.pdhc patient-clinics lookup failed for %s: %s",
            patient_guid, e,
        )
        return [], 502


def get_patient_clinic_orgs(patient_guid):
    """Return the patient's clinics as (clinic_guid, organisation_guid) pairs.

    The ORGANISATION guid is the one the platform records on a datapoint
    (#768/#774) — `Clinic.guid` is ips's own primary key and lives in a
    different identifier space entirely. `get_patient_clinic_guids` above
    already fetches this response and keeps only the clinic guid, discarding
    the organisation; this returns both so a caller can record the right one.

    Measured 2026-10-06: 0 of ips's 9 clinics have `guid == organisation_guid`.
    They are never interchangeable. See #779.

    Returns:
        (pairs: list[tuple[str, str | None]], status: int)
        On success: ([(clinic_guid, organisation_guid), ...], 200) — the
        organisation may be None, because `Clinic.organisation_guid` is
        nullable. The empty list is a valid 200: the patient exists with no
        assignments.
        On not-found: ([], 404). On upstream error: ([], 502 or the 5xx seen).
    """
    base = current_app.config['IPS_BASE_URL'].rstrip('/')
    url = f"{base}/api/v1/patients/{patient_guid}/clinics"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return [], 404
        resp.raise_for_status()
        clinics = resp.json() or []
        return ([(c.get('guid'), c.get('organisation_guid'))
                 for c in clinics if c.get('guid')], 200)
    except requests.RequestException as e:
        current_app.logger.warning(
            "ips clinic/org lookup failed for patient %s: %s", patient_guid, e)
        return [], 502


def resolve_patient_org_guid(patient_guid):
    """The single organisation to record on this patient's data, or None.

    #768: one organisation identifier per datapoint, and it is the one the
    patient was affiliated with in ips **at request time**. ips keeps no
    assignment history — `patient_clinic_assignments` has `assigned_at` and no
    end timestamp — so this value cannot be reconstructed later. It must be
    captured now and stored.

    Returns None, deliberately, rather than guessing, when:

    * the patient has **no** clinic assignment (28 of ips's 150 patients today);
    * the patient has **several** and they resolve to different organisations —
      all 122 assigned patients have exactly one today, so this is a guard, not
      a workflow. `PatientIndex` has no primary/home field to break the tie, and
      inventing a rule here would write a guess into every subsequent datapoint;
    * the clinic carries no `organisation_guid` (the column is nullable);
    * ips cannot answer.

    A NULL that is visible is better than a plausible value that is wrong — the
    same rule #665 applied to `author_org_guid`.
    """
    pairs, status = get_patient_clinic_orgs(patient_guid)
    if status != 200:
        return None
    orgs = {o for _, o in pairs if o}
    if len(orgs) == 1:
        return orgs.pop()
    if len(orgs) > 1:
        current_app.logger.info(
            "patient %s resolves to %d organisations %s — recording none, "
            "because choosing would be a guess (#774)",
            patient_guid, len(orgs), sorted(orgs))
    return None

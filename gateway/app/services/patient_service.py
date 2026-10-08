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


def _ips_api(path):
    """Build a URL on ips's own `/api/v1` surface (not the FHIR facade)."""
    base = current_app.config['IPS_BASE_URL'].rstrip('/')
    return f"{base}/api/v1{path}"


class PatientListUnavailable(RuntimeError):
    """ips could not be asked which patients belong to a clinic.

    Deliberately NOT the same thing as "this clinic has no patients". A
    clinician who is shown an empty patient selector concludes there is nobody
    to request for; if the real answer is "we could not reach ips", that is a
    different problem with a different fix, and conflating the two is the
    mistake that let request.pdhc's spärr filter hide nothing for months while
    looking healthy (see #783, and ips's own auth notes).

    Raised rather than returned so a caller cannot accidentally treat it as a
    list.
    """


def list_clinics():
    """Active clinics from ips, each carrying its `organisation_guid`.

    This is the ONLY place the two identifier spaces meet: an SSO access blob
    names **organisations**, while ips's patient-assignment endpoint is keyed
    by **clinic**. `clinics.guid` and `clinics.organisation_guid` are different
    values and comparing them as one is #779 — a gate that did exactly that
    denied every non-SU caller while twelve unit tests passed, because the
    fixture fed both sides the same value.
    """
    try:
        resp = requests.get(_ips_api('/clinics'), headers=_headers(), timeout=15)
    except requests.RequestException as e:
        raise PatientListUnavailable(f"ips clinics unreachable: {e}") from e
    if resp.status_code != 200:
        raise PatientListUnavailable(
            f"ips returned {resp.status_code} for /clinics"
            + ("" if current_app.config.get('IPS_API_KEY')
               else " — this service holds no IPS_API_KEY, so the request was "
                    "unauthenticated; that is a MISSING CREDENTIAL here, not "
                    "an ips outage"))
    data = resp.json()
    return data if isinstance(data, list) else []


def _ips_computed(patient_guid, leaf):
    """GET one of ips's COMPUTED euIPS views for a patient.

    Both `/euips-sections` and `/euips-header` are derived on every call — ips
    deliberately stores no copy, because a stored copy of a derivable fact is
    the shape that produced #779 and #771. So this is always current and there
    is nothing here to cache.

    ips accepts either of its two patient identifiers on these routes, which
    matters because this service's patient pages carry the FHIR resource id.
    """
    try:
        resp = requests.get(_ips_api(f'/patients/{patient_guid}/{leaf}'),
                            headers=_headers(), timeout=15)
    except requests.RequestException as e:
        raise PatientListUnavailable(f"ips unreachable for {leaf}: {e}") from e
    if resp.status_code == 404:
        # ips knows of no such patient. A real answer, not a failure.
        return None
    if resp.status_code != 200:
        raise PatientListUnavailable(
            f"ips returned {resp.status_code} for {leaf}")
    data = resp.json()
    return data if isinstance(data, dict) else None


def get_euips_sections(patient_guid):
    """euIPS section coverage: all 17 headings and the state of each.

    Three states per section, and the middle one is the point: PRESENT,
    EXPLICITLY_ABSENT ("no known allergies" — which the guideline REQUIRES
    rather than an empty section), and MISSING. Before ips distinguished them,
    "nothing recorded" and "the clinician confirmed there is nothing" were the
    same value.
    """
    return _ips_computed(patient_guid, 'euips-sections')


def get_euips_header(patient_guid):
    """euIPS document-header coverage: contacts, insurance, author, custodian.

    `legal_guardian` comes back as `not_applicable` for an adult rather than
    `missing`, because an adult without a guardian is correct and scoring it
    as a gap would push a generator toward inventing one.
    """
    return _ips_computed(patient_guid, 'euips-header')


def get_patient_clinics(patient_guid):
    """The clinics a patient is ASSIGNED to — ips's authoritative answer.

    ips accepts either of its two patient identifiers here (the platform
    `guid` or the FHIR `resource_id`), which matters because this service's
    patient pages are built on the FHIR id. Before that was true the call
    answered 404 "Patient not found" for a patient who plainly existed.

    An empty list means ips answered and the patient has no assignment — a
    real and consequential state, since such a patient is invisible to every
    organisation-scoped reader. It is NOT the same as being unable to ask,
    which raises.
    """
    try:
        resp = requests.get(_ips_api(f'/patients/{patient_guid}/clinics'),
                            headers=_headers(), timeout=15)
    except requests.RequestException as e:
        raise PatientListUnavailable(
            f"ips unreachable for patient {str(patient_guid)[:8]}: {e}") from e
    if resp.status_code == 404:
        return []
    if resp.status_code != 200:
        raise PatientListUnavailable(
            f"ips returned {resp.status_code} for patient "
            f"{str(patient_guid)[:8]}/clinics")
    data = resp.json()
    return data if isinstance(data, list) else []


def list_clinic_patients(clinic_guid):
    """Patients ASSIGNED to a clinic — the authoritative list.

    Backed by ips's `PatientClinicAssignment` table, which is the fact. The
    Patient resource's `managingOrganization` is a PROJECTION of it and may
    disagree: ips reports such a disagreement as `custodian_mismatch` rather
    than resolving it silently (#792), precisely because the two can drift.

    Filtering a patient list on `managingOrganization` therefore asks a copy
    instead of the record. It is also single-valued where the assignment is
    many-to-many, so a patient assigned to two clinics can only ever match one.
    """
    try:
        resp = requests.get(_ips_api(f'/clinics/{clinic_guid}/patients'),
                            headers=_headers(), timeout=15)
    except requests.RequestException as e:
        raise PatientListUnavailable(
            f"ips unreachable for clinic {str(clinic_guid)[:8]}: {e}") from e
    if resp.status_code == 404:
        # A genuine answer: ips knows of no such clinic.
        return []
    if resp.status_code != 200:
        raise PatientListUnavailable(
            f"ips returned {resp.status_code} for clinic "
            f"{str(clinic_guid)[:8]}")
    data = resp.json()
    return data if isinstance(data, list) else []


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


class PatientOrgUnresolved(Exception):
    """No single organisation could be established for this patient.

    Carries a machine `code` and the facts behind it, so the API layer can
    refuse with something the operator can act on rather than a bare 409.
    """

    def __init__(self, code, message, *, orgs=(), clinics=()):
        super().__init__(message)
        self.code = code
        self.message = message
        self.orgs = sorted(orgs)
        self.clinics = sorted(clinics)

    def as_details(self):
        return {'reason': self.code,
                'patient_org_guids': self.orgs,
                'patient_clinic_guids': self.clinics}


def resolve_patient_org_guid(patient_guid, *, requesting_org_guid=None):
    """The single organisation to record on this patient's data.

    #768: one organisation identifier per datapoint, and it is the one the
    patient was affiliated with in ips **at request time**. ips keeps no
    assignment history — `patient_clinic_assignments` has `assigned_at` and no
    end timestamp — so this value cannot be reconstructed later. It must be
    captured now and stored.

    Operator decisions, 2026-10-07:

    * **No clinic → REFUSE** (28 of ips's 150 patients today). #735 requires the
      organisation on every datapoint, so a NULL row is the non-compliant
      artefact these tickets exist to prevent; it would also be invisible to
      every organisation-scoped reader under Rule 24, meaning data collected and
      then unreadable by the people who collected it. Refusing surfaces the gap
      where someone can fix it.
    * **Several clinics → ALLOW**, resolved by `requesting_org_guid`.

    The tie-break is NOT invented here, which was the objection to allowing it.
    It reuses a choice the caller has already been forced to make explicitly:

    * a single-org caller has `requesting_org_guid` auto-filled;
    * a multi-org caller **must** specify it (#226 — silent first-pick was the
      antipattern that ticket removed);
    * and for a non-SU caller the #779 gate has already established that one of
      the patient's clinic organisations is among the caller's own.

    So in the realistic path there is a definite answer and no guessing. When
    several organisations remain and none is the requesting one — reachable
    mainly for an SU admin, who bypasses the #779 gate — this raises
    `patient_org_ambiguous` rather than picking by `assigned_at` or guid order.
    Either of those would write an invented rule onto every subsequent datapoint
    for that patient. Asking for explicitness costs one error; guessing is
    permanent.

    Raises:
        PatientOrgUnresolved: with `code` one of `patient_not_found`,
        `ips_unavailable`, `patient_org_unassigned`, `patient_org_ambiguous`.

    Returns:
        str: the organisation guid to stamp on the datapoint.
    """
    pairs, status = get_patient_clinic_orgs(patient_guid)
    if status == 404:
        raise PatientOrgUnresolved(
            'patient_not_found',
            f'Patient {patient_guid} not found in ips.')
    if status != 200:
        # Fail closed. An unreachable ips is not permission to write a row
        # with no organisation on it.
        raise PatientOrgUnresolved(
            'ips_unavailable',
            'Could not reach ips to establish the patient’s organisation; '
            'try again shortly.')

    clinics = [c for c, _o in pairs if c]
    orgs = {o for _c, o in pairs if o}

    if not orgs:
        # Either no clinic assignment at all, or every assigned clinic has a
        # NULL organisation_guid (#780 found one pointing at an organisation
        # sso had never issued). Both mean the same thing here.
        raise PatientOrgUnresolved(
            'patient_org_unassigned',
            'This patient has no clinic assignment in ips with an '
            'organisation, so the organisation required on every datapoint '
            'cannot be determined. Assign the patient to a clinic before '
            'requesting data collection.',
            clinics=clinics)

    if len(orgs) == 1:
        return next(iter(orgs))

    if requesting_org_guid and requesting_org_guid in orgs:
        current_app.logger.info(
            "patient %s is affiliated with %d organisations; recording the "
            "requesting one (%s) per the 2026-10-07 decision",
            patient_guid, len(orgs), requesting_org_guid)
        return requesting_org_guid

    raise PatientOrgUnresolved(
        'patient_org_ambiguous',
        'This patient is affiliated with several organisations and none of '
        'them is the requesting organisation, so which one this request is '
        'made under cannot be determined. Specify requesting_org_guid as one '
        'of the patient’s organisations.',
        orgs=orgs, clinics=clinics)

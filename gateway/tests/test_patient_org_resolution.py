"""#774 — resolve the patient's organisation from ips, or record nothing.

#768: one organisation per datapoint, and it is the one the patient was
affiliated with in ips AT REQUEST TIME. ips keeps no assignment history —
`patient_clinic_assignments` has `assigned_at` and no end timestamp — so this
cannot be reconstructed later and must be snapshotted.

The hard part is not the lookup; it is refusing to guess. A plausible wrong
organisation on a datapoint is worse than a visible NULL, because org scoping
and spärr are decided on it.
"""
from unittest.mock import patch

import pytest

from app.services import patient_service

CLINIC_A = "clinic-aaaa"
ORG_A = "org-aaaa"
CLINIC_B = "clinic-bbbb"
ORG_B = "org-bbbb"


def _clinics(*pairs):
    return [{"guid": c, "organisation_guid": o, "name": "c"} for c, o in pairs]


def _resolve(app, clinics, status=200):
    with app.app_context():
        with patch.object(patient_service, "get_patient_clinic_orgs",
                          return_value=(clinics, status)):
            return patient_service.resolve_patient_org_guid("pat-1")


def test_one_clinic_resolves_to_its_organisation(app):
    assert _resolve(app, [(CLINIC_A, ORG_A)]) == ORG_A


def test_the_CLINIC_guid_is_never_returned(app):
    """clinic_guid and organisation_guid are different identifier spaces — 0 of
    ips's 9 clinics have them equal. Returning the clinic guid would put a value
    in the column that no sso organisation matches (#779)."""
    got = _resolve(app, [(CLINIC_A, ORG_A)])
    assert got == ORG_A and got != CLINIC_A


def test_no_clinic_records_nothing(app):
    """28 of ips's 150 patients have no assignment. The nil UUID is what
    cdr2/cdr3 ended up with on 5,258,600 rows; None is visible, nil is not."""
    assert _resolve(app, []) is None


def test_several_organisations_record_nothing_rather_than_choosing(app):
    """All 122 assigned patients have exactly one clinic today, so this is a
    guard rather than a workflow. PatientIndex has no primary/home field to
    break the tie, and inventing a rule writes a guess into every subsequent
    datapoint."""
    assert _resolve(app, [(CLINIC_A, ORG_A), (CLINIC_B, ORG_B)]) is None


def test_two_clinics_in_the_SAME_organisation_still_resolve(app):
    """Several clinics is not ambiguity if they agree on the organisation."""
    assert _resolve(app, [(CLINIC_A, ORG_A), (CLINIC_B, ORG_A)]) == ORG_A


def test_a_clinic_with_no_organisation_guid_records_nothing(app):
    """Clinic.organisation_guid is nullable."""
    assert _resolve(app, [(CLINIC_A, None)]) is None


@pytest.mark.parametrize("status", [404, 502, 500])
def test_an_unanswerable_lookup_records_nothing(app, status):
    """Never a guess when ips cannot answer. This records provenance and makes
    no authorisation decision, so returning None is correct — the gate above it
    already fails closed separately."""
    assert _resolve(app, [(CLINIC_A, ORG_A)], status=status) is None


def test_the_resolver_reads_organisation_guid_from_the_ips_response(app):
    """get_patient_clinic_orgs must keep the organisation, not only the clinic
    guid — the existing get_patient_clinic_guids discards it, which is why the
    value was fetched and thrown away for months (#778)."""
    payload = _clinics((CLINIC_A, ORG_A))

    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return payload

    with app.app_context():
        with patch("app.services.patient_service.requests.get", return_value=_R()):
            pairs, status = patient_service.get_patient_clinic_orgs("pat-1")
    assert status == 200
    assert pairs == [(CLINIC_A, ORG_A)]

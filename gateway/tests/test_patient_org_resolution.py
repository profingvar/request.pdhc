"""#774/#768 — resolve the patient's organisation from ips, or refuse.

#768: one organisation per datapoint, and it is the one the patient was
affiliated with in ips AT REQUEST TIME. ips keeps no assignment history —
`patient_clinic_assignments` has `assigned_at` and no end timestamp — so this
cannot be reconstructed later and must be snapshotted.

## The contract changed on 2026-10-07

This module used to assert that the resolver **records nothing** — returns None
— when it cannot establish one organisation. The operator decided otherwise:

* **no clinic → REFUSE.** #735 requires the organisation on every datapoint, so
  a NULL row is the non-compliant artefact these tickets exist to prevent. It is
  also invisible to every org-scoped reader under Rule 24, which means data
  collected and then unreadable by the people who collected it.
* **several clinics → ALLOW**, resolved by `requesting_org_guid`.

The second one needed a tie-break, and the objection to allowing it was that any
tie-break would be invented. It is not invented here: it reuses a choice the
caller has already been forced to state. A single-org caller has
`requesting_org_guid` auto-filled; a multi-org caller **must** supply it (#226);
and for a non-SU caller the #779 gate has already established that one of the
patient's organisations is among the caller's own. Where several remain and none
is the requesting one — mainly an SU admin, who bypasses that gate — the
resolver still refuses rather than ordering by `assigned_at` or guid.

So "refuses to guess" survives; what changed is that the refusal is now loud
instead of a NULL column.
"""
from unittest.mock import patch

import pytest

from app.services import patient_service
from app.services.patient_service import PatientOrgUnresolved

CLINIC_A = "clinic-aaaa"
ORG_A = "org-aaaa"
CLINIC_B = "clinic-bbbb"
ORG_B = "org-bbbb"
ORG_C = "org-cccc"


def _clinics(*pairs):
    return [{"guid": c, "organisation_guid": o, "name": "c"} for c, o in pairs]


def _resolve(app, clinics, status=200, requesting_org_guid=None):
    with app.app_context():
        with patch.object(patient_service, "get_patient_clinic_orgs",
                          return_value=(clinics, status)):
            return patient_service.resolve_patient_org_guid(
                "pat-1", requesting_org_guid=requesting_org_guid)


def _refusal(app, clinics, status=200, requesting_org_guid=None):
    """Resolve, expecting a refusal, and hand back the exception."""
    with pytest.raises(PatientOrgUnresolved) as ei:
        _resolve(app, clinics, status, requesting_org_guid)
    return ei.value


# ---------------------------------------------------------------------------
# Resolves
# ---------------------------------------------------------------------------

def test_one_clinic_resolves_to_its_organisation(app):
    assert _resolve(app, [(CLINIC_A, ORG_A)]) == ORG_A


def test_the_CLINIC_guid_is_never_returned(app):
    """clinic_guid and organisation_guid are different identifier spaces — 0 of
    ips's 9 clinics have them equal. Returning the clinic guid would put a value
    in the column that no sso organisation matches (#779)."""
    got = _resolve(app, [(CLINIC_A, ORG_A)])
    assert got == ORG_A and got != CLINIC_A


def test_two_clinics_in_the_SAME_organisation_still_resolve(app):
    """Several clinics is not ambiguity if they agree on the organisation, and
    no tie-break is needed to see that."""
    assert _resolve(app, [(CLINIC_A, ORG_A), (CLINIC_B, ORG_A)]) == ORG_A


def test_several_organisations_resolve_to_the_requesting_one(app):
    """The 2026-10-07 decision: ALLOW, resolved by requesting_org_guid."""
    got = _resolve(app, [(CLINIC_A, ORG_A), (CLINIC_B, ORG_B)],
                   requesting_org_guid=ORG_B)
    assert got == ORG_B


def test_the_requesting_org_does_not_override_a_single_affiliation(app):
    """The tie-break applies ONLY to a tie. With one organisation the patient's
    own affiliation wins, even when the requester is someone else — otherwise
    `patient_org_guid` would quietly become a second copy of
    `requesting_org_guid` and the two columns would stop being two facts."""
    assert _resolve(app, [(CLINIC_A, ORG_A)], requesting_org_guid=ORG_B) == ORG_A


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_no_clinic_refuses(app):
    """28 of ips's 150 patients have no assignment. Previously this returned
    None and the ServiceRequest was created anyway."""
    e = _refusal(app, [])
    assert e.code == "patient_org_unassigned"
    assert "Assign the patient to a clinic" in e.message


def test_a_clinic_with_no_organisation_guid_refuses(app):
    """Clinic.organisation_guid is nullable, and #780 found a live clinic
    pointing at an organisation sso had never issued. An unbridged clinic is
    indistinguishable from no clinic for this purpose, and must not be treated
    as a wildcard."""
    e = _refusal(app, [(CLINIC_A, None)])
    assert e.code == "patient_org_unassigned"
    # The clinic is still named, so the operator can go and bridge it.
    assert e.clinics == [CLINIC_A]


def test_several_organisations_with_an_unrelated_requester_refuses(app):
    """The residual case the decision did not cover: several affiliations and
    the requester is none of them. Reachable mainly for an SU admin, who
    bypasses the #779 gate.

    Ordering by `assigned_at` or guid would settle it — and would write an
    invented rule onto every subsequent datapoint for that patient. One error
    now beats a permanent guess.
    """
    e = _refusal(app, [(CLINIC_A, ORG_A), (CLINIC_B, ORG_B)],
                 requesting_org_guid=ORG_C)
    assert e.code == "patient_org_ambiguous"
    assert e.orgs == sorted([ORG_A, ORG_B])


def test_several_organisations_with_no_requester_refuses(app):
    """An SU admin may omit requesting_org_guid entirely."""
    e = _refusal(app, [(CLINIC_A, ORG_A), (CLINIC_B, ORG_B)])
    assert e.code == "patient_org_ambiguous"


def test_an_unknown_patient_refuses_as_not_found(app):
    e = _refusal(app, [], status=404)
    assert e.code == "patient_not_found"


@pytest.mark.parametrize("status", [500, 502, 503])
def test_an_unreachable_ips_refuses_rather_than_writing_no_organisation(app, status):
    """Fail closed. An ips outage is not permission to write a row with no
    organisation on it — which is what returning None used to do."""
    e = _refusal(app, [(CLINIC_A, ORG_A)], status=status)
    assert e.code == "ips_unavailable"


def test_a_refusal_carries_the_facts_for_the_audit_row(app):
    """`as_details()` feeds the audit row, so a refusal is diagnosable without
    re-querying ips — and the two codes mean different operator actions."""
    d = _refusal(app, [(CLINIC_A, ORG_A), (CLINIC_B, ORG_B)]).as_details()
    assert d["reason"] == "patient_org_ambiguous"
    assert d["patient_org_guids"] == sorted([ORG_A, ORG_B])
    assert d["patient_clinic_guids"] == sorted([CLINIC_A, CLINIC_B])


# ---------------------------------------------------------------------------
# The lookup itself
# ---------------------------------------------------------------------------

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

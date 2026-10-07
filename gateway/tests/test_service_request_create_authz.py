"""Tests for the PDL Ch 4 §§ 1-2 patient-org authorisation gate on
POST /ServiceRequest (ticket #225), corrected for #779.

The gate's contract:

- Caller is SU admin → allowed, audited as `admin_bypass`.
- Caller is not SU AND caller's org_ids ∩ the ORGANISATIONS of the patient's
  clinics ≠ ∅ → allowed (no extra audit row beyond the regular create audit).
- Caller is not SU AND no intersection → **403**, audited as
  `denied / patient_org_mismatch`.
- Patient not found in IPS → **404**, audited as `denied / patient_not_found`.
- IPS upstream error → **502** (fail-closed), audited as
  `denied / ips_lookup_failed`.

## Why this module was rewritten (#779)

It used to pass CLINIC guids as `organization_ids` and intersect them against
ips `Clinic.guid`. Both sides got the same identifier space, so the tests
matched and went green — against a gate that could never match in production,
where `Clinic.guid` and `Clinic.organisation_guid` are different values (0 of
ips's 9 clinics had them equal, measured 2026-10-06).

The fixtures below therefore keep **four distinct constants**: `ORG_*` are sso
organisation guids, the space `organization_ids` and `requesting_org_guid` live
in; `CLINIC_*` are ips primary keys, which authorisation must never compare
against. `test_a_clinic_guid_in_caller_orgs_does_not_grant_access` pins that
distinction, and it is the assertion this module previously had backwards.
"""
from unittest.mock import patch

import pytest

from app.models.audit_models import AuditLog


PATIENT = "patient-guid-test-225"
PLANDEF = "plandef-guid-test-225"
USER_GUID = "user-test-225"

# sso ORGANISATION guids — what an access blob carries and what the gate
# compares. Deliberately unlike the clinic guids below.
ORG_A = "org-a-guid-sso"
ORG_B = "org-b-guid-sso"

# ips CLINIC guids — Clinic's own primary key. Present in the ips response the
# gate reads, and never a valid thing to authorise against (#779/#777).
CLINIC_A = "clinic-a-guid-ips"
CLINIC_B = "clinic-b-guid-ips"


def _blob(*, is_su=False, org_ids=None):
    """Build a synthetic SSO access blob.

    `organization_ids` holds ORGANISATION guids. The gate prefers
    `affiliations[].care_unit_guid` and falls back to this, so these tests
    exercise the fallback path.
    """
    return {
        "user_guid": USER_GUID,
        "email": "test@example.com",
        "user_type": "professional",
        "is_su_admin": is_su,
        "organization_ids": list(org_ids or []),
        "organization_names": ["Test Clinic"],
        "display_name": "Test User",
        "effective_phases": ["active"],
    }


@pytest.fixture(autouse=True)
def _clean_audit_and_pin_auth(db_session, app):
    """Two pieces of per-test hygiene:

    1. Audit-row cleanup — the session-scoped DB persists across tests
       so old audit rows would otherwise pollute the count.
    2. AUTH_DISABLED pin — sibling test modules (test_sandbox_dispatch,
       test_scope_enforcement, test_webhook_dispatcher) flip
       AUTH_DISABLED at import time; restore it for our tests so the
       requires_auth decorator passes through to the blob we
       monkeypatch.
    """
    prev_auth = app.config.get('AUTH_DISABLED')
    app.config['AUTH_DISABLED'] = True
    db_session.query(AuditLog).delete()
    db_session.commit()
    yield
    app.config['AUTH_DISABLED'] = prev_auth


@pytest.fixture(autouse=True)
def _no_real_ips_calls():
    """Fail loudly instead of reaching ips.pdhc over the network.

    When #779 moved the gate from `get_patient_clinic_guids` to
    `get_patient_clinic_orgs`, every test still patching the old name left the
    REAL lookup in place — and it called `https://ips.pdhc.se` from the unit
    suite, which answered 401. The tests failed, so nothing silently passed,
    but a test run must never depend on a production service being reachable.

    Patching the module's `requests.get` turns any such gap into an immediate
    RuntimeError naming the URL, rather than a 502 that looks like an
    unrelated upstream problem.
    """
    def _boom(url, *a, **kw):
        raise RuntimeError(
            f"a test tried to reach ips over the network: {url} — patch "
            f"patient_service.get_patient_clinic_orgs instead")

    with patch("app.services.patient_service.requests.get", side_effect=_boom):
        yield


@pytest.fixture
def stub_service_create():
    """Replace service_request_service.create_service_request so tests
    don't actually persist rows / hit plan.pdhc."""
    with patch(
        "app.api.service_requests.service_request_service.create_service_request",
        return_value=({"guid": "sr-stub-guid", "status": "draft"}, 201),
    ) as m:
        yield m


def _audit_rows(action):
    return AuditLog.query.filter_by(action=action).all()


def _patch_clinics(return_value):
    """Patch the ips lookup the gate actually calls (#779)."""
    return patch("app.api.service_requests.patient_service."
                 "get_patient_clinic_orgs", return_value=return_value)


def _patch_clinics_unused():
    """Patch it as a bare mock, for paths that must not reach ips at all."""
    return patch("app.api.service_requests.patient_service."
                 "get_patient_clinic_orgs")


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_su_admin_can_create_for_any_patient(client, db_session, stub_service_create):
    """SU admin bypass — call goes through even with empty
    organization_ids and no matching clinic. Audited."""
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=True, org_ids=[])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics_unused() as ips_mock:
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 201
    # SU path skips the IPS lookup entirely.
    ips_mock.assert_not_called()
    stub_service_create.assert_called_once()
    # Audit row for the admin bypass.
    rows = _audit_rows("service_request.create.admin_bypass")
    assert len(rows) == 1
    assert rows[0].data_subject_guid == PATIENT
    assert rows[0].user_guid == USER_GUID
    assert rows[0].details["reason"] == "caller_is_su_admin"


def test_non_admin_with_matching_org_can_create(client, db_session, stub_service_create):
    """A caller in ORG_A may act for a patient whose clinic belongs to ORG_A.

    Note the shape: the caller holds an ORGANISATION, the patient holds a
    CLINIC, and they match through the clinic's `organisation_guid`. Under the
    pre-#779 gate this case was a 403 — which is to say every real caller was
    denied.
    """
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_A])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([(CLINIC_A, ORG_A), (CLINIC_B, ORG_B)], 200)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 201
    stub_service_create.assert_called_once()
    # No denied/admin_bypass rows — the regular create audit (if any) is
    # written by the underlying service, which we stubbed.
    assert _audit_rows("service_request.create.denied") == []
    assert _audit_rows("service_request.create.admin_bypass") == []


# ---------------------------------------------------------------------------
# Deny paths
# ---------------------------------------------------------------------------

def test_a_clinic_guid_in_caller_orgs_does_not_grant_access(
        client, db_session, stub_service_create):
    """THE #779 REGRESSION TEST — and the assertion this module had backwards.

    The caller's `organization_ids` contains a value equal to the patient's
    ips `Clinic.guid`. The old gate intersected exactly those two and returned
    **201**; that is what made the bug invisible for the life of the ticket.

    Authorisation must compare organisations, so a clinic primary key matching
    is not a grant. If this test ever goes green on a 201 again, the gate has
    been reverted to comparing identifier spaces that production never equates.
    """
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[CLINIC_A])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([(CLINIC_A, ORG_A)], 200)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 403
    stub_service_create.assert_not_called()
    rows = _audit_rows("service_request.create.denied")
    assert len(rows) == 1
    assert rows[0].details["reason"] == "patient_org_mismatch"
    # The audit shows both spaces, so the operator can see the confusion.
    assert rows[0].details["caller_org_ids"] == [CLINIC_A]
    assert rows[0].details["patient_org_guids"] == [ORG_A]
    assert rows[0].details["patient_clinic_guids"] == [CLINIC_A]


def test_clinic_without_an_organisation_denies(
        client, db_session, stub_service_create):
    """`Clinic.organisation_guid` is nullable, and NULL must DENY.

    Treating it as a wildcard would turn an unfinished ips record into
    platform-wide access. #780 found a live clinic whose organisation sso had
    never issued, so an unbridged clinic is not hypothetical.

    The denial is also distinguishable in the audit: `patient_org_guids` is
    empty while `clinics_without_organisation` names the clinic, which is what
    tells the operator to bridge a record rather than to re-check an
    affiliation.
    """
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_A])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([(CLINIC_A, None)], 200)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 403
    stub_service_create.assert_not_called()
    rows = _audit_rows("service_request.create.denied")
    assert len(rows) == 1
    assert rows[0].details["reason"] == "patient_org_mismatch"
    assert rows[0].details["patient_org_guids"] == []
    assert rows[0].details["clinics_without_organisation"] == [CLINIC_A]


def test_non_admin_without_matching_org_is_403(client, db_session, stub_service_create):
    """A caller in ORG_B cannot create an SR for a patient whose clinic
    belongs to ORG_A."""
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_B])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([(CLINIC_A, ORG_A)], 200)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["code"] == "forbidden"
    assert "PDL" in body["message"]
    stub_service_create.assert_not_called()
    rows = _audit_rows("service_request.create.denied")
    assert len(rows) == 1
    assert rows[0].data_subject_guid == PATIENT
    assert rows[0].user_guid == USER_GUID
    assert rows[0].details["reason"] == "patient_org_mismatch"
    assert rows[0].details["caller_org_ids"] == [ORG_B]
    assert rows[0].details["patient_org_guids"] == [ORG_A]
    assert rows[0].details["patient_clinic_guids"] == [CLINIC_A]
    assert rows[0].details["clinics_without_organisation"] == []


def test_non_admin_with_no_orgs_is_403(client, db_session, stub_service_create):
    """A user with empty organization_ids is rejected for any non-empty
    patient clinic set."""
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([(CLINIC_A, ORG_A)], 200)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 403
    stub_service_create.assert_not_called()


def test_patient_with_no_clinic_assignment_is_403(
        client, db_session, stub_service_create):
    """An empty clinic list is a valid 200 from ips, and it must deny.

    28 of ips's 150 patients have no assignment today, so this is the common
    case, not an edge one — and an empty intersection must read as "no
    affiliation established" rather than "no restriction".
    """
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_A])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([], 200)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 403
    stub_service_create.assert_not_called()
    rows = _audit_rows("service_request.create.denied")
    assert len(rows) == 1
    assert rows[0].details["reason"] == "patient_org_mismatch"
    assert rows[0].details["patient_org_guids"] == []


def test_non_admin_patient_not_found_in_ips_is_404(client, db_session, stub_service_create):
    """When ips.pdhc returns 404 for the patient, request.pdhc surfaces 404
    and audits the denial."""
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_A])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([], 404)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 404
    stub_service_create.assert_not_called()
    rows = _audit_rows("service_request.create.denied")
    assert len(rows) == 1
    assert rows[0].details["reason"] == "patient_not_found"


def test_non_admin_ips_upstream_error_fails_closed(client, db_session, stub_service_create):
    """When ips.pdhc is unreachable / returns 5xx, request.pdhc MUST NOT
    create the SR — failing open would silently bypass the PDL gate."""
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_A])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([], 502)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["code"] == "upstream_error"
    stub_service_create.assert_not_called()
    rows = _audit_rows("service_request.create.denied")
    assert len(rows) == 1
    assert rows[0].details["reason"] == "ips_lookup_failed"
    assert rows[0].details["ips_status"] == 502


# ---------------------------------------------------------------------------
# Sanity: still rejects bad input
# ---------------------------------------------------------------------------

def test_missing_patient_guid_still_400(client, db_session, stub_service_create):
    """The new auth gate must not regress existing input validation."""
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=True)), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 400
    stub_service_create.assert_not_called()


# ---------------------------------------------------------------------------
# Explicit requesting-org choice (ticket #226 — Lag 2022:913)
# ---------------------------------------------------------------------------

def test_multi_org_caller_without_pick_is_400(client, db_session, stub_service_create):
    """A user with > 1 affiliation MUST specify requesting_org_guid;
    silent first-pick was the antipattern this ticket removed."""
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_A, ORG_B])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics_unused() as ips_mock:
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == "bad_request"
    assert "requesting_org_guid" in body["message"]
    # Patient gate never ran — auth on the choice came first.
    ips_mock.assert_not_called()
    stub_service_create.assert_not_called()
    rows = _audit_rows("service_request.create.denied")
    assert len(rows) == 1
    assert rows[0].details["reason"] == "requesting_org_required"


def test_multi_org_caller_with_explicit_pick_lands_in_create(
        client, db_session, stub_service_create):
    """A multi-org caller's explicit pick flows through to
    create_service_request as org_guid + audit captures it.

    The pick is an ORGANISATION, drawn from the caller's own affiliations —
    the same space the patient gate compares.
    """
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_A, ORG_B])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([(CLINIC_A, ORG_A)], 200)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={
                "patient_guid": PATIENT,
                "plan_definition_guid": PLANDEF,
                "requesting_org_guid": ORG_B,
            },
        )
    assert resp.status_code == 201
    # The chosen org made it into the underlying create call.
    kwargs = stub_service_create.call_args.kwargs
    assert kwargs["org_guid"] == ORG_B
    # And it's recorded in the requested-audit row.
    rows = _audit_rows("service_request.create.requested")
    assert len(rows) == 1
    assert rows[0].details["requesting_org_guid"] == ORG_B
    assert rows[0].details["org_choice_mode"] == "caller_specified"
    assert rows[0].details["caller_org_ids_count"] == 2


def test_explicit_pick_not_in_caller_orgs_is_403(
        client, db_session, stub_service_create):
    """The chosen org must be one of the caller's affiliations."""
    ROGUE_ORG = "org-rogue-guid-sso"
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_A, ORG_B])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics_unused() as ips_mock:
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={
                "patient_guid": PATIENT,
                "plan_definition_guid": PLANDEF,
                "requesting_org_guid": ROGUE_ORG,
            },
        )
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["code"] == "forbidden"
    # IPS lookup short-circuited; we deny on the choice itself.
    ips_mock.assert_not_called()
    stub_service_create.assert_not_called()
    rows = _audit_rows("service_request.create.denied")
    assert len(rows) == 1
    assert rows[0].details["reason"] == "requesting_org_not_in_caller_orgs"
    assert rows[0].details["requesting_org_guid"] == ROGUE_ORG


def test_single_org_caller_autofills(client, db_session, stub_service_create):
    """The pre-#226 ergonomics for single-org callers are preserved —
    no need to specify the pick, server fills it in."""
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=False, org_ids=[ORG_A])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics(([(CLINIC_A, ORG_A)], 200)):
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={"patient_guid": PATIENT, "plan_definition_guid": PLANDEF},
        )
    assert resp.status_code == 201
    kwargs = stub_service_create.call_args.kwargs
    assert kwargs["org_guid"] == ORG_A
    rows = _audit_rows("service_request.create.requested")
    assert len(rows) == 1
    assert rows[0].details["requesting_org_guid"] == ORG_A
    assert rows[0].details["org_choice_mode"] == "auto_single_org"


def test_su_admin_can_explicitly_choose_any_org(
        client, db_session, stub_service_create):
    """SU admin's organization_ids is empty by convention, but they may
    legitimately act on behalf of any org. The chosen org must flow
    through and the audit must capture it."""
    SU_CHOSEN_ORG = "org-su-chosen-guid-sso"
    with patch("app.api.service_requests.get_current_access_blob",
               return_value=_blob(is_su=True, org_ids=[])), \
         patch("app.api.service_requests.get_current_user_guid",
               return_value=USER_GUID), \
         _patch_clinics_unused() as ips_mock:
        resp = client.post(
            "/api/v1/ServiceRequest",
            json={
                "patient_guid": PATIENT,
                "plan_definition_guid": PLANDEF,
                "requesting_org_guid": SU_CHOSEN_ORG,
            },
        )
    assert resp.status_code == 201
    # SU path: IPS lookup is skipped.
    ips_mock.assert_not_called()
    kwargs = stub_service_create.call_args.kwargs
    assert kwargs["org_guid"] == SU_CHOSEN_ORG
    # Bypass row records the chosen org.
    bypass_rows = _audit_rows("service_request.create.admin_bypass")
    assert len(bypass_rows) == 1
    assert bypass_rows[0].details["requesting_org_guid"] == SU_CHOSEN_ORG
    assert bypass_rows[0].details["org_choice_mode"] == "caller_specified"

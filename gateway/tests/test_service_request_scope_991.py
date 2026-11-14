"""#991 — every route keyed by a ServiceRequest guid reaches the patient only
through the caller's organisation (patient_access.py, shared with #981), and
the list no longer FAILS OPEN for a caller with no organisation.

REAL non-SU blobs throughout; each assertion was shown to fail with the gate
removed when written.
"""
from unittest.mock import patch

import pytest

from app.models.audit_models import AuditLog
from app.models.service_request_models import ServiceRequest

PATIENT = "patient-991"
ORG_A, ORG_B = "org-a-sso", "org-b-sso"
CLINIC_A = "clinic-a-ips"


def _blob(*, su=False, orgs=()):
    # The caller's care units are AFFILIATIONS. This helper used to set only
    # the legacy organization_ids, so every test here ran through the
    # fallback that was removed 2026-11-14; the scope is the same units.
    return {"user_guid": "u-991", "email": "t@example.com", "user_type": "professional",
            "is_su_admin": su, "affiliations": [{"care_unit_guid": o} for o in orgs],
            "display_name": "T", "effective_phases": ["active"]}


@pytest.fixture(autouse=True)
def _hygiene(db_session, app):
    prev = app.config.get("AUTH_DISABLED")
    app.config["AUTH_DISABLED"] = True
    db_session.query(AuditLog).delete()
    db_session.commit()
    yield
    app.config["AUTH_DISABLED"] = prev


@pytest.fixture(autouse=True)
def _no_network():
    def boom(url, *a, **k):
        raise RuntimeError(f"a test reached the network: {url}")
    with patch("app.services.patient_service.requests.get", side_effect=boom), \
         patch("app.services.ips_client.is_sr_visible", return_value=True):
        yield


@pytest.fixture
def sr(db_session):
    row = ServiceRequest(patient_guid=PATIENT, plan_definition_guid="pd-1",
                         requester_user_guid="u-x", requester_org_guid=ORG_A, status="draft")
    db_session.add(row)
    db_session.commit()
    yield row.guid
    db_session.query(ServiceRequest).filter_by(guid=row.guid).delete()
    db_session.commit()


def _call(client, method, url, blob, clinics=((CLINIC_A, ORG_A),), ips_status=200, **kw):
    with patch("app.api.service_requests.get_current_access_blob", return_value=blob), \
         patch("app.services.patient_service.get_patient_clinic_orgs",
               return_value=(list(clinics), ips_status)):
        return getattr(client, method)(url, **kw)


GUID_ROUTES = [
    ("get", "", "read"), ("put", "/snapshot", "snapshot"), ("post", "/finalize", "finalize"),
    ("post", "/archive", "archive"), ("post", "/revoke", "revoke"), ("get", "/matches", "matches"),
    ("post", "/match", "match"), ("post", "/push", "push"), ("post", "/push/m-1", "push"),
    ("get", "/receipts", "receipts"), ("get", "/forms", "forms"), ("post", "/forms", "forms.add"),
]


@pytest.mark.parametrize("method,suffix,verb", GUID_ROUTES)
def test_every_guid_route_REFUSES_another_organisation(client, sr, method, suffix, verb):
    kw = {"json": {}} if method in ("post", "put") else {}
    r = _call(client, method, f"/api/v1/ServiceRequest/{sr}{suffix}", _blob(orgs=[ORG_B]), **kw)
    assert r.status_code == 403, (verb, r.status_code, r.get_json())
    rows = AuditLog.query.filter_by(action=f"service_request.{verb}.denied").all()
    assert len(rows) == 1 and rows[0].details["reason"] == "patient_org_mismatch"


@pytest.mark.parametrize("suffix", ["", "/matches", "/receipts", "/forms"])
def test_the_patients_organisation_READS(client, sr, suffix):
    r = _call(client, "get", f"/api/v1/ServiceRequest/{sr}{suffix}", _blob(orgs=[ORG_A]))
    assert r.status_code == 200, (suffix, r.get_json())


def test_a_CLINIC_guid_does_not_grant_access(client, sr):
    assert _call(client, "get", f"/api/v1/ServiceRequest/{sr}", _blob(orgs=[CLINIC_A])).status_code == 403


def test_ips_down_FAILS_CLOSED(client, sr):
    assert _call(client, "get", f"/api/v1/ServiceRequest/{sr}", _blob(orgs=[ORG_A]),
                 clinics=(), ips_status=503).status_code == 502


def test_an_SU_admin_reads(client, sr):
    assert _call(client, "get", f"/api/v1/ServiceRequest/{sr}", _blob(su=True)).status_code == 200


def test_an_unknown_guid_is_still_404(client):
    assert _call(client, "get", "/api/v1/ServiceRequest/does-not-exist", _blob(orgs=[ORG_A])).status_code == 404


def test_the_list_no_longer_FAILS_OPEN_for_a_caller_with_no_organisation(client, sr):
    r = _call(client, "get", "/api/v1/ServiceRequest", _blob(orgs=[]))
    assert r.status_code == 403
    assert AuditLog.query.filter_by(action="service_request.list.denied").first().details["reason"] == \
        "caller_has_no_organisation"


def test_the_list_still_works_for_an_organisation(client, sr):
    r = _call(client, "get", "/api/v1/ServiceRequest", _blob(orgs=[ORG_A]))
    assert r.status_code == 200
    assert any(i["guid"] == sr for i in r.get_json()["items"])


def test_legacy_organization_ids_ALONE_reach_nothing(client, sr):
    """2026-11-14: the organization_ids fallback is removed. A blob with an
    old MEMBERSHIP of the patient's organisation but no affiliation used to
    read this ServiceRequest and list it; now it gets neither."""
    legacy = {"user_guid": "u-991", "email": "t@example.com", "user_type": "professional",
              "is_su_admin": False, "organization_ids": [ORG_A], "display_name": "T",
              "effective_phases": ["active"]}
    assert _call(client, "get", f"/api/v1/ServiceRequest/{sr}", legacy).status_code == 403
    assert _call(client, "get", "/api/v1/ServiceRequest", legacy).status_code == 403

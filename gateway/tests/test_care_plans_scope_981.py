"""#981 — the CarePlan routes reach a patient only through the caller's
organisation, by the SAME rule as POST /ServiceRequest (patient_access.py).

Every test drives a REAL non-SU blob. CLAUDE.md §11 records a 990-test suite
that passed identically before and after a security gate existed, because
every test ran as an admin; these must FAIL with the gate removed (mutation-
checked when written).
"""
from unittest.mock import patch

import pytest

from app import db
from app.models.audit_models import AuditLog
from app.models.care_plan_models import CarePlan

PATIENT = "patient-981"
ORG_A, ORG_B = "org-a-sso", "org-b-sso"
CLINIC_A = "clinic-a-ips"          # ips primary key: never an authorisation value (#779)


def _blob(*, su=False, orgs=()):
    return {"user_guid": "u-981", "email": "t@example.com", "user_type": "professional",
            "is_su_admin": su, "organization_ids": list(orgs), "display_name": "T",
            "effective_phases": ["active"]}


@pytest.fixture(autouse=True)
def _hygiene(db_session, app):
    prev = app.config.get("AUTH_DISABLED")
    app.config["AUTH_DISABLED"] = True
    db_session.query(AuditLog).delete()
    db_session.query(CarePlan).delete()
    db_session.commit()
    yield
    app.config["AUTH_DISABLED"] = prev


@pytest.fixture(autouse=True)
def _no_network():
    def boom(url, *a, **k):
        raise RuntimeError(f"a test reached the network: {url}")
    with patch("app.services.patient_service.requests.get", side_effect=boom):
        yield


@pytest.fixture
def cp(db_session):
    c = CarePlan(patient_guid=PATIENT, plan_definition_guid="pd-1", status="active",
                 intent="plan", title="T", plan_definition_snapshot={"activities": []},
                 goals=[])
    db_session.add(c)
    db_session.commit()
    return c.guid


def _as(blob, clinics=((CLINIC_A, ORG_A),), ips_status=200):
    return (patch("app.api.care_plans.get_current_access_blob", return_value=blob),
            patch("app.services.patient_service.get_patient_clinic_orgs",
                  return_value=(list(clinics), ips_status)))


def _call(client, method, url, blob, **kw):
    a, b = _as(blob, **{k: kw.pop(k) for k in ("clinics", "ips_status") if k in kw})
    with a, b:
        return getattr(client, method)(url, **kw)


def _denied(action):
    return AuditLog.query.filter_by(action=action).all()


ROUTES = [("get", "/api/v1/careplans/{g}", "read"),
          ("get", "/api/v1/careplans/{g}/context", "context"),
          ("put", "/api/v1/careplans/{g}", "update"),
          ("get", "/api/v1/careplans?patient_guid=" + PATIENT, "list")]


@pytest.mark.parametrize("method,url,verb", ROUTES)
def test_the_patients_organisation_is_ADMITTED(client, cp, method, url, verb):
    kw = {"json": {"title": "x"}} if method == "put" else {}
    r = _call(client, method, url.format(g=cp), _blob(orgs=[ORG_A]), **kw)
    assert r.status_code == 200, (verb, r.get_json())


@pytest.mark.parametrize("method,url,verb", ROUTES)
def test_another_organisation_is_REFUSED_and_audited(client, cp, method, url, verb):
    kw = {"json": {"title": "x"}} if method == "put" else {}
    r = _call(client, method, url.format(g=cp), _blob(orgs=[ORG_B]), **kw)
    assert r.status_code == 403, (verb, r.get_json())
    rows = _denied(f"care_plan.{verb}.denied")
    assert len(rows) == 1 and rows[0].details["reason"] == "patient_org_mismatch"


def test_a_refused_update_changes_NOTHING(client, cp):
    _call(client, "put", f"/api/v1/careplans/{cp}", _blob(orgs=[ORG_B]),
          json={"goals": [{"concept_guid": "c", "target_type": "range"}]})
    assert db.session.get(CarePlan, CarePlan.query.filter_by(guid=cp).first().id).goals == []


def test_a_caller_with_no_organisation_is_refused(client, cp):
    assert _call(client, "get", f"/api/v1/careplans/{cp}", _blob()).status_code == 403


def test_a_CLINIC_guid_in_the_callers_orgs_does_not_grant_access(client, cp):
    """#779: clinic guid and organisation guid are different spaces."""
    assert _call(client, "get", f"/api/v1/careplans/{cp}", _blob(orgs=[CLINIC_A])).status_code == 403


def test_a_clinic_without_an_organisation_denies(client, cp):
    r = _call(client, "get", f"/api/v1/careplans/{cp}", _blob(orgs=[ORG_A]),
              clinics=((CLINIC_A, None),))
    assert r.status_code == 403


def test_ips_down_FAILS_CLOSED(client, cp):
    r = _call(client, "get", f"/api/v1/careplans/{cp}", _blob(orgs=[ORG_A]), clinics=(), ips_status=503)
    assert r.status_code == 502


def test_a_patient_ips_does_not_know_is_404(client, cp):
    r = _call(client, "get", f"/api/v1/careplans/{cp}", _blob(orgs=[ORG_A]), clinics=(), ips_status=404)
    assert r.status_code == 404


def test_an_UNFILTERED_list_is_refused_for_a_non_admin(client, cp):
    r = _call(client, "get", "/api/v1/careplans", _blob(orgs=[ORG_A]))
    assert r.status_code == 400
    assert _denied("care_plan.list.denied")[0].details["reason"] == "patient_guid_required"


def test_an_SU_admin_may_list_unfiltered(client, cp):
    r = _call(client, "get", "/api/v1/careplans", _blob(su=True))
    assert r.status_code == 200 and r.get_json()["total"] == 1


def test_an_SU_update_is_audited_as_a_BYPASS(client, cp):
    r = _call(client, "put", f"/api/v1/careplans/{cp}", _blob(su=True), json={"title": "y"})
    assert r.status_code == 200
    assert len(_denied("care_plan.update.admin_bypass")) == 1


def test_create_for_another_organisations_patient_is_refused(client):
    with patch("app.api.care_plans.plan_definition_service.get_plan_definition",
               return_value=({"guid": "pd-1", "activities": []}, 200)):
        r = _call(client, "post", "/api/v1/careplans", _blob(orgs=[ORG_B]),
                  json={"patient_guid": PATIENT, "plan_definition_guid": "pd-1"})
    assert r.status_code == 403
    assert CarePlan.query.count() == 0


def test_a_successful_read_is_AUDITED(client, cp):
    _call(client, "get", f"/api/v1/careplans/{cp}", _blob(orgs=[ORG_A]))
    assert AuditLog.query.filter_by(action="care_plan.read").count() == 1

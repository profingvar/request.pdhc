"""#1045 loggkontroll: one patient's access log from request.pdhc.

    GET /api/v1/patients/<guid>/access-log

AUTH ON (AUTH_DISABLED=False) through the real `requires_auth`; the person
arrives on `X-API-Key` (the operator's own SSO token, dashboard's door), and
only the sso validation (`validate_api_key`) and the eps clinic lookup
(`get_patient_clinic_orgs`) are replaced. Also covers the two fixes the log
needed: `@audit_read` now writes `data_subject_guid`, and an `X-API-Key`
caller is the person in `get_current_access_blob` (before: None -> an
affiliated professional was refused, and audited as user NULL).
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models.audit_models import AuditLog
from app.models.care_plan_models import CarePlan
from app.models.service_request_models import ServiceRequest

PATIENT = "aaaa1045-0000-4000-8000-00000000000a"
OTHER = "bbbb1045-0000-4000-8000-00000000000b"
UNIT_A, UNIT_B = "unit-a-1045", "unit-b-1045"


def _blob(kind):
    b = {"user_guid": f"user-{kind}", "email": f"{kind}@example.test",
         "user_type": "professional", "is_su_admin": False,
         "affiliations": [], "effective_phases": ["active"]}
    if kind == "pro_a":
        b["affiliations"] = [{"care_unit_guid": UNIT_A, "role": "nurse"}]
    elif kind == "pro_b":
        b["affiliations"] = [{"care_unit_guid": UNIT_B, "role": "nurse"}]
    elif kind == "su":
        b["is_su_admin"] = True
    elif kind == "service":
        b["user_type"] = "service"
    elif kind == "patient":
        b["user_type"] = "patient"
        b["affiliations"] = [{"care_unit_guid": UNIT_A}]
    return b


def H(kind):
    return {"X-API-Key": f"tok-{kind}"}


@pytest.fixture
def api(client, app, db_session):
    db_session.query(AuditLog).delete()
    db_session.query(CarePlan).delete()
    db_session.query(ServiceRequest).delete()
    db_session.commit()
    app.config["AUTH_DISABLED"] = False

    def validate(tok):
        kind = tok[len("tok-"):]
        return _blob(kind) if kind in ("pro_a", "pro_b", "su", "service", "patient") else None

    def clinics(patient_guid):
        return {PATIENT: ([("clinic-a", UNIT_A)], 200),
                OTHER: ([("clinic-b", UNIT_B)], 200)}.get(patient_guid, ([], 404))

    with patch("app.middleware.auth_middleware.validate_api_key", side_effect=validate), \
            patch("app.services.patient_service.get_patient_clinic_orgs", side_effect=clinics):
        yield client


def L(g=PATIENT, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return f"/api/v1/patients/{g}/access-log" + (f"?{qs}" if qs else "")


def _rows(action, subject=PATIENT):
    db.session.expire_all()
    return AuditLog.query.filter_by(action=action, data_subject_guid=subject).all()


@pytest.fixture
def history(db_session):
    sr = ServiceRequest(patient_guid=PATIENT, plan_definition_guid="pd-1",
                        requester_user_guid="u-req", requester_org_guid=UNIT_A)
    cp = CarePlan(patient_guid=PATIENT, plan_definition_guid="pd-1", status="active",
                  intent="plan", title="T", plan_definition_snapshot={"activities": []},
                  goals=[])
    db_session.add_all([sr, cp])
    db_session.commit()
    t0 = datetime(2026, 11, 1, 9, 0)
    db_session.add_all([
        # pre-#1045 shape: a read with NO data_subject_guid, tied by the order
        AuditLog(user_guid="u-old", action="service_request.read",
                 resource_type="ServiceRequest", resource_guid=sr.guid, created_at=t0),
        AuditLog(user_guid="u-old", action="care_plan.update.admin_bypass",
                 resource_type="CarePlan", resource_guid=cp.guid,
                 details={"reason": "caller_is_su_admin", "secret": "NOT OUT"},
                 created_at=t0 + timedelta(days=1)),
        AuditLog(user_guid="u-x", action="care_plan.read.denied", resource_type="CarePlan",
                 data_subject_guid=PATIENT, created_at=t0 + timedelta(days=2),
                 details={"reason": "patient_org_mismatch", "caller_org_ids": [UNIT_B]}),
        AuditLog(user_guid="u-y", action="service_request.read",
                 data_subject_guid=OTHER, created_at=t0),
    ])
    db_session.commit()
    return {"sr": sr.guid, "cp": cp.guid}


def test_affiliated_professional_reads_the_patients_log(api, history):
    r = api.get(L(), headers=H("pro_a"))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["service"] == "request.pdhc"
    actions = [i["action"] for i in body["items"]]
    assert actions == ["service_request.read", "care_plan.update.admin_bypass",
                       "care_plan.read.denied"]
    bypass, denied = body["items"][1], body["items"][2]
    assert bypass["basis"] == "su_admin" and "NOT OUT" not in r.get_data(as_text=True)
    assert denied["outcome"] == "denied" and denied["actor_units"] == [UNIT_B]


def test_the_read_is_logged_with_the_person(api, history):
    api.get(L(), headers=H("pro_a"))
    rows = _rows("access_log.read")
    assert len(rows) == 1 and rows[0].user_guid == "user-pro_a"


def test_other_unit_is_refused_and_logged(api, history):
    r = api.get(L(), headers=H("pro_b"))
    assert r.status_code == 403
    rows = _rows("access_log.read.denied")
    assert len(rows) == 1 and rows[0].details["reason"] == "patient_org_mismatch"
    assert _rows("access_log.read") == []


def test_su_reads_and_unknown_patient_is_404(api, history):
    assert api.get(L(), headers=H("su")).status_code == 200
    assert api.get(L("cccc1045-0000-4000-8000-00000000000c"), headers=H("su")).status_code == 200
    assert api.get(L("cccc1045-0000-4000-8000-00000000000c"),
                   headers=H("pro_a")).status_code == 404


def test_eps_unreachable_fails_closed(api, history):
    with patch("app.services.patient_service.get_patient_clinic_orgs",
               return_value=([], 503)):
        r = api.get(L(), headers=H("pro_a"))
    assert r.status_code == 502


def test_a_service_blob_a_patient_and_a_provider_token_are_refused(api, history):
    r = api.get(L(), headers=H("service"))
    assert r.status_code == 403 and r.get_json()["code"] == "person_required"
    r = api.get(L(), headers=H("patient"))
    assert r.status_code == 403 and r.get_json()["code"] == "not_professional"
    pat = SimpleNamespace(guid="pat-1", provider_org_guid="prov", contract_guid="c",
                          delivery_mode="pull", scopes=["read"])
    with patch("app.services.pat_service.validate_pat", return_value=pat):
        r = api.get(L(), headers={"X-Provider-Token": "x"})
    assert r.status_code == 403 and r.get_json()["code"] == "person_required"
    assert api.get(L(), headers=H("nobody")).status_code == 401
    assert api.get(L()).status_code == 401


def test_range_and_limit(api, history):
    r = api.get(L(**{"from": "2026-11-02T00:00:00Z"}), headers=H("su"))
    assert [i["action"] for i in r.get_json()["items"]][:2] == [
        "care_plan.update.admin_bypass", "care_plan.read.denied"]
    r = api.get(L(to="2026-11-02T00:00:00Z"), headers=H("su"))
    assert [i["action"] for i in r.get_json()["items"]] == ["service_request.read"]
    r = api.get(L(limit=1), headers=H("su"))
    assert len(r.get_json()["items"]) == 1 and r.get_json()["truncated"] is True
    assert api.get(L(to="igår"), headers=H("su")).status_code == 400


# ---- the two fixes the log needed ----------------------------------------

def test_dashboards_door_reads_a_careplan_as_the_professional(api, history):
    """Before #1045 this answered 403: the gate saw no blob on X-API-Key."""
    r = api.get(f"/api/v1/careplans?patient_guid={PATIENT}", headers=H("pro_a"))
    assert r.status_code == 200, r.get_json()
    assert api.get(f"/api/v1/careplans?patient_guid={PATIENT}",
                   headers=H("pro_b")).status_code == 403


def test_audit_read_records_the_patient_and_the_person(api, history):
    api.get(f"/api/v1/careplans/{history['cp']}", headers=H("pro_a"))
    rows = _rows("care_plan.read")
    assert len(rows) == 1 and rows[0].user_guid == "user-pro_a"
    api.get(f"/api/v1/careplans?patient_guid={PATIENT}", headers=H("pro_a"))
    assert len(_rows("care_plan.list")) == 1

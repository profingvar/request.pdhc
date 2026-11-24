"""#1059 (record.pdhc stage 6b): request.pdhc's patient extract.

    GET /api/v1/patient-extract/<patient guid>

AUTH ON through the real `requires_auth`, the person on `X-API-Key` (as
#1045's loggkontroll); only sso validation and the eps clinic lookup are
replaced. Counts are compared with direct database counts (contract).
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models.audit_models import AuditLog
from app.models.care_plan_models import CarePlan
from app.models.history_models import CarePlanHistory, ServiceRequestHistory
from app.models.security_models import DataExchangeGrant
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch, ServiceRequestReceipt)
from app.services import versioning
from app.api.patient_extract import extract_blob

PATIENT = "aaaa1059-0000-4000-8000-00000000000a"
OTHER = "bbbb1059-0000-4000-8000-00000000000b"
UNKNOWN = "cccc1059-0000-4000-8000-00000000000c"
UNIT_A, UNIT_B = "unit-a-1059", "unit-b-1059"
#: Tolvan Tolvansson, Skatteverket's test personnummer
TOLVAN = "19121212-1212"
RECEIPT_TOKEN = "receipt-secret-1059"
GRANT_TOKEN = "grant-secret-1059"


def _blob(kind):
    b = {"user_guid": f"user-{kind}", "user_type": "professional", "is_su_admin": False,
         "affiliations": [], "effective_phases": ["active"]}
    roles = {"doctor_a": (UNIT_A, "doctor"), "nurse_a": (UNIT_A, "nurse"),
             "other_care_a": (UNIT_A, "other_care"), "doctor_b": (UNIT_B, "doctor")}
    if kind in roles:
        unit, role = roles[kind]
        b["affiliations"] = [{"care_unit_guid": unit, "role": role}]
    elif kind == "su":
        b["is_su_admin"] = True
    elif kind == "service":
        b["user_type"] = "service"
    elif kind == "patient":
        b["user_type"] = "patient"
        b["affiliations"] = [{"care_unit_guid": UNIT_A, "role": "doctor"}]
    return b


KINDS = ("doctor_a", "nurse_a", "other_care_a", "doctor_b", "su", "service", "patient")


def H(kind):
    return {"X-API-Key": f"tok-{kind}"}


def URL(g=PATIENT):
    return f"/api/v1/patient-extract/{g}"


@pytest.fixture
def api(client, app):
    app.config["AUTH_DISABLED"] = False

    def validate(tok):
        kind = tok[len("tok-"):]
        return _blob(kind) if kind in KINDS else None

    def clinics(g):
        return {PATIENT: ([("clinic-a", UNIT_A)], 200),
                OTHER: ([("clinic-b", UNIT_B)], 200)}.get(g, ([], 404))

    with patch("app.middleware.auth_middleware.validate_api_key", side_effect=validate), \
            patch("app.services.patient_service.get_patient_clinic_orgs", side_effect=clinics):
        yield client


@pytest.fixture
def data(db_session):
    """Two orders (one sent, noted and archived; one pre-history), a care plan
    changed once, a dispatch with a delivery, a grant; and another patient's
    order that must not appear."""
    excerpt = {"resourceType": "Patient", "id": PATIENT,
               "identifier": [{"system": "http://electronichealth.se/identifier/personnummer",
                               "value": TOLVAN}],
               "name": [{"family": "Tolvansson", "given": ["Tolvan"]}]}
    cp = CarePlan(patient_guid=PATIENT, plan_definition_guid="pd-1", status="active",
                  intent="plan", title="Diabetesplan", goals=[], created_by_user_guid="u-req")
    db_session.add(cp)
    db_session.commit()
    sr = ServiceRequest(patient_guid=PATIENT, plan_definition_guid="pd-1",
                        plan_definition_snapshot={"title": "Glukos"}, patient_excerpt=excerpt,
                        requester_user_guid="u-req", requester_user_name="Dr Req",
                        requester_org_guid=UNIT_A, care_plan_guid=cp.guid)
    db_session.add(sr)
    db_session.commit()
    from app.services.fhir_builder_service import build_service_request_resource
    versioning.note_change(sr, "u-req", "finalized: sent", "finalize")
    sr.fhir_resource = build_service_request_resource(sr)
    sr.status = "active"
    db_session.commit()
    versioning.note_change(sr, "u-nurse", "note added", "add_note")
    sr.annotations = [{"text": "Ring", "time": "2026-11-24T10:00:00+00:00",
                       "author_guid": "u-nurse", "kind": "note"}]
    db_session.commit()
    versioning.note_change(sr, None, "period over", "auto_archive_expired")
    sr.status = "archived"
    db_session.commit()
    versioning.note_change(cp, "u-req", "on hold", "update")
    cp.status = "on-hold"
    db_session.commit()

    legacy = ServiceRequest(patient_guid=PATIENT, plan_definition_guid="pd-2",
                            requester_user_guid="u-old", requester_org_guid=UNIT_A,
                            status="draft", version_reason=versioning.PRE_HISTORY_REASON)
    other = ServiceRequest(patient_guid=OTHER, plan_definition_guid="pd-1",
                           requester_user_guid="u-x", requester_org_guid=UNIT_B)
    db_session.add_all([legacy, other])
    db_session.commit()
    m = ServiceRequestContractMatch(service_request_guid=sr.guid, contract_guid="c-1",
                                    provider_org_guid="prov-1", provider_name="Medi AB",
                                    status="accepted", sent_at=datetime(2026, 11, 20, 9))
    db_session.add(m)
    db_session.commit()
    db_session.add(ServiceRequestReceipt(service_request_guid=sr.guid, contract_match_guid=m.guid,
                                         receipt_token=RECEIPT_TOKEN, delivery_status="delivered"))
    db_session.add(DataExchangeGrant(service_request_guid=sr.guid, patient_guid=PATIENT,
                                     provider_org_guid="prov-1", contract_guid="c-1",
                                     grant_token=GRANT_TOKEN,
                                     expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    db_session.commit()
    return {"sr": sr.guid, "legacy": legacy.guid, "cp": cp.guid, "other": other.guid}


def _audit(action, subject=PATIENT):
    db.session.expire_all()
    return AuditLog.query.filter_by(action=action, data_subject_guid=subject).all()


def _section(body, key):
    (s,) = [s for s in body["sections"] if s["key"] == key]
    return s


# ── served ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["doctor_a", "nurse_a", "su"])
def test_doctor_nurse_at_the_unit_and_su_get_the_extract(api, data, kind):
    r = api.get(URL(), headers=H(kind))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert (body["schema"], body["service"], body["patient_guid"], body["complete"]) == \
        ("pdhc.patient-extract/1", "request.pdhc", PATIENT, True)
    assert [s["key"] for s in body["sections"]] == [
        "service_requests", "care_plans", "dispatches", "data_exchange_grants"]


def test_counts_match_the_database(api, data):
    body = api.get(URL(), headers=H("doctor_a")).get_json()
    srs = _section(body, "service_requests")
    assert srs["count"] == len(srs["items"]) == \
        ServiceRequest.query.filter_by(patient_guid=PATIENT).count() == 2
    for item in srs["items"]:
        n_hist = ServiceRequestHistory.query.filter_by(service_request_guid=item["id"]).count()
        assert len(item["versions"]) == n_hist + 1
    cps = _section(body, "care_plans")
    assert cps["count"] == CarePlan.query.filter_by(patient_guid=PATIENT).count() == 1
    assert len(cps["items"][0]["versions"]) == \
        CarePlanHistory.query.filter_by(care_plan_guid=data["cp"]).count() + 1 == 2
    assert _section(body, "dispatches")["count"] == ServiceRequestContractMatch.query.filter(
        ServiceRequestContractMatch.service_request_guid.in_([data["sr"], data["legacy"]])).count()
    assert _section(body, "data_exchange_grants")["count"] == \
        DataExchangeGrant.query.filter_by(patient_guid=PATIENT).count() == 1
    assert data["other"] not in json.dumps(body)


def test_every_version_oldest_first_with_who_and_when(api, data):
    body = api.get(URL(), headers=H("doctor_a")).get_json()
    (item,) = [i for i in _section(body, "service_requests")["items"] if i["id"] == data["sr"]]
    vs = item["versions"]
    assert [v["version"] for v in vs] == [1, 2, 3, 4]
    assert [v["status"] for v in vs] == ["draft", "active", "active", "archived"]
    assert [v["fhir"]["status"] for v in vs] == ["draft", "active", "active", "completed"]
    assert vs[0]["author"] == {"guid": "u-req", "name": "Dr Req", "role": None,
                               "service": "request.pdhc"}
    assert vs[2]["author"]["guid"] == "u-nurse" and vs[3]["author"] is None
    assert vs[1]["superseded"]["action"] == "add_note"
    assert all(v["event_time"] and v["recorded_at"] for v in vs)
    assert vs[2]["fhir"]["note"][0]["text"] == "Ring"
    assert item["current_status"] == "archived"
    assert vs[0]["summary_sv"].startswith("Beställning: Glukos (utkast)")


def test_pre_history_order_is_one_version_and_said_so(api, data):
    body = api.get(URL(), headers=H("doctor_a")).get_json()
    (item,) = [i for i in _section(body, "service_requests")["items"] if i["id"] == data["legacy"]]
    assert len(item["versions"]) == 1 and item["versions"][0]["author"]["guid"] == "u-old"
    assert any("#1054" in n and "1 beställning" in n for n in body["notes"])


def test_no_personnummer_and_no_tokens(api, data):
    text = api.get(URL(), headers=H("doctor_a")).get_data(as_text=True)
    assert TOLVAN not in text
    assert RECEIPT_TOKEN not in text and GRANT_TOKEN not in text
    assert "grant_token" not in text and "receipt_token" not in text
    # the stored order still has it (it is what was sent); only the extract drops it
    sr = ServiceRequest.query.filter_by(guid=data["sr"]).one()
    assert TOLVAN in json.dumps(sr.fhir_resource)


def test_every_fhir_body_is_valid_r5(api, data):
    fr = pytest.importorskip("fhir.resources", reason="pip install -r requirements-test.txt")
    del fr
    from fhir.resources import get_fhir_model_class
    body = api.get(URL(), headers=H("doctor_a")).get_json()
    n = 0
    for s in body["sections"]:
        for item in s["items"]:
            for v in item["versions"]:
                if v["fhir"] is not None:
                    get_fhir_model_class(v["fhir"]["resourceType"]).model_validate(v["fhir"])
                    n += 1
    assert n == 4 + 1 + 2 + 1  # sr versions, legacy, care plan versions, task


def test_served_extract_is_audited(api, data):
    api.get(URL(), headers=H("nurse_a"))
    (row,) = _audit("patient_extract")
    assert row.user_guid == "user-nurse_a"
    assert row.details["outcome"] == "served" and row.details["access_basis"] == "same_unit"
    assert row.details["counts"]["service_requests"] == 2


def test_empty_patient_for_su_is_an_empty_complete_extract(api, data):
    with patch("app.services.patient_service.get_patient_clinic_orgs",
               return_value=([("clinic-x", "unit-x")], 200)):
        body = api.get(URL("dddd1059-0000-4000-8000-00000000000d"), headers=H("su")).get_json()
    assert body["sections"] == [] and body["complete"] is True


def test_the_extract_shows_in_the_patients_access_log(api, data):
    api.get(URL(), headers=H("doctor_a"))
    api.get(URL(), headers=H("doctor_b"))
    log = api.get(f"/api/v1/patients/{PATIENT}/access-log", headers=H("doctor_a")).get_json()
    actions = [(i["action"], i["outcome"]) for i in log["items"]]
    assert ("patient_extract", "served") in actions
    assert ("patient_extract.denied", "denied") in actions


# ── refused, and every refusal audited ────────────────────────────────────

@pytest.mark.parametrize("kind,status,code,reason", [
    ("doctor_b", 403, "forbidden", "patient_org_mismatch"),
    ("other_care_a", 403, "forbidden", "role_not_permitted"),
    ("service", 403, "person_required", "not_a_person"),
    ("patient", 403, "not_professional", "not_professional"),
])
def test_refusals(api, data, kind, status, code, reason):
    r = api.get(URL(), headers=H(kind))
    assert (r.status_code, r.get_json()["code"]) == (status, code)
    assert "sections" not in r.get_json()
    (row,) = _audit("patient_extract.denied")
    assert row.details["reason"] == reason and row.details["outcome"] == "denied"
    assert _audit("patient_extract") == []


def test_no_credential_is_401(api, data):
    assert api.get(URL()).status_code == 401


def test_provider_token_is_refused(api, data):
    pat = SimpleNamespace(guid="pat-1", provider_org_guid="prov-1", contract_guid="c-1",
                          delivery_mode="poll")
    with patch("app.services.pat_service.validate_pat", return_value=pat):
        r = api.get(URL(), headers={"X-Provider-Token": "t"})
    assert (r.status_code, r.get_json()["code"]) == (403, "person_required")
    assert _audit("patient_extract.denied")[0].details["reason"] == "provider_token"


def test_eps_unreachable_is_502_never_an_empty_extract(api, data):
    with patch("app.services.patient_service.get_patient_clinic_orgs",
               return_value=([], 503)):
        r = api.get(URL(), headers=H("doctor_a"))
    assert r.status_code == 502 and "sections" not in r.get_json()
    assert _audit("patient_extract.denied")[0].details["reason"] == "ips_lookup_failed"


def test_unknown_patient_is_404_for_a_professional(api, data):
    r = api.get(URL(UNKNOWN), headers=H("doctor_a"))
    assert r.status_code == 404
    assert _audit("patient_extract.denied", UNKNOWN)[0].details["reason"] == "patient_not_found"


def test_extract_blob_keeps_only_doctor_and_nurse():
    b = extract_blob({"affiliations": [{"care_unit_guid": "u1", "role": "doctor"},
                                       {"care_unit_guid": "u2", "role": "other_care"},
                                       {"care_unit_guid": "u3", "role": "nurse"}]})
    assert [a["care_unit_guid"] for a in b["affiliations"]] == ["u1", "u3"]

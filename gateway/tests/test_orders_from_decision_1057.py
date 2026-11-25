"""#1057 (record.pdhc stage 5): an order made FROM A MEDICAL DECISION, and the
read that finds it again.

record.pdhc creates the follow-up order through the ordinary create route
with the professional's OWN bearer on `X-API-Key` (request accepts no service
key), carrying `supporting_info: ["ClinicalImpression/<id>/_history/<n>"]` —
#1054 already stores that and renders it as R5 `supportingInfo`. What #1057
adds is the reverse read, so record shows "orders made from this decision"
from the stored orders instead of a second copy:

    GET /api/v1/patients/<patient>/ServiceRequest?supporting-info=<ref>

AUTH ON through the real `requires_auth`; only sso validation, the eps clinic
lookup and the plan/patient fetches are replaced.
"""
import copy
from unittest.mock import patch

import pytest

from app.api.service_requests import supporting_info_matches
from app.models.audit_models import AuditLog
from app.models.service_request_models import ServiceRequest
from app.services import ips_client, scope_service
from app.services import service_request_service as svc
from app import db

PATIENT = "aaaa1057-0000-4000-8000-00000000000a"
OTHER = "bbbb1057-0000-4000-8000-00000000000b"
UNIT_A, UNIT_B = "unit-a-1057", "unit-b-1057"
CI = "c1c1c1c1-0000-4000-8000-000000001057"
CI2 = "c2c2c2c2-0000-4000-8000-000000001057"
ENC = "e0e0e0e0-0000-4000-8000-000000001057"


def _blob(kind):
    b = {"user_guid": f"user-{kind}", "user_type": "professional", "is_su_admin": False,
         "affiliations": [], "session_phases": ["request"], "display_name": f"Dr {kind}"}
    if kind == "doctor_a":
        b["affiliations"] = [{"care_unit_guid": UNIT_A, "role": "doctor"}]
    elif kind == "doctor_b":
        b["affiliations"] = [{"care_unit_guid": UNIT_B, "role": "doctor"}]
    elif kind == "su":
        b["is_su_admin"] = True
    return b


def H(kind):
    return {"X-API-Key": f"tok-{kind}"}


@pytest.fixture
def api(client, app, monkeypatch):
    app.config["AUTH_DISABLED"] = False
    monkeypatch.setattr(ips_client, "is_sr_visible", lambda sr, client=None: True)
    monkeypatch.setattr('app.services.service_request_service.patient_service.get_patient',
                        lambda g: ({'id': g}, 200))
    monkeypatch.setattr(
        'app.services.service_request_service.plan_definition_service.get_plan_definition',
        lambda g: (copy.deepcopy({"title": "HbA1c", "goals": [], "activities": [], "id": g}),
                   200))
    monkeypatch.setattr('app.services.service_request_service.build_patient_excerpt',
                        lambda d: {})
    monkeypatch.setattr(scope_service, 'fetch_scope', lambda g: None)

    def validate(tok):
        kind = tok[len("tok-"):]
        return _blob(kind) if kind in ("doctor_a", "doctor_b", "su") else None

    def clinics(g):
        return {PATIENT: ([("clinic-a", UNIT_A)], 200),
                OTHER: ([("clinic-b", UNIT_B)], 200)}.get(g, ([], 404))

    with patch("app.middleware.auth_middleware.validate_api_key", side_effect=validate), \
            patch("app.services.patient_service.get_patient_clinic_orgs", side_effect=clinics):
        yield client


def _order(client, who="doctor_a", patient=PATIENT, ci=CI, version=1):
    return client.post("/api/v1/ServiceRequest", headers=H(who), json={
        "patient_guid": patient, "plan_definition_guid": "pd-1057",
        "encounter_guid": ENC,
        "supporting_info": [f"ClinicalImpression/{ci}/_history/{version}"],
        "reason": [{"concept": {"text": "Uppföljning efter beslut"}}],
        "notes": "Nytt HbA1c om tre månader"})


def _citing(client, ref, who="doctor_a", patient=PATIENT):
    return client.get(f"/api/v1/patients/{patient}/ServiceRequest",
                      query_string={"supporting-info": ref}, headers=H(who))


def test_an_order_from_a_decision_carries_the_versioned_decision(api):
    r = _order(api)
    assert r.status_code == 201, r.get_json()
    sr = ServiceRequest.query.filter_by(guid=r.get_json()["guid"]).one()
    assert sr.supporting_info == [f"ClinicalImpression/{CI}/_history/1"]
    assert sr.encounter_guid == ENC
    assert sr.requester_user_guid == "user-doctor_a"   # the PERSON, not record


def test_the_decision_finds_its_orders_every_version_and_only_its_own(api):
    a = _order(api, version=1).get_json()["guid"]
    b = _order(api, version=2).get_json()["guid"]
    other_decision = _order(api, ci=CI2).get_json()["guid"]
    body = _citing(api, f"ClinicalImpression/{CI}").get_json()
    assert sorted(i["guid"] for i in body["items"]) == sorted([a, b])
    assert other_decision not in [i["guid"] for i in body["items"]]
    one = _citing(api, f"ClinicalImpression/{CI}/_history/2").get_json()
    assert [i["guid"] for i in one["items"]] == [b]
    by_type = _citing(api, "ClinicalImpression").get_json()
    assert {i["guid"] for i in by_type["items"]} == {a, b, other_decision}
    assert body["items"][0]["supporting_info"][0].startswith(f"ClinicalImpression/{CI}/")


def test_the_read_is_gated_on_the_patient_and_refusals_are_audited(api):
    _order(api)
    r = _citing(api, f"ClinicalImpression/{CI}", who="doctor_b")
    assert r.status_code == 403
    db.session.expire_all()
    assert AuditLog.query.filter_by(action="service_request.by_supporting_info.denied",
                                    data_subject_guid=PATIENT).count() == 1
    assert _citing(api, f"ClinicalImpression/{CI}", who="su").status_code == 200
    assert api.get(f"/api/v1/patients/{PATIENT}/ServiceRequest",
                   query_string={"supporting-info": "ClinicalImpression"}).status_code == 401


def test_supporting_info_is_required(api):
    r = api.get(f"/api/v1/patients/{PATIENT}/ServiceRequest", headers=H("doctor_a"))
    assert r.status_code == 400


def test_a_served_read_is_audited(api):
    _order(api)
    assert _citing(api, f"ClinicalImpression/{CI}").status_code == 200
    db.session.expire_all()
    assert AuditLog.query.filter_by(action="service_request.by_supporting_info").count() >= 1


def test_spaerr_hides_a_blocked_order(api, monkeypatch):
    g = _order(api).get_json()["guid"]
    monkeypatch.setattr(ips_client, "is_sr_visible", lambda sr, client=None: sr.guid != g)
    assert _citing(api, f"ClinicalImpression/{CI}").get_json()["items"] == []


@pytest.mark.parametrize("refs,wanted,hit", [
    ([f"ClinicalImpression/{CI}/_history/1"], f"ClinicalImpression/{CI}", True),
    ([f"ClinicalImpression/{CI}"], f"ClinicalImpression/{CI}", True),
    ([f"ClinicalImpression/{CI}9/_history/1"], f"ClinicalImpression/{CI}", False),
    ([f"ClinicalImpression/{CI}/_history/1"], f"ClinicalImpression/{CI}/_history/12", False),
    ([{"reference": {"reference": f"ClinicalImpression/{CI}"}}], "ClinicalImpression", True),
    ([], "ClinicalImpression", False),
    (None, "ClinicalImpression", False),
    ([f"ClinicalImpression/{CI}"], "", False),
])
def test_matching_is_by_whole_segments(refs, wanted, hit):
    assert supporting_info_matches(refs, wanted) is hit

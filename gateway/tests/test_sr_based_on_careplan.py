"""A ServiceRequest is grounded in the patient's CarePlan (operator 2026-11-19).

ServiceRequest.basedOn -> CarePlan/<guid> -> instantiatesCanonical PlanDefinition.
One SHARED CarePlan per (patient, PlanDefinition): every request attaches to
the open plan, a closed plan is not reused. Before this, no creation path set
care_plan_guid (0 of 21 production requests had one).
"""
import copy

import pytest

from app import db as _db
from app.models.care_plan_models import CarePlan
from app.models.service_request_models import ServiceRequest
from app.services import service_request_service
from app.services.care_plan_link import link_existing
from app.services.fhir_builder_service import build_service_request_resource
from tests.test_dispatch_trigger import _clean, stubs  # noqa: F401  (fixtures)

PLAN = {"id": "pd-cp", "title": "Veckorapport", "goals": [],
        "activities": [{"transactions": [{"guid": "t1", "transaction_guid": "t1",
                                          "concept_name": "note"}]}]}


@pytest.fixture
def plan_stub(monkeypatch, stubs):  # noqa: F811
    monkeypatch.setattr(
        'app.services.service_request_service.plan_definition_service.get_plan_definition',
        lambda pd_guid: (copy.deepcopy({**PLAN, "id": pd_guid}), 200))


def _create(patient, plandef="pd-cp", contract=None):
    r, st = service_request_service.create_service_request(
        patient_guid=patient, plan_definition_guid=plandef, user_guid="u-cp",
        contract_guid=contract)
    assert st == 201, r
    return ServiceRequest.query.filter_by(guid=r["guid"]).one()


def test_requests_share_one_careplan_per_patient_and_plandef(app, plan_stub):
    with app.app_context():
        a, b = _create("pat-cp1"), _create("pat-cp1")
        other_patient = _create("pat-cp2")
        other_plan = _create("pat-cp1", plandef="pd-other")
        assert a.care_plan_guid and a.care_plan_guid == b.care_plan_guid
        assert other_patient.care_plan_guid != a.care_plan_guid
        assert other_plan.care_plan_guid != a.care_plan_guid
        cp = CarePlan.query.filter_by(guid=a.care_plan_guid).one()
        assert (cp.patient_guid, cp.plan_definition_guid, cp.status) == ("pat-cp1", "pd-cp", "active")
        assert cp.title == "Veckorapport"


def test_a_closed_careplan_is_not_reused(app, plan_stub):
    with app.app_context():
        first = _create("pat-cp3")
        cp = CarePlan.query.filter_by(guid=first.care_plan_guid).one()
        cp.status = "completed"
        _db.session.commit()
        assert _create("pat-cp3").care_plan_guid != first.care_plan_guid


def test_fhir_basedOn_is_the_careplan_and_the_contract_moves_to_supportingInfo(app, plan_stub):
    with app.app_context():
        sr = _create("pat-cp4", contract="c-cp")
        res = build_service_request_resource(sr)
        assert res["basedOn"] == [{"reference": f"CarePlan/{sr.care_plan_guid}", "type": "CarePlan"}]
        assert not any("Contract" in b["reference"] for b in res["basedOn"])
        refs = [s["reference"]["reference"] for s in res["supportingInfo"]]
        assert any(r.endswith("/Contract/c-cp") for r in refs)
        assert res["instantiatesCanonical"][0].endswith("/plandefinitions/pd-cp")
        # the contained snapshot (what provider1/cgm execute) names the real plan
        contained = [c for c in res["contained"] if c["resourceType"] == "CarePlan"]
        assert contained and contained[0]["identifier"][0]["value"] == sr.care_plan_guid


def test_backfill_links_old_requests_dry_run_first(app, plan_stub):
    with app.app_context():
        old = [_create("pat-cp5"), _create("pat-cp5"), _create("pat-cp6")]
        for sr in old:
            sr.care_plan_guid = None
        CarePlan.query.filter(CarePlan.patient_guid.in_(["pat-cp5", "pat-cp6"])).delete()
        _db.session.commit()
        dry = link_existing(apply=False)
        assert (dry["groups"], dry["plans_created"]) >= (2, 2)
        assert all(_db.session.get(ServiceRequest, sr.id).care_plan_guid is None for sr in old)
        assert CarePlan.query.filter(CarePlan.patient_guid.in_(["pat-cp5", "pat-cp6"])).count() == 0
        link_existing(apply=True)
        a, b, c = (_db.session.get(ServiceRequest, sr.id) for sr in old)
        assert a.care_plan_guid and a.care_plan_guid == b.care_plan_guid != c.care_plan_guid
        assert link_existing(apply=False)["requests"] == 0          # idempotent

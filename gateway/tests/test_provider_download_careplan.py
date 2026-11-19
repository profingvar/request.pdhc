"""The provider download carries the plan THIS order instantiates (2026-11-19).

Asked for by a provider (MMD): the delivered CarePlan listed only concepts, so
they read the live template via instantiatesCanonical -- whose schedule had
changed since the order while its version string had not. The download now
carries the order's FROZEN activities, schedule and transaction_guids, the
shared care_plan_guid, and a plain is_open flag.
"""
import uuid

from app import db
from app.services import provider_feed_service
from tests.test_provider_feed_archived import _mk_match

SNAP = {"title": "MMD_plan", "version": "1.0.0", "activities": [
    {"activity_guid": "a-2", "sort_order": 1, "title": "Veckorapport", "performer_type": "Patient",
     "timing_type": "repeat", "timing_frequency": 1, "timing_period": 1, "timing_period_unit": "wk",
     "timing_bounds_mode": "count", "timing_bounds_count": 8, "duration_value": 3, "duration_unit": "min",
     "transactions": [{"transaction_guid": "t-2", "concept_guid": "c-2", "concept_name": "note",
                       "response_type": "text", "requirement_type": "required"}]},
    {"activity_guid": "a-1", "sort_order": 0, "title": "CGM", "timing_type": "once",
     "transactions": [{"transaction_guid": "t-1", "concept_guid": "c-1", "concept_name": "CGM",
                       "unit": "mmol/L", "range_min": 4.0, "range_max": 8.0}]}]}


def _download(app, status):
    from app.models.service_request_models import ServiceRequest
    prov = str(uuid.uuid4())
    with app.app_context():
        sr = ServiceRequest(guid=str(uuid.uuid4()), status=status, patient_guid=str(uuid.uuid4()),
                            plan_definition_guid="pd-mmd", plan_definition_snapshot=SNAP,
                            contract_guid=str(uuid.uuid4()), requester_user_guid="u",
                            care_plan_guid="cp-1",
                            fhir_resource={"resourceType": "ServiceRequest", "status": "active"})
        db.session.add(sr); db.session.flush()
        _mk_match(sr, prov, match_status="sent")
        db.session.commit()
        data, st = provider_feed_service.download_bundle(sr.guid, prov, sr.contract_guid)
        assert st == 200, data
        return data


def test_download_carries_the_frozen_instantiated_plan(app):
    d = _download(app, "active")
    assert d["care_plan_guid"] == "cp-1" and d["is_open"] is True
    cp = d["care_plan"]
    assert (cp["care_plan_guid"], cp["plan_definition_version"]) == ("cp-1", "1.0.0")
    assert [a["title"] for a in cp["activities"]] == ["CGM", "Veckorapport"]      # sort_order
    weekly = cp["activities"][1]
    assert weekly["timing"] == {"repeat": {"frequency": 1, "period": 1, "periodUnit": "wk",
                                           "count": 8, "duration": 3, "durationUnit": "min"}}
    assert weekly["transactions"][0]["transaction_guid"] == "t-2"
    assert cp["activities"][0]["timing"] is None                                 # once
    assert cp["activities"][0]["transactions"][0]["unit"] == "mmol/L"


def test_an_archived_order_says_so_in_one_field(app):
    d = _download(app, "archived")
    assert d["is_open"] is False and d["sr_status"] == "archived"

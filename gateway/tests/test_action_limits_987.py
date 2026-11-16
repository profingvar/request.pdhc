"""Action limits on an order keep their provenance (#987 follow-through).

plan.pdhc's range is the RECOMMENDED NORMAL; the ACTION limit is the
requester's, set on the draft order in request.pdhc.
"""
import copy
import json

import pytest

from app import db as _db
from app.models.audit_models import AuditLog
from app.models.service_request_models import ServiceRequest
from app.services import action_limits as al
from app.services import service_request_service
from tests.test_dispatch_trigger import _clean, stubs  # noqa: F401  (fixtures)

PLAN = {"id": "pd", "version": "1.1.0", "activities": [{"transactions": [
    {"guid": "t-dia", "transaction_guid": "t-dia", "concept_name": "bp_diastolic", "range_min": 60.0, "range_max": 90.0},
    {"guid": "t-sys", "transaction_guid": "t-sys", "concept_name": "bp_systolic", "range_min": 100.0, "range_max": 160.0},
    {"guid": "t-note", "transaction_guid": "t-note", "concept_name": "note"}]}]}


def _tx(snap, g):
    return next(t for a in snap["activities"] for t in a["transactions"] if t["transaction_guid"] == g)


# ----------------------------------------------------------------- pure functions

def test_create_records_plan_range_as_RECOMMENDED():
    s = al.stamp_recommended(PLAN)
    d = _tx(s, "t-dia")
    assert (d["range_min"], d["range_max"]) == (60.0, 90.0), "the action limit starts as plan's"
    assert (d["recommended_range_min"], d["recommended_range_max"]) == (60.0, 90.0)
    assert d["action_limit_source"] == "plan_recommended"
    assert "action_limit_source" not in _tx(s, "t-note"), "no range, no provenance"
    assert "recommended_range_min" not in _tx(PLAN, "t-dia"), "input not mutated"


def test_a_requester_edit_is_marked_and_listed():
    stored = al.stamp_recommended(PLAN)
    edited = copy.deepcopy(stored)
    _tx(edited, "t-dia").update(range_min=55.0, range_max=95.0)
    out, ch = al.merge_edit(stored, edited)
    d = _tx(out, "t-dia")
    assert d["action_limit_source"] == "requester"
    assert (d["recommended_range_min"], d["recommended_range_max"]) == (60.0, 90.0)
    assert ch == [{"transaction_guid": "t-dia", "concept_name": "bp_diastolic",
                   "before": [60.0, 90.0], "after": [55.0, 95.0], "recommended": [60.0, 90.0]}]
    assert _tx(out, "t-sys")["action_limit_source"] == "plan_recommended"


def test_the_client_cannot_rewrite_the_recommendation_or_the_source():
    stored = al.stamp_recommended(PLAN)
    edited = copy.deepcopy(stored)
    _tx(edited, "t-dia").update(range_min=55.0, recommended_range_min=55.0, action_limit_source="plan_recommended")
    out, _ = al.merge_edit(stored, edited)
    d = _tx(out, "t-dia")
    assert d["recommended_range_min"] == 60.0 and d["action_limit_source"] == "requester"


def test_editing_back_to_the_recommendation_is_plan_recommended_again():
    stored, _ = al.merge_edit(al.stamp_recommended(PLAN), _with(al.stamp_recommended(PLAN), 50.0, 90.0))
    out, ch = al.merge_edit(stored, _with(stored, 60.0, 90.0))
    assert _tx(out, "t-dia")["action_limit_source"] == "plan_recommended" and len(ch) == 1


def _with(snap, lo, hi):
    e = copy.deepcopy(snap); _tx(e, "t-dia").update(range_min=lo, range_max=hi); return e


@pytest.mark.parametrize("lo,hi", [(90.0, 60.0), (60.0, 60.0), ("60", 90.0), (True, 90.0), (float("nan"), 90.0)])
def test_invalid_action_limits_are_refused(lo, hi):
    with pytest.raises(al.InvalidActionLimit):
        al.merge_edit(al.stamp_recommended(PLAN), _with(al.stamp_recommended(PLAN), lo, hi))


def test_a_legacy_draft_without_provenance_uses_its_stored_range():
    out, _ = al.merge_edit(PLAN, _with(PLAN, 55.0, 90.0))
    d = _tx(out, "t-dia")
    assert d["recommended_range_min"] == 60.0 and d["action_limit_source"] == "requester"


# ----------------------------------------------------------------- the service path

@pytest.fixture
def plan_stub(monkeypatch, stubs):  # noqa: F811
    monkeypatch.setattr(
        'app.services.service_request_service.plan_definition_service.get_plan_definition',
        lambda pd_guid: (copy.deepcopy(PLAN), 200))


def test_create_then_edit_is_stored_and_AUDITED_with_details(app, plan_stub):
    with app.app_context():
        r, st = service_request_service.create_service_request(
            patient_guid="pat-987", plan_definition_guid="pd", user_guid="u-987", contract_guid="c-987")
        assert st == 201, r
        sr = _db.session.get(ServiceRequest, r["id"]) if "id" in r else ServiceRequest.query.filter_by(guid=r["guid"]).one()
        assert _tx(sr.plan_definition_snapshot, "t-dia")["action_limit_source"] == "plan_recommended"
        r2, st2 = service_request_service.update_plan_definition_snapshot(
            r["guid"], _with(sr.plan_definition_snapshot, 50.0, 85.0), user_guid="u-987")
        assert st2 == 200, r2
        assert _tx(r2["plan_definition_snapshot"], "t-dia")["action_limit_source"] == "requester"
        log = AuditLog.query.filter_by(action="service_request.edit_plandef", resource_guid=r["guid"]).one()
        details = log.details if isinstance(log.details, dict) else json.loads(log.details)
        assert details["action_limit_changes"][0]["after"] == [50.0, 85.0]
        bad, st3 = service_request_service.update_plan_definition_snapshot(
            r["guid"], _with(sr.plan_definition_snapshot, 90.0, 50.0), user_guid="u-987")
        assert st3 == 400 and bad["code"] == "invalid_action_limit"


def test_a_client_cannot_invent_a_recommendation_for_a_transaction_it_added():
    stored = al.stamp_recommended(PLAN)
    edited = copy.deepcopy(stored)
    edited["activities"][0]["transactions"].append(
        {"transaction_guid": "t-new", "concept_name": "x", "range_min": 1.0, "range_max": 2.0,
         "recommended_range_min": 1.0, "recommended_range_max": 2.0, "action_limit_source": "plan_recommended"})
    out, _ = al.merge_edit(stored, edited)
    t = _tx(out, "t-new")
    assert "recommended_range_min" not in t and t["action_limit_source"] == "requester"


# ----------------------------------------------------------------- CarePlan goals (the dashboard's limits)

from unittest.mock import patch  # noqa: E402

GOAL_PLAN = {"guid": "pd-g", "title": "BP", "activities": [], "goals": [
    {"guid": "g-dia", "concept_guid": "c-dia", "target_type": "range",
     "target_range_low": 60.0, "target_range_high": 90.0, "target_unit": "mm[Hg]"}]}


def _cp(client, **extra):
    with patch('app.api.care_plans.plan_definition_service.get_plan_definition',
               return_value=(copy.deepcopy(GOAL_PLAN), 200)):
        return client.post('/api/v1/careplans', json={'patient_guid': 'pat-g', 'plan_definition_guid': 'pd-g', **extra})


def test_inherited_goals_are_plan_recommended(client):
    g, = _cp(client).get_json()["goals"]
    assert g["limit_source"] == "plan_recommended"
    assert g["recommended"]["target_range_low"] == 60.0


def test_a_goal_edit_is_the_requesters_and_AUDITED(client, app):
    cp = _cp(client).get_json()
    goals = copy.deepcopy(cp["goals"])
    goals[0].update(target_range_low=55.0, recommended={"target_range_low": 55.0}, limit_source="plan_recommended")
    r = client.put(f"/api/v1/careplans/{cp['guid']}", json={"goals": goals})
    assert r.status_code == 200, r.get_json()
    g, = r.get_json()["goals"]
    assert g["limit_source"] == "requester" and g["recommended"]["target_range_low"] == 60.0
    with app.app_context():
        log = AuditLog.query.filter_by(action="care_plan.goals_update", resource_guid=cp["guid"]).one()
        d = log.details if isinstance(log.details, dict) else json.loads(log.details)
        ch, = d["action_limit_changes"]
        assert (ch["before"]["target_range_low"], ch["after"]["target_range_low"]) == (60.0, 55.0)


def test_removing_a_goal_is_listed(client, app):
    cp = _cp(client).get_json()
    assert client.put(f"/api/v1/careplans/{cp['guid']}", json={"goals": []}).status_code == 200
    with app.app_context():
        log = AuditLog.query.filter_by(action="care_plan.goals_update", resource_guid=cp["guid"]).one()
        d = log.details if isinstance(log.details, dict) else json.loads(log.details)
        assert d["action_limit_changes"][0]["after"] is None


@pytest.mark.parametrize("bad", [{"target_range_low": 90.0, "target_range_high": 60.0}, {"target_quantity": "7"}])
def test_invalid_goals_are_refused_on_create_and_update(client, bad):
    assert _cp(client, goals=[{"concept_guid": "c", **bad}]).status_code == 400
    cp = _cp(client).get_json()
    assert client.put(f"/api/v1/careplans/{cp['guid']}", json={"goals": [{"concept_guid": "c", **bad}]}).status_code == 400


def test_a_NEW_goal_cannot_claim_to_be_plans():
    out, ch = al.merge_goals([], [{"concept_guid": "c", "target_range_low": 1.0, "target_range_high": 2.0,
                                   "recommended": {"target_range_low": 1.0}, "limit_source": "plan_recommended"}])
    assert "recommended" not in out[0] and out[0]["limit_source"] == "requester" and len(ch) == 1

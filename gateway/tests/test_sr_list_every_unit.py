"""ServiceRequest lists show EVERY care unit the caller is affiliated to, and
a non-SU caller with NO unit sees nothing — on the web lists too.

Main rule (operator 2026-11-13): a professional is employed by a vårdgivare
and affiliated to SEVERAL units; the unit scopes patients. The three lists
took `caller_org_ids(blob)[0]`, so requests from every unit but the first
were invisible. And the service filtered `if not is_su_admin and org_guid:`,
which SKIPPED the filter for a caller without a unit: #991 refused that on
the API route, but the two web lists still showed every ServiceRequest.
"""
from unittest.mock import patch

import pytest

from app.models.audit_models import AuditLog
from app.models.service_request_models import ServiceRequest
from app.services import service_request_service

UNIT_A, UNIT_B, UNIT_C = "unit-a-everyunit", "unit-b-everyunit", "unit-c-everyunit"


def _blob(*units, su=False):
    return {"user_guid": "u-eu", "email": "t@example.com", "user_type": "professional",
            "is_su_admin": su, "display_name": "T", "effective_phases": ["active"],
            "affiliations": [{"care_unit_guid": u, "care_unit_name": u} for u in units],
            "organization_ids": list(units)}


@pytest.fixture(autouse=True)
def _hygiene(db_session, app):
    prev = app.config.get("AUTH_DISABLED")
    app.config["AUTH_DISABLED"] = True
    yield
    app.config["AUTH_DISABLED"] = prev


@pytest.fixture(autouse=True)
def _no_spaerr():
    with patch("app.services.ips_client.is_sr_visible", return_value=True):
        yield


@pytest.fixture
def srs(db_session):
    """One active and one archived ServiceRequest in each of three units."""
    rows = {}
    for unit in (UNIT_A, UNIT_B, UNIT_C):
        for status in ("active", "archived"):
            r = ServiceRequest(patient_guid="p-eu", plan_definition_guid="pd-eu",
                               requester_user_guid="u-x", requester_org_guid=unit, status=status)
            db_session.add(r)
            rows[(unit, status)] = r
    db_session.commit()
    out = {k: r.guid for k, r in rows.items()}
    yield out
    db_session.query(ServiceRequest).filter(ServiceRequest.guid.in_(out.values())).delete(
        synchronize_session=False)
    db_session.commit()


def _own(guids_returned, srs):
    return {k for k, g in srs.items() if g in guids_returned}


# ---------------------------------------------------------------- service

def test_service_lists_EVERY_given_unit_and_no_other(app, srs):
    data, _ = service_request_service.list_service_requests(org_guids=[UNIT_A, UNIT_B])
    assert _own({i["guid"] for i in data["items"]}, srs) == {(UNIT_A, "active"), (UNIT_B, "active")}


def test_service_gives_a_non_su_with_NO_unit_an_empty_page(app, srs):
    for empty in (None, [], [None, ""]):
        data, status = service_request_service.list_service_requests(org_guids=empty)
        assert status == 200 and data["items"] == [] and data["total"] == 0, empty


def test_service_su_sees_all_units(app, srs):
    data, _ = service_request_service.list_service_requests(is_su_admin=True, per_page=200)
    assert {(UNIT_A, "active"), (UNIT_B, "active"), (UNIT_C, "active")} <= \
        _own({i["guid"] for i in data["items"]}, srs)


# ---------------------------------------------------------------- web lists

def _web(client, url, blob):
    import app.routes.service_requests as mod
    with patch.object(mod, "get_current_access_blob", return_value=blob), \
         patch.object(mod, "get_current_user_guid", return_value="u-eu"):
        r = client.get(url)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    return {k for k, g in srs_holder[0].items() if g in body}


srs_holder = []


@pytest.fixture
def web(srs):
    srs_holder[:] = [srs]
    yield
    srs_holder.clear()


def test_web_list_shows_requests_from_EVERY_unit(client, web):
    assert _web(client, "/service-requests", _blob(UNIT_A, UNIT_B)) == \
        {(UNIT_A, "active"), (UNIT_B, "active")}


def test_web_archive_shows_requests_from_EVERY_unit(client, web):
    assert _web(client, "/service-requests/archived", _blob(UNIT_A, UNIT_B)) == \
        {(UNIT_A, "archived"), (UNIT_B, "archived")}


@pytest.mark.parametrize("url", ["/service-requests", "/service-requests/archived"])
def test_web_lists_NO_LONGER_FAIL_OPEN_for_a_caller_with_no_unit(client, web, url):
    assert _web(client, url, _blob()) == set()


# ---------------------------------------------------------------- API

def _api(client, blob):
    with patch("app.api.service_requests.get_current_access_blob", return_value=blob):
        return client.get("/api/v1/ServiceRequest")


def test_api_list_shows_requests_from_EVERY_unit(client, db_session, srs):
    r = _api(client, _blob(UNIT_A, UNIT_B))
    assert r.status_code == 200
    assert _own({i["guid"] for i in r.get_json()["items"]}, srs) == \
        {(UNIT_A, "active"), (UNIT_B, "active")}


def test_api_list_with_no_unit_is_still_403(client, db_session, srs):
    db_session.query(AuditLog).delete(); db_session.commit()
    assert _api(client, _blob()).status_code == 403

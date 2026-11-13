"""#996 — the request.pdhc WEB pages get the gates the API got in #991.

1. every web route keyed by a ServiceRequest guid reaches its patient only
   through the caller's care units (patient_access, #981);
2. the web is for professionals and SU admins — a patient's SSO login no
   longer reaches any web page;
3. the two web lists write an audit row (Rule 24).

Real non-SU blobs; each rule shown to fail with the gate removed.
"""
from unittest.mock import patch

import pytest

from app.middleware.auth_middleware import web_user_allowed
from app.models.audit_models import AuditLog
from app.models.service_request_models import ServiceRequest

PATIENT = "patient-996"
UNIT_A, UNIT_B = "unit-a-996", "unit-b-996"
CLINIC_A = "clinic-a-996"


def _blob(*units, su=False, user_type="professional"):
    return {"user_guid": "u-996", "email": "t@example.com", "user_type": user_type,
            "is_su_admin": su, "display_name": "T", "session_phases": ["request"],
            "affiliations": [{"care_unit_guid": u} for u in units],
            "organization_ids": list(units)}


@pytest.fixture(autouse=True)
def _hygiene(db_session, app):
    prev = app.config.get("AUTH_DISABLED")
    app.config["AUTH_DISABLED"] = True
    db_session.query(AuditLog).delete(); db_session.commit()
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
    row = ServiceRequest(patient_guid=PATIENT, plan_definition_guid="pd-996",
                         requester_user_guid="u-x", requester_org_guid=UNIT_A, status="draft")
    db_session.add(row); db_session.commit()
    yield row.guid
    db_session.query(ServiceRequest).filter_by(guid=row.guid).delete(); db_session.commit()


def _web(client, method, url, blob, ips_status=200):
    import app.routes.service_requests as mod
    with patch.object(mod, "get_current_access_blob", return_value=blob), \
         patch.object(mod, "get_current_user_guid", return_value="u-996"), \
         patch("app.services.patient_access.patient_service.get_patient_clinic_orgs",
               return_value=([(CLINIC_A, UNIT_A)], ips_status)):
        return getattr(client, method)(url)


WEB_GUID_ROUTES = [
    ("get", "", "read"), ("get", "/timeline", "timeline"), ("get", "/edit-plan", "edit_plan"),
    ("post", "/finalize", "finalize"), ("post", "/archive", "archive"), ("post", "/revoke", "revoke"),
    ("post", "/find-matches", "find_matches"), ("post", "/dispatch", "dispatch"),
    ("post", "/add-form", "forms.add"), ("post", "/remove-form/f-1", "forms.remove"),
    ("get", "/form/f-1", "forms.read"), ("post", "/push-all", "push"),
]


@pytest.mark.parametrize("method,suffix,verb", WEB_GUID_ROUTES)
def test_every_web_guid_route_REFUSES_another_care_unit(client, db_session, sr, method, suffix, verb):
    r = _web(client, method, f"/service-requests/{sr}{suffix}", _blob(UNIT_B))
    assert r.status_code == 302 and r.headers["Location"].endswith("/service-requests"), verb
    rows = AuditLog.query.filter_by(action=f"service_request.web.{verb}.denied").all()
    assert len(rows) == 1 and rows[0].details["reason"] == "patient_org_mismatch", verb
    db_session.expire_all()
    assert db_session.get(ServiceRequest, ServiceRequest.query.filter_by(guid=sr).first().id).status == "draft"


def test_a_write_from_another_unit_does_NOT_happen(client, db_session, sr):
    import app.routes.service_requests as mod
    with patch.object(mod.service_request_service, "archive_service_request") as archive:
        _web(client, "post", f"/service-requests/{sr}/archive", _blob(UNIT_B))
    archive.assert_not_called()


def test_the_patients_care_unit_passes_the_gate(client, sr):
    import app.routes.service_requests as mod
    with patch.object(mod.service_request_service, "archive_service_request",
                      return_value=({}, 200)) as archive:
        _web(client, "post", f"/service-requests/{sr}/archive", _blob(UNIT_A))
    archive.assert_called_once()
    assert AuditLog.query.filter(AuditLog.action.like("%.denied")).count() == 0


def test_an_su_admin_passes_the_gate(client, sr):
    import app.routes.service_requests as mod
    with patch.object(mod.service_request_service, "archive_service_request",
                      return_value=({}, 200)) as archive:
        _web(client, "post", f"/service-requests/{sr}/archive", _blob(su=True))
    archive.assert_called_once()


def test_ips_down_refuses_rather_than_admits(client, sr):
    r = _web(client, "get", f"/service-requests/{sr}", _blob(UNIT_A), ips_status=503)
    assert r.status_code == 302
    assert AuditLog.query.filter_by(action="service_request.web.read.denied").first() \
        .details["reason"] == "ips_lookup_failed"


# ------------------------------------------------- 2. professionals and SU only

@pytest.mark.parametrize("blob,ok", [
    (_blob(UNIT_A), True), (_blob(su=True), True),
    (_blob(user_type="patient"), False), (_blob(user_type="patient", su=False), False),
    ({"user_type": "service"}, False), (None, False), ({}, False),
])
def test_web_user_allowed(blob, ok):
    assert web_user_allowed(blob) is ok


def _through_middleware(client, app, url, blob):
    """AUTH ON, so the real requires_auth runs."""
    import app.middleware.auth_middleware as mw
    import app.routes.service_requests as mod
    app.config["AUTH_DISABLED"] = False
    try:
        with patch.object(mw, "get_current_access_blob", return_value=blob), \
             patch.object(mod, "get_current_access_blob", return_value=blob), \
             patch.object(mod, "get_current_user_guid", return_value="u-996"):
            return client.get(url)
    finally:
        app.config["AUTH_DISABLED"] = True


def test_a_PATIENT_login_is_refused_on_the_web(client, app):
    r = _through_middleware(client, app, "/service-requests", _blob(user_type="patient"))
    assert r.status_code == 403
    row = AuditLog.query.filter_by(action="web.access.denied").one()
    assert row.details["reason"] == "not_professional_or_su" and row.details["user_type"] == "patient"


def test_a_professional_reaches_the_web(client, app):
    assert _through_middleware(client, app, "/service-requests", _blob(UNIT_A)).status_code == 200


def test_the_API_is_not_affected_by_the_web_rule(client, app):
    """The API keeps its own per-route gates; the patient rule there is the
    #991 list refusal (403 for no unit), not this one."""
    r = _through_middleware(client, app, "/api/v1/ServiceRequest", _blob(user_type="patient"))
    assert AuditLog.query.filter_by(action="web.access.denied").count() == 0


# ------------------------------------------------- 3. the web lists are audited

@pytest.mark.parametrize("url,action", [("/service-requests", "service_request.web.list"),
                                        ("/service-requests/archived", "service_request.web.archived")])
def test_the_web_lists_write_an_audit_row(client, sr, url, action):
    _web(client, "get", url, _blob(UNIT_A))
    row = AuditLog.query.filter_by(action=action).one()
    assert row.user_guid == "u-996" and row.details["care_unit_count"] == 1

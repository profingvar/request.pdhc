"""X2 operator-session propagation (#423) — request.pdhc adoption.

request.pdhc forwards the operator's X-Operator-Session-Id on the synchronous
onward calls it makes while serving an operator request (contract / plan / ips /
forms / provider / scope / dispatch), so one session_id threads the whole
request -> gateway -> cdr chain end-to-end.
"""
from app.services.session_headers import (
    current_session_id,
    outbound_session_headers,
)
from app.services import (
    contract_service,
    plan_definition_service,
    patient_service,
    form_service,
)

SID = "sess-abc-123"


def test_header_from_forwarded_operator_header(app):
    """A received X-Operator-Session-Id is forwarded onward."""
    with app.test_request_context("/", headers={"X-Operator-Session-Id": SID}):
        assert current_session_id() == SID
        assert outbound_session_headers() == {"X-Operator-Session-Id": SID}


def test_header_from_session_blob_sid(app):
    """The JWT sid claim on the SSO blob (ticket #191) is used when no header."""
    with app.test_request_context("/"):
        from flask import session
        session["access_blob"] = {"session_id": SID}
        assert current_session_id() == SID
        assert outbound_session_headers() == {"X-Operator-Session-Id": SID}


def test_no_header_without_operator_session(app):
    """Machine / legacy calls stay header-less (never an empty header)."""
    with app.test_request_context("/"):
        assert current_session_id() is None
        assert outbound_session_headers() == {}


def test_explicit_session_id_for_background_callers(app):
    """An explicit session_id (async replay) is honoured outside a request."""
    assert outbound_session_headers(SID) == {"X-Operator-Session-Id": SID}


def test_onward_service_headers_include_operator_session(app):
    """The onward-call _headers() helpers carry the operator session when
    present, and omit it when absent."""
    with app.test_request_context("/", headers={"X-Operator-Session-Id": SID}):
        for svc in (contract_service, plan_definition_service,
                    patient_service, form_service):
            assert svc._headers().get("X-Operator-Session-Id") == SID, svc.__name__
    with app.test_request_context("/"):
        for svc in (contract_service, plan_definition_service,
                    patient_service, form_service):
            assert "X-Operator-Session-Id" not in svc._headers(), svc.__name__
